"""Safe deploy: healthcheck, success snapshot, auto-rollback restoring files."""
import json
import sys
import time
from pathlib import Path

import pytest

from app import deploy
from app.db import SessionLocal
from app.models import Deployment, Project
from app.security import decrypt
from tests.test_core import wait_job

PY = sys.executable


class FakeDocker:
    """Container health depends on the compose file content: 'BROKEN' -> exited(1)."""

    def __init__(self, compose_file: Path):
        self.compose_file = compose_file
        self.tags = []

    def containers(self, all=True, filters=None):
        return [{"Id": "c1", "Image": "app:latest", "ImageID": "sha256:" + "a" * 64}]

    def inspect_container(self, cid):
        broken = "BROKEN" in self.compose_file.read_text()
        state = {"Status": "exited", "ExitCode": 1} if broken else {"Status": "running"}
        return {"Name": "/web-1", "State": state, "RestartCount": 0}

    def inspect_image(self, ref):
        return {"Id": "sha256:" + "a" * 64}

    def tag(self, iid, repo, tag):
        self.tags.append((iid, repo, tag))


@pytest.fixture()
def project(client, auth, monkeypatch):
    p = client.post("/api/projects", json={"name": f"Dep {time.time_ns()}", "source": "empty"}, headers=auth).json()
    cf = Path(p["path"]) / "docker-compose.yml"
    fake = FakeDocker(cf)
    monkeypatch.setattr(deploy, "api", lambda *a, **k: fake)
    monkeypatch.setattr(deploy, "STABLE_FOR", 0)
    monkeypatch.setattr(deploy, "POLL", 0.05)
    # no real docker: "compose up" is a no-op python call
    monkeypatch.setattr(deploy.compose, "base", lambda proj, ansi="never": [PY, "-c", "pass"])
    return p, cf


def _start(pid, steps, on_failure):
    from app.jobs import runner
    db = SessionLocal()
    p = db.get(Project, pid)
    db.close()
    return runner.start(action="deploy", steps=steps, on_failure=on_failure, project_id=pid, cwd=p.path)


def _deployments(pid):
    db = SessionLocal()
    rows = db.query(Deployment).filter(Deployment.project_id == pid).order_by(Deployment.id).all()
    db.close()
    return rows


def test_deploy_success_records_snapshot(project, monkeypatch):
    p, cf = project
    monkeypatch.setattr(deploy.compose, "action_steps",
                        lambda proj, action, service=None, no_cache=False: [("noop", [PY, "-c", "pass"])])
    db = SessionLocal()
    proj = db.get(Project, p["id"])
    db.close()
    steps, on_failure = deploy.deploy_steps(proj, "tester")
    j = wait_job(_start(p["id"], steps, on_failure))
    assert j.status == "success", j.output
    d = _deployments(p["id"])[-1]
    assert d.status == "success"
    after = json.loads(decrypt(d.after_enc))
    assert "docker-compose.yml" in after["files"] and after["images"] == {"app:latest": "sha256:" + "a" * 64}


def test_failed_deploy_auto_rollback_restores_files(project, monkeypatch):
    p, cf = project
    original = cf.read_text()

    def break_it(ctx):
        cf.write_text(original + "# BROKEN\n")  # simulates a bad change coming with the deploy

    monkeypatch.setattr(deploy.compose, "action_steps",
                        lambda proj, action, service=None, no_cache=False: [("bad change", break_it)])
    db = SessionLocal()
    proj = db.get(Project, p["id"])
    db.close()
    steps, on_failure = deploy.deploy_steps(proj, "tester")
    j = wait_job(_start(p["id"], steps, on_failure))
    assert j.status == "failed"
    assert "Автооткат" in j.output
    assert cf.read_text() == original  # file restored
    deployment = _deployments(p["id"])[-1]
    assert deployment.status == "rolled_back"
    assert "web-1" in decrypt(deployment.diagnostics_enc)


def test_no_rollback_when_disabled(project, monkeypatch, client, auth):
    p, cf = project
    client.patch(f"/api/projects/{p['id']}", json={"auto_rollback": False}, headers=auth)
    monkeypatch.setattr(deploy.compose, "action_steps",
                        lambda proj, action, service=None, no_cache=False:
                        [("bad", lambda ctx: cf.write_text("# BROKEN\n"))])
    db = SessionLocal()
    proj = db.get(Project, p["id"])
    db.close()
    steps, on_failure = deploy.deploy_steps(proj, "tester")
    j = wait_job(_start(p["id"], steps, on_failure))
    assert j.status == "failed" and "BROKEN" in cf.read_text()
    assert _deployments(p["id"])[-1].status == "failed"


def test_manual_rollback_endpoint(project, monkeypatch, client, auth):
    p, cf = project
    monkeypatch.setattr(deploy.compose, "action_steps",
                        lambda proj, action, service=None, no_cache=False: [("noop", [PY, "-c", "pass"])])
    db = SessionLocal()
    proj = db.get(Project, p["id"])
    db.close()
    steps, on_failure = deploy.deploy_steps(proj, "tester")
    assert wait_job(_start(p["id"], steps, on_failure)).status == "success"
    good = _deployments(p["id"])[-1]
    original = cf.read_text()
    cf.write_text(original + "# changed later\n")

    hist = client.get(f"/api/projects/{p['id']}/deployments", headers=auth).json()
    assert hist[0]["can_rollback"]
    r = client.post(f"/api/projects/{p['id']}/deployments/{good.id}/rollback", headers=auth)
    assert r.status_code == 200, r.text
    j = wait_job(r.json()["job_id"])
    assert j.status == "success", j.output
    assert cf.read_text() == original
    assert _deployments(p["id"])[-1].kind == "rollback"


def test_rollback_targets_last_successful_deploy_after_local_edit(project, monkeypatch):
    """File edited in the panel *before* a deploy: rollback must return to the last good deploy."""
    p, cf = project
    monkeypatch.setattr(deploy.compose, "action_steps",
                        lambda proj, action, service=None, no_cache=False: [("noop", [PY, "-c", "pass"])])
    db = SessionLocal()
    proj = db.get(Project, p["id"])
    db.close()
    steps, on_failure = deploy.deploy_steps(proj, "tester")
    assert wait_job(_start(p["id"], steps, on_failure)).status == "success"
    good = cf.read_text()

    cf.write_text(good + "# BROKEN edited in panel\n")  # edited before deploying
    steps, on_failure = deploy.deploy_steps(proj, "tester")
    j = wait_job(_start(p["id"], steps, on_failure))
    assert j.status == "failed" and "последнему успешному деплою" in j.output
    assert cf.read_text() == good
    assert _deployments(p["id"])[-1].status == "rolled_back"
