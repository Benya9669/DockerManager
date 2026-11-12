from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import git_ops, servers
from ..db import get_db
from ..deps import audit, require
from ..dockerc import api, forget
from ..models import Project, Server, User

router = APIRouter(prefix="/api/servers", tags=["servers"])


class ServerIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    docker_host: str = Field(min_length=1, max_length=512)
    ssh_key: str = ""
    description: str = ""

    @field_validator("docker_host")
    @classmethod
    def _v_host(cls, v: str) -> str:
        v = v.strip()
        if not servers.URL_RE.match(v):
            raise ValueError("docker_host: ssh://user@host[:port] или tcp://host:port")
        return v


class ServerPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    docker_host: str | None = None
    ssh_key: str | None = None
    description: str | None = None

    @field_validator("docker_host")
    @classmethod
    def _v_host(cls, v):
        return ServerIn._v_host(v) if v is not None else v


def _check_key(name: str) -> str:
    name = (name or "").strip()
    if name and name not in {k["name"] for k in git_ops.list_ssh_keys()}:
        raise HTTPException(400, f"SSH key '{name}' not found")
    return name


def out(s: Server, projects: int = 0) -> dict:
    return {"id": s.id, "name": s.name, "docker_host": s.docker_host, "ssh_key": s.ssh_key,
            "description": s.description, "created_at": s.created_at, "projects": projects}


@router.get("")
def list_servers(_: User = Depends(require("viewer")), db: Session = Depends(get_db)):
    counts = dict(db.execute(select(Project.server_id, func.count()).group_by(Project.server_id)).all())
    return {
        "local": {"projects": counts.get(None, 0)},
        "servers": [out(s, counts.get(s.id, 0)) for s in db.scalars(select(Server).order_by(Server.name))],
    }


@router.post("")
def add_server(data: ServerIn, user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    if db.scalar(select(Server).where(Server.name == data.name)):
        raise HTTPException(409, "Server with this name exists")
    s = Server(name=data.name.strip(), docker_host=data.docker_host, ssh_key=_check_key(data.ssh_key),
               description=data.description)
    db.add(s)
    db.commit()
    servers.write_ssh_config()
    audit(db, user, "server.add", s.name, s.docker_host)
    return out(s)


@router.patch("/{server_id}")
def update_server(server_id: int, data: ServerPatch, user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    s = db.get(Server, server_id)
    if not s:
        raise HTTPException(404, "Server not found")
    if data.name is not None:
        s.name = data.name.strip()
    if data.docker_host is not None:
        s.docker_host = data.docker_host
    if data.ssh_key is not None:
        s.ssh_key = _check_key(data.ssh_key)
    if data.description is not None:
        s.description = data.description
    db.commit()
    servers.write_ssh_config()
    forget(server_id)
    audit(db, user, "server.update", s.name)
    return out(s)


@router.delete("/{server_id}")
def delete_server(server_id: int, user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    s = db.get(Server, server_id)
    if not s:
        raise HTTPException(404, "Server not found")
    if db.scalar(select(func.count()).select_from(Project).where(Project.server_id == server_id)):
        raise HTTPException(409, "На сервере есть проекты — перенесите или удалите их")
    db.delete(s)
    db.commit()
    servers.write_ssh_config()
    forget(server_id)
    audit(db, user, "server.delete", s.name)
    return {"ok": True}


@router.post("/{server_id}/test")
def test_server(server_id: int, _: User = Depends(require("admin")), db: Session = Depends(get_db)):
    if not db.get(Server, server_id):
        raise HTTPException(404, "Server not found")
    forget(server_id)
    try:
        v = api(server_id).version()
        i = api(server_id).info()
    except HTTPException as e:
        return {"ok": False, "error": e.detail}
    except Exception as e:  # noqa: BLE001
        forget(server_id)
        return {"ok": False, "error": str(e)}
    return {"ok": True, "version": v.get("Version"), "os": i.get("OperatingSystem"), "name": i.get("Name"),
            "cpus": i.get("NCPU"), "mem_total": i.get("MemTotal"), "containers": i.get("Containers")}
