"""Self-update of the panel.

The panel cannot recreate its own container from inside (it would be killed mid-way),
so it starts a short-lived *updater* container from its own image which runs, in the
panel's compose directory on the host:
  git mode:   git pull --ff-only && docker compose up -d --build
  image mode: docker compose pull && docker compose up -d
"""
import json
import logging
import shlex
import socket
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from docker.errors import NotFound

from .config import settings
from .dockerc import api
from .jobs import runner
from .version import GIT_SHA, VERSION, is_newer

log = logging.getLogger("dockermanager.updater")

_last_check: dict = {}


def latest_release() -> dict | None:
    url = f"https://api.github.com/repos/{settings.update_repo}/releases/latest"
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json", "User-Agent": "dockermanager-updater",
    })
    if settings.update_token:
        req.add_header("Authorization", f"Bearer {settings.update_token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            d = json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None  # no releases yet (or private repo without token)
        raise
    return {
        "version": str(d.get("tag_name", "")).lstrip("v"), "tag": d.get("tag_name"),
        "url": d.get("html_url"), "notes": d.get("body") or "", "published_at": d.get("published_at"),
    }


def check() -> dict:
    res: dict = {"checked_at": datetime.now(timezone.utc).isoformat()}
    try:
        rel = latest_release()
        res["latest"] = rel
        res["update_available"] = bool(rel and is_newer(rel["version"]))
    except Exception as e:  # noqa: BLE001
        res["error"] = str(e)
        res["update_available"] = False
    _last_check.clear()
    _last_check.update(res)
    return res


def context() -> dict:
    """Where/how the panel itself is running."""
    try:
        c = api().inspect_container(socket.gethostname())
    except Exception:  # noqa: BLE001
        return {"can_update": False, "reason": "Панель запущена не в Docker-контейнере — самообновление недоступно"}
    labels = c.get("Config", {}).get("Labels") or {}
    project = labels.get("com.docker.compose.project")
    workdir = labels.get("com.docker.compose.project.working_dir")
    files = [f for f in (labels.get("com.docker.compose.project.config_files") or "").split(",") if f]
    if not project or not workdir:
        return {"can_update": False, "reason": "Контейнер панели запущен не через docker compose"}
    mounts = c.get("Mounts") or []
    ssh_src = next((m.get("Source") for m in mounts if m.get("Destination") == "/ssh-src"), None)
    data_m = next((m for m in mounts if m.get("Destination") == settings.data_dir.as_posix()), None)
    data_src = (data_m.get("Name") if data_m.get("Type") == "volume" else data_m.get("Source")) if data_m else None
    return {
        "data_src": data_src,
        "can_update": True, "reason": None, "project": project, "working_dir": workdir,
        "config_files": files, "image": c.get("Image"), "ssh_src": ssh_src,
        "updater_name": f"{project}-updater",
    }


def updater_argv(ctx: dict) -> list[str]:
    q = shlex.quote
    compose = f"docker compose -p {q(ctx['project'])} " + " ".join(f"-f {q(f)}" for f in ctx["config_files"])
    if settings.update_mode == "image":
        script = f"{compose} pull && {compose} up -d"
    else:
        script = f"git pull --ff-only && {compose} up -d --build"
    # registry logins: copy into a writable docker config dir (buildx keeps state there)
    prep = "mkdir -p /root/.docker && (cp /dm-data/docker-config/config.json /root/.docker/ 2>/dev/null || true)"
    script = f"{prep} && echo '[updater] {settings.update_mode} mode, {VERSION} -> latest' && {script} && echo '[updater] done'"

    ssh = "ssh -o StrictHostKeyChecking=accept-new -o BatchMode=yes"
    if settings.update_ssh_key:
        ssh += f" -i /root/.ssh/{settings.update_ssh_key} -o IdentitiesOnly=yes"
    wd = ctx["working_dir"]
    argv = [
        "docker", "run", "-d", "--name", ctx["updater_name"], "--label", "dockermanager.updater=1",
        "-v", "/var/run/docker.sock:/var/run/docker.sock", "-v", f"{wd}:{wd}", "-w", wd,
        "-e", f"GIT_SSH_COMMAND={ssh}",
    ]
    if ctx.get("ssh_src"):
        argv += ["-v", f"{ctx['ssh_src']}:/ssh-src:ro"]
    if ctx.get("data_src"):
        # registry logins managed in the panel (private GHCR etc.)
        argv += ["-v", f"{ctx['data_src']}:/dm-data:ro"]
    argv += [ctx["image"], "sh", "-c", script]
    return argv


def start_update(username: str) -> int:
    ctx = context()
    if not ctx["can_update"]:
        raise RuntimeError(ctx["reason"])
    try:
        api().remove_container(ctx["updater_name"], force=True)
    except NotFound:
        pass
    return runner.start(
        action="panel.update",
        steps=[(f"start updater container {ctx['updater_name']} (panel will restart)", updater_argv(ctx))],
        username=username,
    )


def status() -> dict:
    return {
        "current": VERSION, "git_sha": GIT_SHA, "mode": settings.update_mode, "repo": settings.update_repo,
        "auto_update": settings.auto_update, "check_hours": settings.update_check_hours,
        **context(), "last_check": dict(_last_check),
    }


def auto_update_loop() -> None:
    time.sleep(60)  # let the app settle after start
    while True:
        res = check()
        if settings.auto_update and res.get("update_available"):
            try:
                log.warning("Auto-update to %s", res["latest"]["version"])
                start_update("auto-update")
            except Exception as e:  # noqa: BLE001
                log.error("auto-update failed: %s", e)
        time.sleep(max(settings.update_check_hours, 0.25) * 3600)


def start_background() -> None:
    threading.Thread(target=auto_update_loop, daemon=True).start()
