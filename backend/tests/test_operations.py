"""Regression coverage for file conflicts, deploy drift, log access and health alert transitions."""
from pathlib import Path

from app import alerts
from app.db import SessionLocal
from app.models import Project
from app.routers import projects


def test_config_save_is_conditional(client, auth):
    p = client.post("/api/projects", json={"name": "guarded edits", "source": "empty"}, headers=auth).json()
    url = f"/api/projects/{p['id']}"
    path = "docker-compose.yml"
    source = client.get(url + "/files", params={"path": path}, headers=auth).json()
    data = {"path": path, "revision": source["revision"], "content": source["content"] + "# changed\n"}
    result = client.put(url + "/files", json=data, headers=auth)
    assert result.status_code == 200
    assert client.put(url + "/files", json=data, headers=auth).status_code == 409
    assert client.get(url, headers=auth).json()["pending_config"] == [path]
    data.update(revision=result.json()["revision"], content=source["content"])
    assert client.put(url + "/files", json=data, headers=auth).status_code == 200
    assert client.get(url, headers=auth).json()["pending_config"] == []
    assert Path(p["path"], path).read_bytes() == source["content"].encode()


def test_incident_notifies_once_then_recovers(client, auth, monkeypatch):
    p = client.post("/api/projects", json={"name": "alert transitions", "source": "empty"}, headers=auth).json()
    url = f"/api/projects/{p['id']}"
    client.patch(url, json={"alerts_enabled": True, "environment": "production"}, headers=auth)
    container = {"name": "app-1", "service": "app", "state": "running", "status": "Up (unhealthy)"}
    monkeypatch.setattr(alerts, "list_containers", lambda *args: [container])
    sent = []
    monkeypatch.setattr(alerts, "notify", lambda p, name, recovered, start, now: sent.append((name, recovered)))
    for _ in range(4):
        alerts.sample()
    container["status"] = "Up (healthy)"
    alerts.sample()
    alerts.sample()
    assert sent == [("app", False), ("app", True)]
    with SessionLocal() as db:
        assert db.get(Project, p["id"]).alert_state == "{}"


def test_context_checks_membership_and_centers_event(client, auth, monkeypatch):
    p = client.post("/api/projects", json={"name": "log context", "source": "empty"}, headers=auth).json()
    url = f"/api/projects/{p['id']}/logs/context"
    stamp = "2026-01-01T10:00:00.000000123Z"
    monkeypatch.setattr(projects, "list_containers", lambda *args: [{"id":"owned"}])
    class Logs:
        def logs(self, cid, **kwargs):
            if kwargs.get("stream"):
                return (line for line in [(stamp + " anchor\n").encode(), b"later\n"])
            return b"earlier\n"
    monkeypatch.setattr(projects, "docker_api", lambda sid: Logs())
    params = {"container": "other", "at": stamp}
    assert client.get(url, params=params, headers=auth).status_code == 404
    params["container"] = "owned"
    assert client.get(url, params=params, headers=auth).json() == {
        "before":["earlier"], "line":stamp+" anchor", "after":["later"]}
