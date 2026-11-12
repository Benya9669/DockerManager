"""Job runner, git operations and webhook signature checks."""
import hashlib
import hmac
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app import git_ops
from app.db import SessionLocal
from app.jobs import BusyError, runner
from app.models import Job, Project

PY = sys.executable


def wait_job(job_id: int, timeout: float = 20) -> Job:
    end = time.time() + timeout
    while time.time() < end:
        if job_id not in runner.live:
            db = SessionLocal()
            j = db.get(Job, job_id)
            db.close()
            if j and j.status != "running":
                return j
        time.sleep(0.05)
    raise AssertionError("job did not finish")


# ---------------- job runner ----------------
def test_job_success_and_output(client):
    jid = runner.start(action="t.ok", steps=[("say hi", [PY, "-c", "print('hello-from-job')"])])
    j = wait_job(jid)
    assert j.status == "success"
    assert "hello-from-job" in j.output and "say hi" in j.output


def test_job_stops_on_failure(client):
    jid = runner.start(action="t.fail", steps=[
        ("fail", [PY, "-c", "import sys; sys.exit(3)"]),
        ("never", [PY, "-c", "print('SHOULD-NOT-RUN')"]),
    ])
    j = wait_job(jid)
    assert j.status == "failed"
    assert "Exit code 3" in j.output and "SHOULD-NOT-RUN" not in j.output


def test_job_env_and_on_success(client):
    called = []
    jid = runner.start(action="t.env", steps=[("env", [PY, "-c", "import os; print(os.environ['DM_T'])"])],
                       env={"DM_T": "value-42"}, on_success=lambda: called.append(1))
    j = wait_job(jid)
    assert "value-42" in j.output and called == [1]


def test_job_busy_lock_and_cancel(client):
    jid = runner.start(action="t.slow", project_id=987654,
                       steps=[("sleep", [PY, "-c", "import time; time.sleep(30)"])])
    with pytest.raises(BusyError):
        runner.start(action="t.second", project_id=987654, steps=[("x", [PY, "-c", "pass"])])
    time.sleep(0.3)
    assert runner.cancel(jid)
    j = wait_job(jid)
    assert j.status == "cancelled"
    assert not runner.is_busy(987654)


def test_job_missing_binary(client):
    jid = runner.start(action="t.missing", steps=[("nope", ["definitely-not-a-binary-xyz"])])
    assert wait_job(jid).status == "failed"


def test_job_stream_ws(client, auth):
    jid = runner.start(action="t.ws", steps=[("hi", [PY, "-c", "print('streamed')"])])
    wait_job(jid)
    ticket = client.post("/api/auth/ws-ticket", headers=auth).json()["ticket"]
    with client.websocket_connect(f"/api/jobs/{jid}/stream?ticket={ticket}") as ws:
        line = ws.receive_json()
        done = ws.receive_json()
    assert "streamed" in line["data"] and done == {"type": "done", "data": "success"}


# ---------------- git ----------------
def _git(cwd, *args):
    r = subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


@pytest.fixture()
def origin(tmp_path):
    o = tmp_path / "origin"
    o.mkdir()
    _git(o, "init", "-b", "main")
    (o / "docker-compose.yml").write_text("services: {}\n")
    _git(o, "add", ".")
    _git(o, "commit", "-m", "first")
    return o


def test_git_clone_status_pull(client, origin, tmp_path):
    p = Project(slug="g", path=str(tmp_path / "clone"), repo_url=str(origin), branch="main",
                git_username="", git_token_enc="", ssh_key="")
    jid = runner.start(action="t.clone", steps=git_ops.clone_steps(p), cwd=str(tmp_path), env=git_ops.git_env(p))
    j = wait_job(jid)
    assert j.status == "success", j.output

    st = git_ops.status(p)
    assert st["is_repo"] and st["branch"] == "main" and st["behind"] == 0
    assert st["commit"]["subject"] == "first"

    (origin / "new.txt").write_text("x")
    _git(origin, "add", ".")
    _git(origin, "commit", "-m", "second")
    git_ops.fetch(p)
    assert git_ops.status(p)["behind"] == 1

    jid = runner.start(action="t.pull", steps=git_ops.pull_steps(p), cwd=p.path, env=git_ops.git_env(p))
    assert wait_job(jid).status == "success"
    assert git_ops.status(p)["behind"] == 0
    assert [c["subject"] for c in git_ops.log(p, 5)] == ["second", "first"]
    assert "main" in git_ops.branches(p)["local"]


def test_git_dirty_detected(client, origin, tmp_path):
    clone = tmp_path / "c2"
    _git(tmp_path, "clone", str(origin), str(clone))
    p = Project(slug="g2", path=str(clone), repo_url=str(origin), branch="main", git_token_enc="", ssh_key="")
    (clone / "docker-compose.yml").write_text("changed\n")
    assert git_ops.status(p)["changes"]


def test_ssh_command_uses_selected_key():
    p = Project(slug="k", path=".", repo_url="git@github.com:a/b.git", git_token_enc="", ssh_key="id_rsa_bny")
    cmd = git_ops.git_env(p)["GIT_SSH_COMMAND"]
    assert "id_rsa_bny" in cmd and "IdentitiesOnly=yes" in cmd


# ---------------- webhooks ----------------
@pytest.fixture()
def hook_project(client, auth, monkeypatch):
    pid = client.post("/api/projects", json={"name": f"Hook {time.time_ns()}", "source": "empty"}, headers=auth).json()["id"]
    p = client.patch(f"/api/projects/{pid}", json={"webhook_enabled": True}, headers=auth).json()
    db = SessionLocal()
    proj = db.get(Project, pid)
    proj.branch = "main"
    db.commit()
    db.close()
    started = []
    monkeypatch.setattr(runner, "start", lambda **kw: started.append(kw) or 4242)
    return p, started


def test_webhook_github_signature(client, hook_project):
    p, started = hook_project
    body = json.dumps({"ref": "refs/heads/main"}).encode()
    sig = "sha256=" + hmac.new(p["webhook_secret"].encode(), body, hashlib.sha256).hexdigest()
    url = f"/api/webhooks/{p['slug']}"
    assert client.post(url, content=body, headers={"X-Hub-Signature-256": "sha256=bad"}).status_code == 403
    r = client.post(url, content=body, headers={"X-Hub-Signature-256": sig})
    assert r.status_code == 200 and started


def test_webhook_gitlab_token_and_branch_filter(client, hook_project):
    p, started = hook_project
    url = f"/api/webhooks/{p['slug']}"
    assert client.post(url, json={"ref": "refs/heads/main"}, headers={"X-Gitlab-Token": "wrong"}).status_code == 403
    r = client.post(url, json={"ref": "refs/heads/feature"}, headers={"X-Gitlab-Token": p["webhook_secret"]})
    assert r.json()["skipped"] and not started
    r = client.post(url, json={"ref": "refs/heads/main"}, headers={"X-Gitlab-Token": p["webhook_secret"]})
    assert r.status_code == 200 and started


def test_webhook_disabled_or_unknown(client, auth):
    assert client.post("/api/webhooks/no-such-project", json={}).status_code == 404
    p = client.post("/api/projects", json={"name": "Hook off", "source": "empty"}, headers=auth).json()
    assert client.post(f"/api/webhooks/{p['slug']}?token=whatever", json={}).status_code == 404
