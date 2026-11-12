import threading

import docker
from docker.errors import DockerException
from fastapi import HTTPException

_client = None
_lock = threading.Lock()


def client() -> docker.DockerClient:
    global _client
    with _lock:
        if _client is None:
            try:
                _client = docker.from_env(timeout=30)
                _client.ping()
            except DockerException as e:
                _client = None
                raise HTTPException(503, f"Docker is not available: {e}")
        return _client


def api():
    return client().api


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


def list_containers(project_slug: str | None = None) -> list[dict]:
    filters = {"label": f"com.docker.compose.project={project_slug}"} if project_slug else None
    return [summarize_container(c) for c in api().containers(all=True, filters=filters)]
