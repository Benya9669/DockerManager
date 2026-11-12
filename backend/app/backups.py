"""Backups of the panel itself, project files and docker volumes.

Volumes are archived by a short-lived helper container (the panel's own image when running in
Docker, otherwise alpine) that mounts the volume read-only and writes a .tar.gz into the backup dir.
When the panel runs in a container, the backup dir lives on one of its mounts; the helper mounts
that same source so the archive lands where the panel can read it.
"""
import socket
import sqlite3
import tarfile
import tempfile
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from . import compose
from .config import settings
from .db import SessionLocal
from .dockerc import api
from .jobs import JobContext
from .models import Backup, Project
from .registries import DOCKER_CONFIG_DIR

HELPER_FALLBACK_IMAGE = "alpine:3"


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


# ---------- where is the backup dir from Docker's point of view ----------
def _helper_mount() -> tuple[str, str, str]:
    """(source for `docker run -v`, path of backup dir inside helper, helper image)."""
    try:
        me = api().inspect_container(socket.gethostname())
    except Exception:  # noqa: BLE001 — not in a container: backup dir is a host path
        return str(settings.backup_dir), "/backups", HELPER_FALLBACK_IMAGE
    bdir = settings.backup_dir.as_posix()
    best = None
    for m in me.get("Mounts") or []:
        dest = m.get("Destination", "")
        if bdir == dest or bdir.startswith(dest.rstrip("/") + "/"):
            if not best or len(dest) > len(best["Destination"]):
                best = m
    if not best:
        raise RuntimeError(f"Папка бэкапов {bdir} не смонтирована в контейнер панели — архивы потеряются при пересоздании")
    src = best.get("Name") if best.get("Type") == "volume" else best.get("Source")
    rel = bdir[len(best["Destination"].rstrip("/")):].lstrip("/")
    return src, "/host/" + rel if rel else "/host", me.get("Image")


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
    vols = api().volumes(filters={"label": f"com.docker.compose.project={p.slug}"}).get("Volumes") or []
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


def backup_volume(ctx: JobContext, volume: str, username: str, project_id: int | None = None) -> bool:
    src, inner, image = _helper_mount()
    name = f"volume-{volume}-{_stamp()}.tar.gz"
    bid = _record(kind="volume", target=volume, project_id=project_id, filename=name, username=username)
    rc = ctx.run(["docker", "run", "--rm", "--entrypoint", "tar", "-v", f"{volume}:/v:ro", "-v", f"{src}:/host",
                  image, "czf", f"{inner}/{name}", "-C", "/v", "."], label=f"архивация тома {volume}")
    _finish(bid, rc == 0)
    if rc == 0:
        prune_old("volume", volume)
        ctx.ok(f"Том {volume}: {name}")
    return rc == 0


def backup_project(ctx: JobContext, p: Project, username: str, stop: bool) -> bool:
    ok = backup_project_files(ctx, p, username)
    vols = project_volumes(p)
    if not vols:
        ctx.info("Именованных томов у проекта нет")
        return ok
    stopped = False
    if stop:
        stopped = ctx.run([*compose.base(p), "stop"], cwd=p.path, label="остановка контейнеров на время бэкапа") == 0
    try:
        for v in vols:
            ok = backup_volume(ctx, v, username, p.id) and ok
    finally:
        if stopped:
            ctx.run([*compose.base(p), "start"], cwd=p.path, label="запуск контейнеров")
    return ok


def restore_volume(ctx: JobContext, b: Backup, p: Project | None) -> bool:
    src, inner, image = _helper_mount()
    stopped = False
    if p:
        stopped = ctx.run([*compose.base(p), "stop"], cwd=p.path, label="остановка контейнеров проекта") == 0
    try:
        script = f"find /v -mindepth 1 -delete && tar xzf {inner}/{b.filename} -C /v"
        rc = ctx.run(["docker", "run", "--rm", "--entrypoint", "sh", "-v", f"{b.target}:/v", "-v", f"{src}:/host:ro",
                      image, "-c", script], label=f"восстановление тома {b.target} из {b.filename}")
    finally:
        if stopped:
            ctx.run([*compose.base(p), "start"], cwd=p.path, label="запуск контейнеров")
    if rc == 0:
        ctx.ok("Том восстановлен")
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
