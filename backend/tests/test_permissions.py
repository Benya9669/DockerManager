"""Per-project roles."""
import time

import pytest

from app.routers import docker_res


def _login(client, u, pw):
    return {"Authorization": f"Bearer {client.post('/api/auth/login', json={'username': u, 'password': pw}).json()['token']}"}


@pytest.fixture(scope="module")
def setup(client, auth):
    a = client.post("/api/projects", json={"name": f"Perm A {time.time_ns()}", "source": "empty"}, headers=auth).json()
    b = client.post("/api/projects", json={"name": f"Perm B {time.time_ns()}", "source": "empty"}, headers=auth).json()
    uid = client.post("/api/users", json={"username": "perm-user", "password": "permuser1", "role": "viewer"},
                      headers=auth).json()["id"]
    # operator in A, hidden B
    assert client.put(f"/api/users/{uid}/access", json={"project_id": a["id"], "role": "operator"}, headers=auth).status_code == 200
    assert client.put(f"/api/users/{uid}/access", json={"project_id": b["id"], "role": "none"}, headers=auth).status_code == 200
    return a, b, uid, _login(client, "perm-user", "permuser1")


def test_visibility_and_roles(client, setup):
    a, b, _, h = setup
    ids = {p["id"]: p["my_role"] for p in client.get("/api/projects", headers=h).json()}
    assert ids.get(a["id"]) == "operator" and b["id"] not in ids
    assert client.get(f"/api/projects/{b['id']}", headers=h).status_code == 404
    assert client.get(f"/api/projects/{a['id']}", headers=h).json()["my_role"] == "operator"


def test_operator_actions_only_in_granted_project(client, setup):
    a, b, _, h = setup
    # operator-level endpoint: file write allowed in A
    assert client.put(f"/api/projects/{a['id']}/files", json={"path": "x.txt", "content": "1"}, headers=h).status_code == 200
    assert client.put(f"/api/projects/{b['id']}/files", json={"path": "x.txt", "content": "1"}, headers=h).status_code == 404
    # admin-only stays admin-only
    assert client.patch(f"/api/projects/{a['id']}", json={"name": "x"}, headers=h).status_code == 403


def test_default_role_and_reset(client, auth, setup):
    a, b, uid, h = setup
    other = client.post("/api/projects", json={"name": f"Perm C {time.time_ns()}", "source": "empty"}, headers=auth).json()
    # no override -> global viewer
    assert client.get(f"/api/projects/{other['id']}", headers=h).json()["my_role"] == "viewer"
    assert client.put(f"/api/projects/{other['id']}/files", json={"path": "y", "content": ""}, headers=h).status_code == 403
    acc = client.get(f"/api/users/{uid}/access", headers=auth).json()
    assert {p["project_id"]: p["role"] for p in acc["projects"]}[a["id"]] == "operator"
    client.put(f"/api/users/{uid}/access", json={"project_id": b["id"], "role": None}, headers=auth)
    assert client.get(f"/api/projects/{b['id']}", headers=h).status_code == 200


def test_containers_filtered_by_project(client, setup, monkeypatch):
    a, b, _, h = setup

    class FakeAPI:
        def containers(self, all=True, filters=None):
            return [{"Id": f"id-{s}", "Names": [f"/{s}-1"], "Labels": {"com.docker.compose.project": s}, "State": "running"}
                    for s in (a["slug"], b["slug"], "standalone")]

        def inspect_container(self, cid):
            slug = cid.removeprefix("id-")
            return {"Id": cid, "Config": {"Labels": {"com.docker.compose.project": slug}, "Env": ["SECRET=1"]}}

    monkeypatch.setattr(docker_res, "list_containers", lambda: [
        {"id": c["Id"], "project": c["Labels"]["com.docker.compose.project"], "name": c["Names"][0][1:], "state": "running"}
        for c in FakeAPI().containers()])
    monkeypatch.setattr(docker_res, "api", lambda: FakeAPI())
    names = {c["project"]: c["my_role"] for c in client.get("/api/docker/containers", headers=h).json()}
    assert names.get(a["slug"]) == "operator" and "standalone" in names
    # B is hidden only while override "none" exists (may be reset by previous test) -> check A env visible
    assert "SECRET=1" in str(client.get(f"/api/docker/containers/id-{a['slug']}", headers=h).json())
    assert "SECRET=1" not in str(client.get("/api/docker/containers/id-standalone", headers=h).json())
