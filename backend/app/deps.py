from fastapi import Depends, HTTPException, Request, WebSocket
from sqlalchemy.orm import Session

from .authsec import client_ip, ws_tickets
from .db import get_db
from .models import AuditLog, Project, User
from .security import decode_token

ROLE_LEVEL = {"viewer": 0, "operator": 1, "admin": 2}


def user_from_token(db: Session, token: str | None) -> User | None:
    if not token:
        return None
    decoded = decode_token(token)
    if decoded is None:
        return None
    uid, tv = decoded
    user = db.get(User, uid)
    if not user or not user.is_active or (user.token_version or 0) != tv:
        return None
    return user


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    auth = request.headers.get("Authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else None
    user = user_from_token(db, token)
    if not user:
        raise HTTPException(401, "Not authenticated")
    return user


def require(role: str):
    def dep(user: User = Depends(get_current_user)) -> User:
        if ROLE_LEVEL.get(user.role, -1) < ROLE_LEVEL[role]:
            raise HTTPException(403, f"Requires role '{role}'")
        return user

    return dep


def ws_user(ws: WebSocket, db: Session, role: str = "viewer") -> User | None:
    """Websockets authenticate with a one-time ticket (POST /api/auth/ws-ticket), not the session token."""
    if ws.client:
        client_ip.set(ws.client.host)
    uid = ws_tickets.consume(ws.query_params.get("ticket"))
    if uid is None:
        return None
    user = db.get(User, uid)
    if not user or not user.is_active or ROLE_LEVEL.get(user.role, -1) < ROLE_LEVEL[role]:
        return None
    return user


def get_project(db: Session, project_id: int) -> Project:
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "Project not found")
    return p


def audit(db: Session, user: User | str | None, action: str, target: str = "", details: str = "") -> None:
    name = user.username if isinstance(user, User) else (user or "")
    db.add(AuditLog(username=name, ip=client_ip.get(), action=action, target=target, details=details[:4000]))
    db.commit()
