"""Backups of the panel itself, project files and docker volumes.

Volumes are archived by a short-lived helper container on the volume's docker host (local or a
remote server) that mounts the volume read-only and streams a .tar.gz to stdout; the panel writes
it into the backup dir. Restore streams the archive back through stdin.
"""
import os
import sqlite3
import subprocess
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from . import compose, servers
from .config import settings
from .db import SessionLocal
from .dockerc import api
from .jobs import JobContext
from .models import Backup, Project
from .registries import DOCKER_CONFIG_DIR

HELPER_IMAGE = os.getenv("DM_BACKUP_HELPER_IMAGE", "alpine:3")


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _record(**kw) -> int:
    db = SessionLocal()
    b = Backup(**kw)
    db.add(b)
    db.commit()
    bid = b.id
    db.close()
    return bid


def _finish(bid: int, ok: bool) -> None:
    db = SessionLocal()
    b = db.get(Backup, bid)
    if b:
        f = settings.backup_dir / b.filename
        b.status = "success" if ok and f.exists() else "failed"
        b.size = f.stat().st_size if f.exists() else 0
        db.commit()
    db.close()


def prune_old(kind: str, target: str) -> None:
    db = SessionLocal()
    rows = db.scalars(select(Backup).where(Backup.kind == kind, Backup.target == target, Backup.status == "success")
                      .order_by(Backup.id.desc())).all()
    for b in rows[settings.backup_keep:]:
        (settings.backup_dir / b.filename).unlink(missing_ok=True)
        db.delete(b)
    db.commit()
    db.close()


# ---------- panel ----------
def backup_panel(ctx: JobContext, username: str) -> bool:
    name = f"panel-{_stamp()}.tar.gz"
    bid = _record(kind="panel", target="panel", filename=name, username=username)
    with tempfile.TemporaryDirectory() as tmp:
        files: list[tuple[Path, str]] = []
        if settings.database_url.startswith("sqlite"):
            db_path = Path(settings.database_url.removeprefix("sqlite:///"))
            copy = Path(tmp) / "dm.db"
            src, dst = sqlite3.connect(db_path), sqlite3.connect(copy)
            with dst:
                src.backup(dst)  # consistent online copy
            src.close()
            dst.close()
            files.append((copy, "dm.db"))
        else:
            ctx.info("БД не SQLite — сделайте её дамп средствами СУБД (pg_dump); в архив попадут ключи и конфиг")
        for f, arc in ((settings.data_dir / "secret.key", "secret.key"),
                       (DOCKER_CONFIG_DIR / "config.json", "docker-config/config.json")):
            if f.exists():
                files.append((f, arc))
        with tarfile.open(settings.backup_dir / name, "w:gz") as tar:
            for f, arc in files:
                tar.add(f, arcname=arc)
                ctx.info(f"  + {arc}")
    _finish(bid, True)
    prune_old("panel", "panel")
    ctx.ok(f"Бэкап панели: {name}")
    return True


# ---------- project ----------
def project_volumes(p: Project) -> list[str]:
    vols = api(p.server_id).volumes(filters={"label": f"com.docker.compose.project={p.slug}"}).get("Volumes") or []
    return sorted(v["Name"] for v in vols)


def backup_project_files(ctx: JobContext, p: Project, username: str) -> bool:
    root = Path(p.path)
    if not root.is_dir():
        ctx.error("Папка проекта недоступна")
        return False
    name = f"files-{p.slug}-{_stamp()}.tar.gz"
    bid = _record(kind="files", target=p.slug, project_id=p.id, filename=name, username=username)
    skip = {".git", "node_modules", "__pycache__", ".venv"}
    with tarfile.open(settings.backup_dir / name, "w:gz") as tar:
        tar.add(root, arcname=".", filter=lambda ti: None if set(Path(ti.name).parts) & skip else ti)
    _finish(bid, True)
    prune_old("files", p.slug)
    ctx.ok(f"Файлы проекта: {name}")
    return True


def _denv(server_id: int | None) -> dict[str, str]:
    return {**os.environ, **servers.env_for(server_id)}


