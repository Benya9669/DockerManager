"""Effective per-project roles.

global admin                 -> admin everywhere
ProjectAccess row for project -> that role (none | viewer | operator)
otherwise                    -> the user's global role
"""
from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .deps import ROLE_LEVEL, get_current_user
from .models import Project, ProjectAccess, User

PROJECT_ROLES = ("none", "viewer", "operator")


def level(role: str | None) -> int:
    return ROLE_LEVEL.get(role or "none", -1)


def project_role(db: Session, user: User, project_id: int | None) -> str:
    if user.role == "admin":
        return "admin"
    if project_id is None:
        return user.role
    row = db.scalar(select(ProjectAccess).where(ProjectAccess.user_id == user.id,
                                                ProjectAccess.project_id == project_id))
    return row.role if row else user.role


def role_for_slug(db: Session, user: User, slug: str | None) -> str:
    """Role for a compose project name (container label); non-panel stacks use the global role."""
    if user.role == "admin" or not slug:
        return user.role
    p = db.scalar(select(Project).where(Project.slug == slug))
    return project_role(db, user, p.id) if p else user.role


def roles_by_project(db: Session, user: User) -> dict[int, str]:
    """Effective role for every project (one query)."""
    if user.role == "admin":
        return {pid: "admin" for pid in db.scalars(select(Project.id))}
    overrides = {r.project_id: r.role for r in db.scalars(select(ProjectAccess).where(ProjectAccess.user_id == user.id))}
    return {pid: overrides.get(pid, user.role) for pid in db.scalars(select(Project.id))}


def roles_by_slug(db: Session, user: User) -> dict[str, str]:
    roles = roles_by_project(db, user)
    return {slug: roles[pid] for pid, slug in db.execute(select(Project.id, Project.slug)).all()}


def require_project(need: str):
    """Dependency for endpoints with a `project_id` path parameter."""
    def dep(project_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
        if not db.get(Project, project_id):
            raise HTTPException(404, "Project not found")
        role = project_role(db, user, project_id)
        if level(role) < level("viewer"):
            raise HTTPException(404, "Project not found")  # don't reveal hidden projects
        if level(role) < level(need):
            raise HTTPException(403, f"Requires role '{need}' in this project")
        return user

    return dep
