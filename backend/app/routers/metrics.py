from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import metrics
from ..access import level, project_role, role_for_slug
from ..config import settings
from ..db import get_db
from ..deps import get_project, require
from ..models import User

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


@router.get("/host")
def host(hours: float = Query(6, gt=0, le=168), _: User = Depends(require("viewer"))):
    return {"interval": settings.metrics_interval, "points": metrics.host_series(hours)}


@router.get("/projects/{project_id}")
def project(project_id: int, hours: float = Query(6, gt=0, le=168), user: User = Depends(require("viewer")),
            db: Session = Depends(get_db)):
    p = get_project(db, project_id)
    if level(project_role(db, user, p.id)) < level("viewer"):
        raise HTTPException(404, "Project not found")
    return {"interval": settings.metrics_interval, "series": metrics.container_series(hours, project=p.slug, server_id=p.server_id)}


@router.get("/containers/{cid}")
def container(cid: str, hours: float = Query(6, gt=0, le=168), server_id: int | None = None, user: User = Depends(require("viewer")),
              db: Session = Depends(get_db)):
    series = metrics.container_series(hours, container=cid, server_id=server_id)
    if series and level(role_for_slug(db, user, series[0]["project"] or None, server_id)) < level("viewer"):
        raise HTTPException(404, "Not found")
    return {"interval": settings.metrics_interval, "series": series}
