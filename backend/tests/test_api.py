import json

from app import discover, registries, version


def test_health_and_version(client):
    assert client.get("/api/health").json() == {"ok": True}
    assert client.get("/api/version").json()["version"]


def test_auth(client, auth):
    assert client.post("/api/auth/login", json={"username": "admin", "password": "nope"}).status_code == 401
    assert client.get("/api/projects").status_code == 401
    assert client.get("/api/auth/me", headers=auth).json()["role"] == "admin"


def test_roles(client, auth):
    r = client.post("/api/users", json={"username": "viewer1", "password": "viewerpass1", "role": "viewer"}, headers=auth)
    assert r.status_code == 200
    tok = client.post("/api/auth/login", json={"username": "viewer1", "password": "viewerpass1"}).json()["token"]
    h = {"Authorization": f"Bearer {tok}"}
    assert client.get("/api/projects", headers=h).status_code == 200
    assert client.post("/api/projects", json={"name": "x", "source": "empty"}, headers=h).status_code == 403
    assert client.get("/api/users", headers=h).status_code == 403


def test_project_files_env(client, auth):
    p = client.post("/api/projects", json={"name": "Demo App", "source": "empty"}, headers=auth).json()
    pid = p["id"]
    assert p["slug"] == "demo-app"
    entries = client.get(f"/api/projects/{pid}/files", headers=auth).json()["entries"]
    assert any(e["name"] == "docker-compose.yml" for e in entries)

    assert client.put(f"/api/projects/{pid}/files", json={"path": ".env.prod", "content": "A=1\n"}, headers=auth).status_code == 200
    assert client.put(f"/api/projects/{pid}/files", json={"path": "../evil", "content": "x"}, headers=auth).status_code == 400
    assert client.put(f"/api/projects/{pid}/files", json={"path": ".git/config", "content": "x"}, headers=auth).status_code == 400

    assert client.get(f"/api/projects/{pid}/env-files", headers=auth).json()["files"] == [".env.prod"]
    assert client.post(f"/api/projects/{pid}/env", json={"path": ".env.prod"}, headers=auth).json()["env_file"] == ".env.prod"
    assert client.post(f"/api/projects/{pid}/env", json={"path": "missing.env"}, headers=auth).status_code == 404

    assert client.post(f"/api/projects/{pid}/actions/nope", json={}, headers=auth).status_code == 400
    assert client.delete(f"/api/projects/{pid}?remove_files=true", headers=auth).status_code == 200


def test_ssh_keys(client, auth, tmp_root):
    d = tmp_root / "ssh"
    d.mkdir(exist_ok=True)
    (d / "id_rsa_bny").write_text("-----BEGIN OPENSSH PRIVATE KEY-----\nx\n-----END OPENSSH PRIVATE KEY-----\n")
    (d / "id_rsa_bny.pub").write_text("ssh-rsa AAAA test\n")
    (d / "known_hosts").write_text("")
    keys = client.get("/api/projects/ssh-keys", headers=auth).json()["keys"]
    assert [k["name"] for k in keys] == ["id_rsa_bny"]


def test_registry_config(client, auth):
    r = client.post("/api/registries", json={"url": "https://ghcr.io/", "username": "u", "password": "tok", "verify": False}, headers=auth)
    assert r.status_code == 200 and r.json()["url"] == "ghcr.io"
    cfg = json.loads((registries.DOCKER_CONFIG_DIR / "config.json").read_text())
    assert "ghcr.io" in cfg["auths"]
    assert "password" not in json.dumps(client.get("/api/registries", headers=auth).json())
    client.delete(f"/api/registries/{r.json()['id']}", headers=auth)
    cfg = json.loads((registries.DOCKER_CONFIG_DIR / "config.json").read_text())
    assert cfg["auths"] == {}


def test_discover_import(client, auth, tmp_root, monkeypatch):
    stack = tmp_root / "shop"
    stack.mkdir()
    (stack / "docker-compose.yml").write_text("services:\n  web:\n    image: nginx\n")

    class FakeAPI:
        def containers(self, all=True, filters=None):
            labels = {
                "com.docker.compose.project": "shop", "com.docker.compose.service": "web",
                "com.docker.compose.project.working_dir": str(stack),
                "com.docker.compose.project.config_files": str(stack / "docker-compose.yml"),
            }
            return [{"Labels": labels, "State": "running"}]

    monkeypatch.setattr(discover, "api", lambda: FakeAPI())
    found = client.get("/api/projects/discover", headers=auth).json()
    assert found[0]["slug"] == "shop" and found[0]["accessible"]
    p = client.post("/api/projects/import", json={"slug": "shop"}, headers=auth).json()
    assert p["compose_files"] == "docker-compose.yml" and not p["managed"]
    assert client.post("/api/projects/import", json={"slug": "shop"}, headers=auth).status_code == 409


def test_version_compare():
    assert version.is_newer("0.10.0", "0.9.9")
    assert not version.is_newer("0.2.0", "0.2.0")
    assert not version.is_newer(None, "0.2.0")
