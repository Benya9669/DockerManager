"""Templates, log/job downloads, backups."""
import tarfile
import time
from pathlib import Path

from app.config import settings
from app.jobs import runner
from tests.test_core import PY, wait_job


def test_templates_create_project(client, auth):
    ts = client.get("/api/projects/templates", headers=auth).json()
    assert {"nginx-static", "postgres-redis", "node-app"} <= {t["id"] for t in ts}
    p = client.post("/api/projects", json={"name": f"Tpl {time.time_ns()}", "source": "template",
                                           "template": "postgres-redis"}, headers=auth).json()
    assert p["env_file"] == ".env"
    env = (Path(p["path"]) / ".env").read_text()
    assert "{{secret" not in env and "POSTGRES_PASSWORD=" in env
    assert len(env.split("POSTGRES_PASSWORD=")[1].split("\n")[0]) >= 20
    assert client.post("/api/projects", json={"name": "bad tpl", "source": "template", "template": "nope"},
                       headers=auth).status_code == 400


def test_job_output_download_with_grep(client, auth):
    jid = runner.start(action="t.dl", steps=[("x", [PY, "-c", "print('alpha'); print('ERROR beta'); print('gamma')"])])
    wait_job(jid)
    r = client.get(f"/api/jobs/{jid}/output", headers=auth)
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    assert "alpha" in r.text and "\x1b[" not in r.text
    r = client.get(f"/api/jobs/{jid}/output?grep=error", headers=auth)
    assert "ERROR beta" in r.text and "alpha" not in r.text


def test_panel_and_files_backup_restore(client, auth):
    r = client.post("/api/backups/panel", headers=auth)
    assert wait_job(r.json()["job_id"]).status == "success"
    items = client.get("/api/backups", headers=auth).json()["items"]
    panel = next(b for b in items if b["kind"] == "panel")
    with tarfile.open(settings.backup_dir / panel["filename"]) as tar:
        assert {"dm.db", "secret.key"} <= set(tar.getnames())
    dl = client.get(f"/api/backups/{panel['id']}/download", headers=auth)
    assert dl.status_code == 200 and dl.content[:2] == b"\x1f\x8b"

    p = client.post("/api/projects", json={"name": f"Bk {time.time_ns()}", "source": "empty"}, headers=auth).json()
    cf = Path(p["path"]) / "docker-compose.yml"
    original = cf.read_text()
    from app import backups
    from app.db import SessionLocal
    from app.models import Project
    db = SessionLocal()
    proj = db.get(Project, p["id"])
    db.close()
    jid = runner.start(action="t.bk", steps=[("", lambda ctx: backups.backup_project_files(ctx, proj, "t"))])
    assert wait_job(jid).status == "success"
    files_b = next(b for b in client.get(f"/api/backups?project_id={p['id']}", headers=auth).json()["items"])
    cf.write_text("changed")
    r = client.post(f"/api/backups/{files_b['id']}/restore", headers=auth)
    assert wait_job(r.json()["job_id"]).status == "success"
    assert cf.read_text() == original
    assert client.post(f"/api/backups/{panel['id']}/restore", headers=auth).status_code == 400
    assert client.delete(f"/api/backups/{panel['id']}", headers=auth).status_code == 200
    assert not (settings.backup_dir / panel["filename"]).exists()


def test_metrics_sampler_and_api(client, auth, monkeypatch):
    from app import metrics

    calls = {"n": 0}

    class FakeAPI:
        def containers(self, filters=None, all=False):
            return [{"Id": "abc123456789xyz", "Names": ["/shop-web-1"], "Labels": {"com.docker.compose.project": "shop-m"}}]

        def stats(self, cid, stream=False, one_shot=True):
            calls["n"] += 1
            n = calls["n"]
            return {"cpu_stats": {"cpu_usage": {"total_usage": 1000 * n}, "system_cpu_usage": 10000 * n, "online_cpus": 2},
                    "memory_stats": {"usage": 5000, "limit": 100000, "stats": {"inactive_file": 1000}},
                    "networks": {"eth0": {"rx_bytes": 100 * n, "tx_bytes": 50 * n}}}

    monkeypatch.setattr(metrics, "api", lambda *a, **k: FakeAPI())
    metrics.sample_once()
    metrics.sample_once()
    series = metrics.container_series(1, project="shop-m")
    assert series and series[0]["name"] == "shop-web-1"
    last = series[0]["points"][-1]
    assert last[1] == 20.0 and last[2] == 4000  # cpu% from deltas: 1000/10000*2*100; mem minus inactive_file
    assert client.get("/api/metrics/host?hours=1", headers=auth).status_code == 200
    assert client.get("/api/metrics/containers/abc123456789?hours=1", headers=auth).json()["series"]
