from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="viewer")  # viewer | operator | admin
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # bumped on password change / disable -> all previously issued tokens become invalid
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(16), default="git")  # git | local
    path: Mapped[str] = mapped_column(String(1024))
    managed: Mapped[bool] = mapped_column(Boolean, default=True)  # path lives inside projects_dir
    repo_url: Mapped[str] = mapped_column(String(1024), default="")
    branch: Mapped[str] = mapped_column(String(255), default="")
    git_username: Mapped[str] = mapped_column(String(255), default="")
    git_token_enc: Mapped[str] = mapped_column(Text, default="")
    ssh_key: Mapped[str] = mapped_column(String(255), default="")  # file name in ssh_dir, "" = ssh defaults/config
    compose_files: Mapped[str] = mapped_column(String(1024), default="docker-compose.yml")  # comma separated
    env_file: Mapped[str] = mapped_column(String(512), default="")
    webhook_secret: Mapped[str] = mapped_column(String(128), default="")
    webhook_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_rollback: Mapped[bool] = mapped_column(Boolean, default=True)
    health_timeout: Mapped[int] = mapped_column(Integer, default=90)  # seconds to wait for healthy containers
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Deployment(Base):
    """One deploy/rollback with encrypted snapshots of the state before and after (commit, files, image ids)."""
    __tablename__ = "deployments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    job_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kind: Mapped[str] = mapped_column(String(16), default="deploy")  # deploy | rollback
    status: Mapped[str] = mapped_column(String(16), default="running")  # running | success | failed | rolled_back
    username: Mapped[str] = mapped_column(String(64), default="")
    commit_before: Mapped[str] = mapped_column(String(64), default="")
    commit_after: Mapped[str] = mapped_column(String(64), default="")
    before_enc: Mapped[str] = mapped_column(Text, default="")
    after_enc: Mapped[str] = mapped_column(Text, default="")
    message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="running")  # running | success | failed | cancelled
    username: Mapped[str] = mapped_column(String(64), default="")
    output: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Backup(Base):
    """A backup archive in the backup dir: panel state, project files or a docker volume."""
    __tablename__ = "backups"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))  # panel | files | volume
    target: Mapped[str] = mapped_column(String(255), default="")  # volume name / project slug / "panel"
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True)
    filename: Mapped[str] = mapped_column(String(255))
    size: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="running")  # running | success | failed
    username: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Registry(Base):
    """Credentials for private container registries (ghcr.io, gitlab registry, harbor...)."""
    __tablename__ = "registries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    url: Mapped[str] = mapped_column(String(255), unique=True)  # e.g. ghcr.io
    username: Mapped[str] = mapped_column(String(255))
    password_enc: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    username: Mapped[str] = mapped_column(String(64), default="")
    ip: Mapped[str] = mapped_column(String(64), default="")
    action: Mapped[str] = mapped_column(String(64))
    target: Mapped[str] = mapped_column(String(255), default="")
    details: Mapped[str] = mapped_column(Text, default="")
