"""Remote Docker hosts.

`ssh://user@host` hosts are reached through the ssh client (docker CLI and docker SDK both use it).
To use a specific key per server the panel writes host aliases into <ssh dir>/dm_servers.conf
(when DM_MANAGE_SSH_CONFIG=true) and points DOCKER_HOST at ssh://dm-server-<id>.
"""
import re
from urllib.parse import urlparse

from sqlalchemy import select

from .config import settings
from .db import SessionLocal
from .models import Project, Server

MANAGED_CONF = "dm_servers.conf"
INCLUDE_LINE = f"Include {MANAGED_CONF}"
# user/host must start with a letter/digit so nothing can be parsed by ssh as an option
URL_RE = re.compile(r"^(ssh://[A-Za-z0-9][\w.-]*@[A-Za-z0-9][\w.-]*(:\d+)?|tcp://[A-Za-z0-9][\w.-]*:\d+)$")


def get(server_id: int | None) -> Server | None:
    if server_id is None:
        return None
    db = SessionLocal()
    try:
        return db.get(Server, server_id)
    finally:
        db.close()


def alias(s: Server) -> str:
    return f"dm-server-{s.id}"


def docker_host(s: Server) -> str:
    if s.docker_host.startswith("ssh://") and settings.manage_ssh_config:
        return f"ssh://{alias(s)}"
    return s.docker_host


def env_for(server_id: int | None) -> dict[str, str]:
    s = get(server_id)
    return {"DOCKER_HOST": docker_host(s)} if s else {}


def docker_env(p: Project) -> dict[str, str]:
    return env_for(p.server_id)


def write_ssh_config() -> None:
    """Regenerate host aliases for ssh servers (each with its own key) and include them from ~/.ssh/config."""
    if not settings.manage_ssh_config:
        return
    d = settings.ssh_dir
    d.mkdir(parents=True, exist_ok=True)
    db = SessionLocal()
    try:
        servers = db.scalars(select(Server)).all()
    finally:
        db.close()
    blocks = ["# Managed by Docker Manager — do not edit, changes are overwritten\n"]
    for s in servers:
        u = urlparse(s.docker_host)
        if u.scheme != "ssh":
            continue
        lines = [f"Host {alias(s)}", f"  HostName {u.hostname}", f"  User {u.username}",
                 "  StrictHostKeyChecking accept-new", "  BatchMode yes",
                 "  ControlMaster auto", "  ControlPath /tmp/dm-ssh-%r@%h-%p", "  ControlPersist 60"]
        if u.port:
            lines.append(f"  Port {u.port}")
        if s.ssh_key:
            lines += [f"  IdentityFile {(d / s.ssh_key).as_posix()}", "  IdentitiesOnly yes"]
        blocks.append("\n".join(lines) + "\n")
    (d / MANAGED_CONF).write_text("\n".join(blocks))
    cfg = d / "config"
    current = cfg.read_text() if cfg.exists() else ""
    if INCLUDE_LINE not in current:
        cfg.write_text(f"{INCLUDE_LINE}\n\n{current}")  # Include must come before any Host block
    try:
        cfg.chmod(0o600)
        (d / MANAGED_CONF).chmod(0o600)
    except OSError:
        pass
