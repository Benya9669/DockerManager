from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import updater
from ..db import get_db
from ..deps import audit, require
from ..models import User
from ..version import GIT_SHA, VERSION

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/version")
def version():
    return {"version": VERSION, "git_sha": GIT_SHA}


@router.get("/system/update")
def update_status(refresh: bool = False, _: User = Depends(require("admin"))):
    if refresh or not updater._last_check:
        updater.check()
    return updater.status()


class UpdateIn(BaseModel):
    force: bool = False


@router.post("/system/update")
def run_update(data: UpdateIn, user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    res = updater.check()
    if not data.force and not res.get("update_available"):
        raise HTTPException(400, "Обновлений нет (используйте принудительное обновление)")
    try:
        jid = updater.start_update(user.username)
    except RuntimeError as e:
        raise HTTPException(400, str(e))
    audit(db, user, "panel.update", (res.get("latest") or {}).get("version", ""), f"force={data.force}")
    return {"job_id": jid}
