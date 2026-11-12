from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import ROLE_LEVEL, audit, get_current_user, require
from ..models import AuditLog, User
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


@router.post("/auth/login")
def login(data: LoginIn, db: Session = Depends(get_db)):
    u = db.scalar(select(User).where(User.username == data.username))
    if not u or not u.is_active or not verify_password(data.password, u.password_hash):
        audit(db, data.username, "login.failed")
        raise HTTPException(401, "Invalid username or password")
    audit(db, u, "login")
    return {"token": create_token(u.id), "user": user_out(u)}


@router.get("/auth/me")
def me(user: User = Depends(get_current_user)):
    return user_out(user)


@router.post("/auth/password")
def change_password(data: PasswordIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(data.current_password, user.password_hash):
        raise HTTPException(400, "Current password is wrong")
    user.password_hash = hash_password(data.new_password)
    db.merge(user)
    db.commit()
    audit(db, user, "password.change")
    return {"ok": True}


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
    if data.password:
        u.password_hash = hash_password(data.password)
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
        {"id": r.id, "ts": r.ts, "username": r.username, "action": r.action, "target": r.target, "details": r.details}
        for r in rows
    ]
