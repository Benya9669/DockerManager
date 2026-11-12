from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..access import PROJECT_ROLES
from ..authsec import throttle, ws_tickets
from ..config import settings
from ..db import get_db
from ..deps import ROLE_LEVEL, audit, get_current_user, require
from ..models import AuditLog, Project, ProjectAccess, User
from ..security import create_token, hash_password, verify_password

router = APIRouter(prefix="/api", tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str


class PasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8)


class UserIn(BaseModel):
    username: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9_.@-]+$")
    password: str = Field(min_length=8)
    role: str = "viewer"


class UserPatch(BaseModel):
    password: str | None = Field(default=None, min_length=8)
    role: str | None = None
    is_active: bool | None = None


def user_out(u: User) -> dict:
    return {"id": u.id, "username": u.username, "role": u.role, "is_active": u.is_active, "created_at": u.created_at}


_DUMMY_HASH = hash_password("timing-equalizer")


def _ip(request: Request) -> str:
    return request.client.host if request.client else ""


def _revoke_sessions(u: User) -> None:
    u.token_version = (u.token_version or 0) + 1


def _forget_initial_password(u: User) -> None:
    f = settings.data_dir / "initial_admin_password.txt"
    if u.username == settings.admin_username and f.exists():
        f.unlink(missing_ok=True)


@router.post("/auth/login")
def login(data: LoginIn, request: Request, db: Session = Depends(get_db)):
    ip = _ip(request)
    wait = throttle.retry_after(ip, data.username)
    if wait:
        raise HTTPException(429, f"Слишком много неудачных попыток входа. Повторите через {wait // 60 + 1} мин.")
    u = db.scalar(select(User).where(User.username == data.username))
    # always run the hash so response time doesn't reveal whether the user exists
    ok = verify_password(data.password, u.password_hash if u else _DUMMY_HASH)
    if not u or not u.is_active or not ok:
        throttle.fail(ip, data.username)
        audit(db, data.username, "login.failed")
        raise HTTPException(401, "Invalid username or password")
    throttle.success(ip, data.username)
    audit(db, u, "login")
    return {"token": create_token(u.id, u.token_version or 0), "user": user_out(u)}


@router.get("/auth/me")
def me(user: User = Depends(get_current_user)):
    return user_out(user)


@router.post("/auth/ws-ticket")
def ws_ticket(user: User = Depends(get_current_user)):
    """Single-use ticket (30s) for opening one websocket; keeps the session token out of URLs."""
    return {"ticket": ws_tickets.issue(user.id)}


@router.post("/auth/password")
def change_password(data: PasswordIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(data.current_password, user.password_hash):
        raise HTTPException(400, "Current password is wrong")
    user.password_hash = hash_password(data.new_password)
    _revoke_sessions(user)  # log out all other sessions
    db.commit()
    _forget_initial_password(user)
    audit(db, user, "password.change")
    return {"ok": True, "token": create_token(user.id, user.token_version)}


@router.get("/users")
def list_users(_: User = Depends(require("admin")), db: Session = Depends(get_db)):
    return [user_out(u) for u in db.scalars(select(User).order_by(User.username))]


@router.post("/users")
def create_user(data: UserIn, admin: User = Depends(require("admin")), db: Session = Depends(get_db)):
    if data.role not in ROLE_LEVEL:
        raise HTTPException(400, "Invalid role")
    if db.scalar(select(User).where(User.username == data.username)):
        raise HTTPException(409, "User already exists")
    u = User(username=data.username, password_hash=hash_password(data.password), role=data.role)
    db.add(u)
    db.commit()
    audit(db, admin, "user.create", data.username, f"role={data.role}")
    return user_out(u)


@router.patch("/users/{user_id}")
def update_user(user_id: int, data: UserPatch, admin: User = Depends(require("admin")), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    if data.role is not None:
        if data.role not in ROLE_LEVEL:
            raise HTTPException(400, "Invalid role")
        if u.id == admin.id and data.role != "admin":
            raise HTTPException(400, "You cannot demote yourself")
        u.role = data.role
    if data.is_active is not None:
        if u.id == admin.id and not data.is_active:
            raise HTTPException(400, "You cannot disable yourself")
        u.is_active = data.is_active
        if not data.is_active:
            _revoke_sessions(u)
    if data.password:
        u.password_hash = hash_password(data.password)
        _revoke_sessions(u)
        _forget_initial_password(u)
    if data.role is not None:
        _revoke_sessions(u)  # role changes take effect immediately everywhere
    db.commit()
    audit(db, admin, "user.update", u.username, data.model_dump_json(exclude={"password"}, exclude_none=True))
    return user_out(u)


@router.delete("/users/{user_id}")
def delete_user(user_id: int, admin: User = Depends(require("admin")), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    if u.id == admin.id:
        raise HTTPException(400, "You cannot delete yourself")
    db.delete(u)
    db.commit()
    audit(db, admin, "user.delete", u.username)
    return {"ok": True}


@router.get("/audit")
def list_audit(limit: int = 200, _: User = Depends(require("admin")), db: Session = Depends(get_db)):
    rows = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 1000)))
    return [
        {"id": r.id, "ts": r.ts, "username": r.username, "ip": r.ip, "action": r.action, "target": r.target, "details": r.details}
        for r in rows
    ]


# ---------- per-project access ----------
class AccessIn(BaseModel):
    project_id: int
    role: str | None = None  # none | viewer | operator; null -> use global role


@router.get("/users/{user_id}/access")
def get_access(user_id: int, _: User = Depends(require("admin")), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if not u:
        raise HTTPException(404, "User not found")
    overrides = {r.project_id: r.role for r in db.scalars(select(ProjectAccess).where(ProjectAccess.user_id == u.id))}
    return {
        "global_role": u.role,
        "projects": [{"project_id": p.id, "name": p.name, "slug": p.slug, "role": overrides.get(p.id)}
                     for p in db.scalars(select(Project).order_by(Project.name))],
    }


@router.put("/users/{user_id}/access")
def set_access(user_id: int, data: AccessIn, admin: User = Depends(require("admin")), db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    p = db.get(Project, data.project_id)
    if not u or not p:
        raise HTTPException(404, "Not found")
    if data.role is not None and data.role not in PROJECT_ROLES:
        raise HTTPException(400, f"role must be one of {PROJECT_ROLES} or null")
    row = db.scalar(select(ProjectAccess).where(ProjectAccess.user_id == u.id, ProjectAccess.project_id == p.id))
    if data.role is None:
        if row:
            db.delete(row)
    elif row:
        row.role = data.role
    else:
        db.add(ProjectAccess(user_id=u.id, project_id=p.id, role=data.role))
    db.commit()
    audit(db, admin, "user.access", u.username, f"{p.slug}={data.role or 'default'}")
    return {"ok": True}