def backup_volume(ctx: JobContext, volume: str, username: str, project_id: int | None = None,
                  server_id: int | None = None) -> bool:
    """tar the volume inside a helper container on the volume's docker host, stream it here via stdout."""
    name = f"volume-{volume}-{_stamp()}.tar.gz"
    bid = _record(kind="volume", target=volume, project_id=project_id, server_id=server_id, filename=name,
                  username=username)
    ctx.emit(f"\x1b[36m$ архивация тома {volume}\x1b[0m\n")
    out = settings.backup_dir / name
    with open(out, "wb") as fh:
        proc = subprocess.Popen(["docker", "run", "--rm", "-v", f"{volume}:/v:ro", HELPER_IMAGE,
                                 "tar", "czf", "-", "-C", "/v", "."],
                                stdout=fh, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, env=_denv(server_id))
        ctx.live.proc = proc
        _, err = proc.communicate()
    ok = proc.returncode == 0
    if not ok:
        ctx.error(err.decode("utf-8", errors="replace").strip() or f"exit {proc.returncode}")
        out.unlink(missing_ok=True)
    _finish(bid, ok)
    if ok:
        prune_old("volume", volume)
        ctx.ok(f"Том {volume}: {name} ({out.stat().st_size // 1024} КБ)")
    return ok


def backup_project(ctx: JobContext, p: Project, username: str, stop: bool) -> bool:
    ok = backup_project_files(ctx, p, username)
    vols = project_volumes(p)
    if not vols:
        ctx.info("Именованных томов у проекта нет")
        return ok
    stopped = False
    denv = servers.docker_env(p)
    if stop:
        stopped = ctx.run([*compose.base(p), "stop"], cwd=p.path, env=denv,
                          label="остановка контейнеров на время бэкапа") == 0
    try:
        for v in vols:
            ok = backup_volume(ctx, v, username, p.id, p.server_id) and ok
    finally:
        if stopped:
            ctx.run([*compose.base(p), "start"], cwd=p.path, env=denv, label="запуск контейнеров")
    return ok


def restore_volume(ctx: JobContext, b: Backup, p: Project | None) -> bool:
    stopped = False
    denv = servers.docker_env(p) if p else {}
    if p:
        stopped = ctx.run([*compose.base(p), "stop"], cwd=p.path, env=denv, label="остановка контейнеров проекта") == 0
    try:
        ctx.emit(f"\x1b[36m$ восстановление тома {b.target} из {b.filename}\x1b[0m\n")
        with open(settings.backup_dir / b.filename, "rb") as fh:
            proc = subprocess.Popen(["docker", "run", "--rm", "-i", "-v", f"{b.target}:/v", HELPER_IMAGE,
                                     "sh", "-c", "find /v -mindepth 1 -delete && tar xzf - -C /v"],
                                    stdin=fh, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    env=_denv(b.server_id))
            ctx.live.proc = proc
            out, _ = proc.communicate()
        if out:
            ctx.emit(out.decode("utf-8", errors="replace"))
        rc = proc.returncode
    finally:
        if stopped:
            ctx.run([*compose.base(p), "start"], cwd=p.path, env=denv, label="запуск контейнеров")
    if rc == 0:
        ctx.ok("Том восстановлен")
    else:
        ctx.error(f"exit {rc}")
    return rc == 0


def restore_files(ctx: JobContext, b: Backup, p: Project) -> bool:
    root = Path(p.path).resolve()
    with tarfile.open(settings.backup_dir / b.filename, "r:gz") as tar:
        tar.extractall(root, filter="data")  # "data" filter blocks absolute paths / traversal / devices
    ctx.ok(f"Файлы проекта восстановлены в {root} (существующие перезаписаны, лишние не удалялись)")
    return True


def scheduled_backup(username: str = "scheduler"):
    """Steps for a full backup: panel + every project (files and volumes)."""
    def step_all(ctx: JobContext):
        ok = backup_panel(ctx, username)
        db = SessionLocal()
        projects = db.scalars(select(Project)).all()
        db.close()
        for p in projects:
            ctx.emit(f"\n\x1b[36m» Проект {p.name}\x1b[0m\n")
            try:
                ok = backup_project(ctx, p, username, settings.backup_stop_containers) and ok
            except Exception as e:  # noqa: BLE001
                ctx.error(f"  {e}")
                ok = False
        return ok
    return [("Полный бэкап", step_all)]
