import asyncio

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import SessionLocal, get_db
from ..deps import audit, require, ws_user
from ..jobs import runner
from ..models import Job, Project, User
from ..textfiles import text_download

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def job_out(j: Job, project: Project | None = None, with_output: bool = False) -> dict:
    d = {
        "id": j.id, "project_id": j.project_id, "project_name": project.name if project else None,
        "action": j.action, "status": j.status, "username": j.username,
        "started_at": j.started_at, "finished_at": j.finished_at,
    }
    if with_output:
        d["output"] = j.output
    return d


@router.get("")
def list_jobs(
    project_id: int | None = None, limit: int = 100,
    _: User = Depends(require("viewer")), db: Session = Depends(get_db),
):
    q = select(Job, Project).outerjoin(Project, Project.id == Job.project_id).order_by(Job.id.desc()).limit(min(limit, 500))
    if project_id is not None:
        q = q.where(Job.project_id == project_id)
    return [job_out(j, p) for j, p in db.execute(q).all()]


@router.get("/{job_id}")
def get_job(job_id: int, _: User = Depends(require("viewer")), db: Session = Depends(get_db)):
    j = db.get(Job, job_id)
    if not j:
        raise HTTPException(404, "Job not found")
    return job_out(j, db.get(Project, j.project_id) if j.project_id else None)


@router.get("/{job_id}/output")
def job_output(job_id: int, grep: str | None = None, _: User = Depends(require("viewer")), db: Session = Depends(get_db)):
    j = db.get(Job, job_id)
    if not j:
        raise HTTPException(404, "Job not found")
    live = runner.live.get(job_id)
    text = "".join(live.chunks) if live else (j.output or "")
    return text_download(text, f"job-{job_id}-{j.action}", grep)


@router.post("/{job_id}/cancel")
def cancel_job(job_id: int, user: User = Depends(require("operator")), db: Session = Depends(get_db)):
    if not runner.cancel(job_id):
        raise HTTPException(400, "Job is not running")
    audit(db, user, "job.cancel", str(job_id))
    return {"ok": True}


@router.websocket("/{job_id}/stream")
async def stream_job(ws: WebSocket, job_id: int):
    db = SessionLocal()
    try:
        user = ws_user(ws, db)
        if not user:
            await ws.close(code=4401)
            return
        await ws.accept()
        live, q, snapshot = runner.subscribe(job_id)
        if live is None:
            j = db.get(Job, job_id)
            if not j:
                await ws.send_json({"type": "error", "data": "Job not found"})
            else:
                await ws.send_json({"type": "line", "data": j.output})
                await ws.send_json({"type": "done", "data": j.status})
            await ws.close()
            return
    finally:
        db.close()
    try:
        if snapshot:
            await ws.send_json({"type": "line", "data": "".join(snapshot)})
        while True:
            kind, data = await q.get()
            await ws.send_json({"type": kind, "data": data})
            if kind == "done":
                break
        await ws.close()
    except (WebSocketDisconnect, RuntimeError, asyncio.CancelledError):
        pass
    finally:
        runner.unsubscribe(live, q)
