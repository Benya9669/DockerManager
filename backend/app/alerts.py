"""Health alerts for opted-in projects; state survives a panel restart."""
import json
import logging
import os
import threading
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from sqlalchemy import select

from .config import settings
from .db import SessionLocal
from .dockerc import list_containers
from .models import Project


def destination():
    webhook = os.getenv("DM_ALERT_WEBHOOK", "")
    if webhook.startswith("https://"):
        return webhook, None
    token, chat = os.getenv("DM_TELEGRAM_TOKEN"), os.getenv("DM_TELEGRAM_CHAT_ID")
    if token and chat:
        return f"https://api.telegram.org/bot{token}/sendMessage", chat
    return None, None


def notify(project, service, recovered, started, now):
    url, chat = destination()
    link = f"{settings.public_url}/projects/{project.id}?" + urlencode({"tab": "logs", "service": service})
    event = "recovered" if recovered else "unhealthy"
    text = f"{project.name} / {service}: {event} · {(now-started)//60} min\n{link}"
    payload = {"chat_id": chat, "text": text} if chat else {
        "event": event, "project": project.slug, "service": service, "duration_seconds": now-started, "url": link}
    request = Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=8) as response:
        if not 200 <= response.status < 300:
            raise ValueError("Alert delivery failed")


def sample():
    with SessionLocal() as db:
        projects = list(db.scalars(select(Project).where(Project.alerts_enabled.is_(True))))
        for project in projects:
            try:
                containers = list_containers(project.slug, project.server_id)
            except Exception:
                # A host outage breaks the sequence of samples for an unconfirmed incident.
                state = json.loads(project.alert_state or "{}")
                project.alert_state = json.dumps({key: value for key, value in state.items() if value["sent"]})
                db.commit()
                continue
            services = {}
            for c in containers:
                name = c["service"] or c["name"]
                status = c.get("status") or ""
                healthy = c["state"] == "running" and "unhealthy" not in status and "starting" not in status
                bad = "unhealthy" in status or c["state"] == "restarting"
                states = services.setdefault(name, [])
                states.append("bad" if bad else "ok" if healthy else "waiting")
            now = int(time.time())
            state = json.loads(project.alert_state or "{}")
            for name in set(state) | services.keys():
                item = state.get(name, {"start": now, "count": 0, "sent": False})
                samples = services.get(name, [])
                bad = "bad" in samples
                if bad:
                    item["count"] += 1
                elif not item["sent"]:
                    state.pop(name, None)
                    continue
                recovered = bool(samples) and all(s == "ok" for s in samples)
                if (bad and item["count"] >= 3 and not item["sent"]) or (recovered and item["sent"]):
                    try:
                        notify(project, name, recovered, item["start"], now)
                    except Exception:
                        logging.warning("Alert delivery failed for project %s", project.id)
                    else:
                        if recovered:
                            state.pop(name, None)
                            continue
                        item["sent"] = True
                state[name] = item
            project.alert_state = json.dumps(state)
            db.commit()


def start_background():
    if not destination()[0]:
        return
    def loop():
        while True:
            try:
                sample()
            except Exception:
                logging.exception("Health alert check failed")
            time.sleep(30)
    threading.Thread(target=loop, name="health-alerts", daemon=True).start()
