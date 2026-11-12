"""Remote docker hosts."""
import time

from app import compose, servers
from app.config import settings
from app.db import SessionLocal
from app.models import Project
from app.routers import docker_res


def test_server_crud_and_validation(client, auth):
    assert client.post("/api/servers", json={"name": "bad", "docker_host": "http://x"}, headers=auth).status_code == 422
    for bad in ("ssh://-oProxyCommand=x@h", "ssh://-v@host", "ssh://user@-host", "tcp://-x:2375"):
        assert client.post("/api/servers", json={"name": "bad2", "docker_host": bad}, headers=auth).status_code == 422
    s = client.post("/api/servers", json={"name": f"prod-{time.time_ns()}", "docker_host": "ssh://deploy@10.0.0.5:2222"},
                    headers=auth).json()
    lst = client.get("/api/servers", headers=auth).json()
    assert any(x["id"] == s["id"] for x in lst["servers"])
    assert client.patch(f"/api/servers/{s['id']}", json={"description": "main"}, headers=auth).json()["description"] == "main"

    p = client.post("/api/projects", json={"name": f"Remote {time.time_ns()}", "source": "empty", "server_id": s["id"]},
                    headers=auth).json()
    assert p["server_id"] == s["id"] and p["server_name"] == s["name"]
    db = SessionLocal()
    proj = db.get(Project, p["id"])
    db.close()
    assert compose.env(proj)["DOCKER_HOST"] == "ssh://deploy@10.0.0.5:2222"
    # cannot delete a server that still has projects
    assert client.delete(f"/api/servers/{s['id']}", headers=auth).status_code == 409
    client.patch(f"/api/projects/{p['id']}", json={"set_server": True, "server_id": None}, headers=auth)
    assert client.get(f"/api/projects/{p['id']}", headers=auth).json()["server_id"] is None
    assert client.delete(f"/api/servers/{s['id']}", headers=auth).status_code == 200


def test_managed_ssh_config(client, auth, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "manage_ssh_config", True)
    monkeypatch.setattr(settings, "ssh_dir", tmp_path)
    (tmp_path / "config").write_text("Host github.com\n  User git\n")
    (tmp_path / "id_rsa_bny").write_text("-----BEGIN OPENSSH PRIVATE KEY-----\nx\n")
    s = client.post("/api/servers", json={"name": f"ssh-{time.time_ns()}", "docker_host": "ssh://ops@srv.local",
                                          "ssh_key": "id_rsa_bny"}, headers=auth).json()
    conf = (tmp_path / "dm_servers.conf").read_text()
    assert f"Host dm-server-{s['id']}" in conf and "IdentityFile" in conf and "id_rsa_bny" in conf
    main = (tmp_path / "config").read_text()
    assert main.startswith("Include dm_servers.conf") and "Host github.com" in main
    assert servers.docker_host(servers.get(s["id"])) == f"ssh://dm-server-{s['id']}"
    client.delete(f"/api/servers/{s['id']}", headers=auth)


def test_docker_endpoints_route_to_server(client, auth, monkeypatch):
    seen = []

    class FakeAPI:
        def images(self):
            return []

        def containers(self, all=True, filters=None):
            return []

    monkeypatch.setattr(docker_res, "api", lambda sid=None: seen.append(sid) or FakeAPI())
    monkeypatch.setattr(docker_res, "list_containers", lambda *a, server_id=None, **k: seen.append(server_id) or [])
    assert client.get("/api/docker/images?server_id=7", headers=auth).status_code == 200
    assert seen and all(s == 7 for s in seen)
