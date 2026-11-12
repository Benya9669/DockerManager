import hashlib
import hmac
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import compose
from ..db import get_db
from ..deps import audit
from ..jobs import BusyError, runner
from ..models import Project

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


def _verify(p: Project, request: Request, body: bytes) -> bool:
    secret = p.webhook_secret.encode()
    # GitLab
    if (t := request.headers.get("X-Gitlab-Token")) is not None:
        return hmac.compare_digest(t.encode(), secret)
    # GitHub / Gitea (HMAC SHA256)
    sig = request.headers.get("X-Hub-Signature-256") or request.headers.get("X-Gitea-Signature")
    if sig:
        expected = hmac.new(secret, body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig.removeprefix("sha256="), expected)
    # Generic: ?token=... or X-Webhook-Token
    t = request.headers.get("X-Webhook-Token") or request.query_params.get("token")
    return bool(t) and hmac.compare_digest(t.encode(), secret)


@router.post("/{slug}")
async def webhook(slug: str, request: Request, db: Session = Depends(get_db)):
    p = db.scalar(select(Project).where(Project.slug == slug))
    if not p or not p.webhook_enabled or not p.webhook_secret:
        raise HTTPException(404, "Not found")
    body = await request.body()
    if not _verify(p, request, body):
        raise HTTPException(403, "Invalid signature")
    try:
        payload = json.loads(body or b"{}")
    except ValueError:
        payload = {}
    ref = payload.get("ref") if isinstance(payload, dict) else None
    if ref and p.branch and ref != f"refs/heads/{p.branch}":
        return {"skipped": True, "reason": f"ref {ref} does not match branch {p.branch}"}
    try:
        jid = runner.start(action="webhook.deploy", steps=compose.action_steps(p, "deploy"), cwd=p.path,
                           project_id=p.id, username="webhook")
    except BusyError as e:
        raise HTTPException(409, str(e))
    audit(db, "webhook", "webhook.deploy", p.slug, ref or "")
    return {"job_id": jid}
