import asyncio
import logging
import os
import secrets
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, select, text

from .config import settings
from .db import Base, SessionLocal, engine
from .jobs import runner
from .models import Job, User
from . import registries, updater
from .authsec import client_ip
from .routers import auth, docker_res, jobs, projects, system, webhooks
from .routers import backups as backups_router
from .routers import metrics as metrics_router
from .routers import servers as servers_router
from .routers import registries as registries_router
from .version import VERSION
from .security import hash_password

log = logging.getLogger("dockermanager")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def migrate() -> None:
    """Minimal auto-migration: add columns that exist in models but not in the DB."""
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing:
                    continue
                coltype = col.type.compile(dialect=engine.dialect)
                default = col.default.arg if col.default is not None and not callable(col.default.arg) else None
                ddl = f'ALTER TABLE {table.name} ADD COLUMN {col.name} {coltype}'
                if isinstance(default, bool):
                    ddl += f" NOT NULL DEFAULT {'TRUE' if default else 'FALSE'}"
                elif isinstance(default, (int, float)):
                    ddl += f" NOT NULL DEFAULT {default}"
                elif isinstance(default, str):
                    ddl += " NOT NULL DEFAULT '" + default.replace("'", "''") + "'"
                conn.execute(text(ddl))
                log.info("migrated: %s", ddl)


def init_db() -> None:
    Base.metadata.create_all(engine)
    migrate()
    db = SessionLocal()
    try:
        # jobs left "running" from a previous process can never finish
        for j in db.scalars(select(Job).where(Job.status == "running")):
            j.status = "failed"
            j.output = (j.output or "") + "\n[interrupted: server restarted]\n"
        if not db.scalar(select(User).limit(1)):
            pwd = settings.admin_password or secrets.token_urlsafe(12)
            db.add(User(username=settings.admin_username, password_hash=hash_password(pwd), role="admin"))
            if not settings.admin_password:
                (settings.data_dir / "initial_admin_password.txt").write_text(pwd)
                log.warning("Created admin user '%s' with password: %s (also saved to %s)",
                            settings.admin_username, pwd, settings.data_dir / "initial_admin_password.txt")
        db.commit()
    finally:
        db.close()


def auto_prune_loop(hours: float, older_than: int) -> None:
    from .routers.docker_res import PruneIn, prune_steps

    while True:
        time.sleep(hours * 3600)
        try:
            runner.start(action="docker.prune:auto", steps=prune_steps(PruneIn(older_than_hours=older_than)), username="scheduler")
        except Exception as e:  # noqa: BLE001
            log.error("auto prune failed: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    runner.loop = asyncio.get_running_loop()
    init_db()
    registries.activate()
    from . import servers as servers_mod
    servers_mod.write_ssh_config()
    updater.start_background()
    if not os.getenv("DM_TESTING"):
        from . import alerts, metrics
        alerts.start_background()
        metrics.start_background()
    log.info("Docker Manager %s started", VERSION)
    hours = settings.auto_prune_hours
    if hours > 0:
        older = settings.auto_prune_older_than
        threading.Thread(target=auto_prune_loop, args=(hours, older), daemon=True).start()
        log.info("Auto prune every %sh (older than %sh)", hours, older)
    if settings.backup_interval_hours > 0:
        def backup_loop():
            from . import backups
            while True:
                time.sleep(settings.backup_interval_hours * 3600)
                try:
                    runner.start(action="backup.scheduled", steps=backups.scheduled_backup(), username="scheduler")
                except Exception as e:  # noqa: BLE001
                    log.error("scheduled backup failed: %s", e)
        threading.Thread(target=backup_loop, daemon=True).start()
        log.info("Scheduled backups every %sh, keep %s", settings.backup_interval_hours, settings.backup_keep)
    yield


SECURITY_HEADERS = [
    (b"content-security-policy",
     b"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
     b"font-src 'self' data:; connect-src 'self' ws: wss:; object-src 'none'; base-uri 'self'; "
     b"frame-ancestors 'none'; form-action 'self'"),
    (b"x-frame-options", b"DENY"),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
]


class SecurityMiddleware:
    """Pure ASGI: remembers client IP for the audit log and adds security headers."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        client = scope.get("client")
        client_ip.set(client[0] if client else "")
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        is_https = scope.get("scheme") == "https"

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers += SECURITY_HEADERS
                if is_https:
                    headers.append((b"strict-transport-security", b"max-age=31536000"))
                if scope["path"].startswith("/api/"):
                    headers.append((b"cache-control", b"no-store"))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)


app = FastAPI(title="Docker Manager", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(SecurityMiddleware)
for r in (auth.router, projects.router, jobs.router, docker_res.router, webhooks.router,
          system.router, registries_router.router, backups_router.router, metrics_router.router, servers_router.router):
    app.include_router(r)


@app.get("/api/health")
def health():
    return {"ok": True}


if settings.static_dir.exists():
    app.mount("/assets", StaticFiles(directory=settings.static_dir / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        f = (settings.static_dir / full_path).resolve()
        if full_path and f.is_file() and f.is_relative_to(settings.static_dir):
            return FileResponse(f)
        return FileResponse(settings.static_dir / "index.html")
