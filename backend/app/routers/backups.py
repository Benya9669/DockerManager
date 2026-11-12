from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import backups
from ..config import settings
from ..db import get_db
from ..deps import audit, get_project, require
from ..jobs import BusyError, runner
from ..models import Backup, Project, User

router = APIRouter(prefix="/api/backups", tags=["backups"])


def out(b: Backup) -> dict:
    return {"id": b.id, "kind": b.kind, "target": b.target, "project_id": b.project_id, "filename": b.filename,
            "size": b.size, "status": b.status, "username": b.username, "created_at": b.created_at}


class ProjectBackupIn(BaseModel):
    stop: bool = False


class VolumeIn(BaseModel):
    volume: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9][\w.-]*$")


def _start(action: str, steps, user: User, project_id: int | None = None) -> dict:
    try:
        return {"job_id": runner.start(action=action, steps=steps, username=user.username, project_id=project_id)}
    except BusyError as e:
        raise HTTPException(409, str(e))


@router.get("")
def list_backups(project_id: int | None = None, _: User = Depends(require("admin")), db: Session = Depends(get_db)):
    q = select(Backup).order_by(Backup.id.desc()).limit(500)
    if project_id is not None:
        q = q.where(Backup.project_id == project_id)
    return {
        "items": [out(b) for b in db.scalars(q)],
        "settings": {"dir": str(settings.backup_dir), "keep": settings.backup_keep,
                     "interval_hours": settings.backup_interval_hours, "stop_containers": settings.backup_stop_containers},
    }


@router.post("/panel")
def backup_panel(user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    audit(db, user, "backup.panel")
    return _start("backup.panel", [("Бэкап панели", lambda ctx: backups.backup_panel(ctx, user.username))], user)


@router.post("/all")
def backup_all(user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    audit(db, user, "backup.all")
    return _start("backup.all", backups.scheduled_backup(user.username), user)


@router.post("/project/{project_id}")
def backup_project(project_id: int, data: ProjectBackupIn, user: User = Depends(require("admin")),
                   db: Session = Depends(get_db)):
    p = get_project(db, project_id)
    audit(db, user, "backup.project", p.slug, f"stop={data.stop}")
    return _start(f"backup:{p.slug}", [(f"Бэкап проекта {p.name}",
                                        lambda ctx: backups.backup_project(ctx, p, user.username, data.stop))],
                  user, p.id)


@router.post("/volume")
def backup_volume(data: VolumeIn, user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    audit(db, user, "backup.volume", data.volume)
    return _start(f"backup:volume:{data.volume}",
                  [("", lambda ctx: backups.backup_volume(ctx, data.volume, user.username))], user)


@router.get("/{backup_id}/download")
def download(backup_id: int, user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    b = db.get(Backup, backup_id)
    f = settings.backup_dir / b.filename if b else None
    if not b or not f.is_file():
        raise HTTPException(404, "Backup file not found")
    audit(db, user, "backup.download", b.filename)
    return FileResponse(f, filename=b.filename, media_type="application/gzip")


@router.post("/{backup_id}/restore")
def restore(backup_id: int, user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    b = db.get(Backup, backup_id)
    if not b or b.status != "success" or not (settings.backup_dir / b.filename).is_file():
        raise HTTPException(404, "Backup not found")
    p = db.get(Project, b.project_id) if b.project_id else None
    if b.kind == "volume":
        steps = [(f"Восстановление тома {b.target}", lambda ctx: backups.restore_volume(ctx, b, p))]
    elif b.kind == "files" and p:
        steps = [(f"Восстановление файлов {p.name}", lambda ctx: backups.restore_files(ctx, b, p))]
    else:
        raise HTTPException(400, "Бэкап панели восстанавливается вручную (см. README)")
    audit(db, user, "backup.restore", b.filename)
    return _start(f"restore:{b.filename}", steps, user, p.id if p else None)


@router.delete("/{backup_id}")
def delete(backup_id: int, user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    b = db.get(Backup, backup_id)
    if not b:
        raise HTTPException(404, "Not found")
    (settings.backup_dir / b.filename).unlink(missing_ok=True)
    db.delete(b)
    db.commit()
    audit(db, user, "backup.delete", b.filename)
    return {"ok": True}
