"""Docker API clients: the local engine (server_id=None) and remote hosts (servers table)."""
import threading

import docker
from docker.errors import DockerException
from fastapi import HTTPException

_clients: dict[int | None, docker.DockerClient] = {}
_lock = threading.Lock()


def client(server_id: int | None = None) -> docker.DockerClient:
    with _lock:
        c = _clients.get(server_id)
        if c is not None:
            return c
        try:
            if server_id is None:
                c = docker.from_env(timeout=30)
            else:
                from . import servers
                s = servers.get(server_id)
                if not s:
                    raise HTTPException(404, "Server not found")
                url = servers.docker_host(s)
                c = docker.DockerClient(base_url=url, use_ssh_client=url.startswith("ssh://"), timeout=30)
            c.ping()
        except DockerException as e:
            where = "local Docker" if server_id is None else f"server #{server_id}"
            raise HTTPException(503, f"Docker is not available ({where}): {e}")
        _clients[server_id] = c
        return c


def forget(server_id: int | None) -> None:
    """Drop a cached client (server settings changed or connection broke)."""
    with _lock:
        c = _clients.pop(server_id, None)
    if c is not None:
        try:
            c.close()
        except Exception:  # noqa: BLE001
            pass


def api(server_id: int | None = None):
    return client(server_id).api


def summarize_container(c: dict) -> dict:
    labels = c.get("Labels") or {}
    return {
        "id": c["Id"],
        "short_id": c["Id"][:12],
        "name": (c.get("Names") or ["/?"])[0].lstrip("/"),
        "image": c.get("Image"),
        "state": c.get("State"),
        "status": c.get("Status"),
        "created": c.get("Created"),
        "ports": [
            {"private": p.get("PrivatePort"), "public": p.get("PublicPort"), "type": p.get("Type"), "ip": p.get("IP")}
            for p in (c.get("Ports") or [])
        ],
        "project": labels.get("com.docker.compose.project"),
        "service": labels.get("com.docker.compose.service"),
    }


def list_containers(project_slug: str | None = None, server_id: int | None = None) -> list[dict]:
    filters = {"label": f"com.docker.compose.project={project_slug}"} if project_slug else None
    return [summarize_container(c) for c in api(server_id).containers(all=True, filters=filters)]
