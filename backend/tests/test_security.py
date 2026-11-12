import pytest
from starlette.websockets import WebSocketDisconnect

from app import git_ops
from app.authsec import throttle
from app.models import Project
from app.routers import docker_res
from app.security import encrypt


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="module")
def viewer(client, auth):
    client.post("/api/users", json={"username": "sec-viewer", "password": "viewerpass1", "role": "viewer"}, headers=auth)
    return _login(client, "sec-viewer", "viewerpass1")


def test_webhook_secret_admin_only(client, auth, viewer):
    pid = client.post("/api/projects", json={"name": "Sec Hook", "source": "empty"}, headers=auth).json()["id"]
    assert client.get(f"/api/projects/{pid}", headers=auth).json()["webhook_secret"]
    v = client.get(f"/api/projects/{pid}", headers=viewer).json()
    assert v["webhook_secret"] == "" and v["webhook_url"] == ""
    assert all(p["webhook_secret"] == "" for p in client.get("/api/projects", headers=viewer).json())


def test_container_env_hidden_from_viewer(client, auth, viewer, monkeypatch):
    class FakeAPI:
        def inspect_container(self, cid):
            return {"Id": cid, "Config": {"Env": ["DB_PASSWORD=secret"]}, "HostConfig": {"Binds": []}}

    monkeypatch.setattr(docker_res, "api", lambda *a, **k: FakeAPI())
    assert "DB_PASSWORD=secret" not in str(client.get("/api/docker/containers/abc", headers=viewer).json())
    assert "DB_PASSWORD=secret" in str(client.get("/api/docker/containers/abc", headers=auth).json())


def test_git_token_not_in_argv():
    p = Project(slug="x", path="/tmp/x", repo_url="https://git.example.com/a/b.git", branch="main",
                git_username="oauth2", git_token_enc=encrypt("SUPERSECRET"), ssh_key="")
    import base64
    secret_b64 = base64.b64encode(b"oauth2:SUPERSECRET").decode()
    for _, argv in git_ops.clone_steps(p) + git_ops.pull_steps(p):
        assert not any(secret_b64 in a or "SUPERSECRET" in a for a in argv)
    env = git_ops.git_env(p)
    assert any(secret_b64 in v for v in env.values())
    clone = git_ops.clone_steps(p)[0][1]
    assert clone[clone.index("--") + 1] == p.repo_url


@pytest.mark.parametrize("path,body", [
    ("/api/docker/images/pull", {"image": "--help"}),
    ("/api/projects", {"name": "inj", "source": "git", "repo_url": "--upload-pack=touch /tmp/pwned"}),
    ("/api/projects", {"name": "inj2", "source": "git", "repo_url": "https://x/y.git", "branch": "--orphan"}),
    ("/api/projects", {"name": "inj3", "source": "empty", "compose_files": "-x"}),
])
def test_option_injection_rejected(client, auth, path, body):
    assert client.post(path, json=body, headers=auth).status_code == 422


def test_service_and_branch_injection_rejected(client, auth):
    pid = client.post("/api/projects", json={"name": "Inj Svc", "source": "empty"}, headers=auth).json()["id"]
    assert client.post(f"/api/projects/{pid}/actions/up", json={"service": "--build"}, headers=auth).status_code == 422
    assert client.post(f"/api/projects/{pid}/git/checkout", json={"branch": "-b"}, headers=auth).status_code == 422


def test_token_revoked_on_password_change(client, auth):
    client.post("/api/users", json={"username": "sec-rot", "password": "oldpassword1", "role": "viewer"}, headers=auth)
    old = _login(client, "sec-rot", "oldpassword1")
    r = client.post("/api/auth/password", json={"current_password": "oldpassword1", "new_password": "newpassword1"}, headers=old)
    assert r.status_code == 200
    assert client.get("/api/auth/me", headers=old).status_code == 401
    new = {"Authorization": f"Bearer {r.json()['token']}"}
    assert client.get("/api/auth/me", headers=new).status_code == 200


def test_ws_requires_ticket(client, auth):
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/jobs/999999/stream") as ws:
            ws.receive_json()
    # old style ?token= no longer accepted
    token = auth["Authorization"].split()[1]
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/api/jobs/999999/stream?token={token}") as ws:
            ws.receive_json()
    ticket = client.post("/api/auth/ws-ticket", headers=auth).json()["ticket"]
    with client.websocket_connect(f"/api/jobs/999999/stream?ticket={ticket}") as ws:
        assert ws.receive_json() == {"type": "error", "data": "Job not found"}
    # single use
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/api/jobs/999999/stream?ticket={ticket}") as ws:
            ws.receive_json()


def test_security_headers_and_audit_ip(client, auth):
    r = client.get("/api/version")
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert client.get("/docs").status_code != 200 or "swagger" not in client.get("/docs").text.lower()
    audit = client.get("/api/audit?limit=5", headers=auth).json()
    assert audit and audit[0]["ip"]


def test_login_throttle(client):
    try:
        for _ in range(10):
            client.post("/api/auth/login", json={"username": "brute", "password": "x"})
        r = client.post("/api/auth/login", json={"username": "admin", "password": "testpass123"})
        assert r.status_code == 429
    finally:
        throttle.fails.clear()
        throttle.blocked_until.clear()
