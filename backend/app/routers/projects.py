import re
import secrets
import shutil
from collections import Counter
from pathlib import Path

import asyncio
import codecs
import subprocess
import threading

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import compose, git_ops
from ..config import settings
from ..db import SessionLocal, get_db
from ..deps import ROLE_LEVEL, audit, get_project, require, ws_user
from ..discover import discover_stacks
from ..dockerc import list_containers
from ..jobs import BusyError, runner
from ..models import Project, User
from ..security import encrypt

router = APIRouter(prefix="/api/projects", tags=["projects"])

ENV_PATTERNS = (".env", ".env.*", "*.env", "env/*", "envs/*", ".envs/*")


# ---------- validation (no values that git/docker could parse as options) ----------
SAFE_NAME = re.compile(r"^[\w][\w.@:/+-]*$")
REPO_URL = re.compile(r"^(https?://|ssh://|git@|[\w.-]+@[\w.-]+:)[^\s]+$")


def _no_option(v: str | None, what: str) -> str | None:
    if v is None:
        return v
    v = v.strip()
    if v.startswith("-"):
        raise ValueError(f"{what} must not start with '-'")
    return v


def _repo_url(v: str | None) -> str | None:
    v = _no_option(v, "repo_url")
    if v and not REPO_URL.match(v):
        raise ValueError("repo_url must be https://, ssh:// or git@host:path")
    return v


def _files(v: str | None) -> str | None:
    if v is None:
        return v
    for f in v.split(","):
        _no_option(f, "compose file")
    return v.strip()


# ---------- schemas ----------
class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    slug: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9_-]*$", max_length=64)
    description: str = ""
    source: str = Field(default="git", pattern="^(git|local|empty)$")
    repo_url: str = ""
    branch: str = ""
    git_username: str = ""
    git_token: str = ""
    ssh_key: str = ""
    path: str = ""
    compose_files: str = "docker-compose.yml"
    env_file: str = ""

    @field_validator("repo_url")
    @classmethod
    def _v_repo(cls, v):
        return _repo_url(v)

    @field_validator("branch", "env_file")
    @classmethod
    def _v_opt(cls, v, info):
        return _no_option(v, info.field_name)

    @field_validator("compose_files")
    @classmethod
    def _v_files(cls, v):
        return _files(v)


class ProjectPatch(BaseModel):
    name: str | None = None
    description: str | None = None
    repo_url: str | None = None
    git_username: str | None = None
    git_token: str | None = None  # "" keeps current, use clear_token to remove
    clear_token: bool = False
    ssh_key: str | None = None
    compose_files: str | None = None
    env_file: str | None = None
    webhook_enabled: bool | None = None
    regenerate_webhook: bool = False

    @field_validator("repo_url")
    @classmethod
    def _v_repo(cls, v):
        return _repo_url(v)

    @field_validator("env_file")
    @classmethod
    def _v_opt(cls, v, info):
        return _no_option(v, info.field_name)

    @field_validator("compose_files")
    @classmethod
    def _v_files(cls, v):
        return _files(v)


class ActionIn(BaseModel):
    service: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][\w.-]*$", max_length=128)
    no_cache: bool = False


class FileIn(BaseModel):
    path: str
    content: str


class PathIn(BaseModel):
    path: str


class RenameIn(BaseModel):
    path: str
    new_path: str


class CheckoutIn(BaseModel):
    branch: str = Field(min_length=1, max_length=255, pattern=r"^[\w][\w./-]*$")


# ---------- helpers ----------
def project_out(p: Project, user: User | None = None, counts: Counter | None = None, total: Counter | None = None) -> dict:
    is_admin = bool(user and ROLE_LEVEL.get(user.role, -1) >= ROLE_LEVEL["admin"])
    return {
        "id": p.id, "slug": p.slug, "name": p.name, "description": p.description, "source": p.source,
        "path": p.path, "managed": p.managed, "repo_url": p.repo_url, "branch": p.branch,
        "git_username": p.git_username, "has_token": bool(p.git_token_enc), "ssh_key": p.ssh_key,
        "compose_files": p.compose_files, "env_file": p.env_file,
        "webhook_enabled": p.webhook_enabled,
        # webhook secret allows triggering deploys -> admins only
        "webhook_url": f"{settings.public_url}/api/webhooks/{p.slug}" if (p.webhook_secret and is_admin) else "",
        "webhook_secret": p.webhook_secret if is_admin else "",
        "busy": runner.is_busy(p.id), "created_at": p.created_at,
        "containers_running": (counts or {}).get(p.slug, 0),
        "containers_total": (total or {}).get(p.slug, 0),
    }


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-_")
    return s[:60] or "project"


def safe_path(p: Project, rel: str) -> Path:
    root = Path(p.path).resolve()
    target = (root / rel.lstrip("/\\")).resolve()
    if target != root and not target.is_relative_to(root):
        raise HTTPException(400, "Path is outside of project")
    return target


def check_writable(p: Project, target: Path) -> None:
    rel = target.relative_to(Path(p.path).resolve())
    if rel.parts and rel.parts[0] == ".git":
        raise HTTPException(400, ".git is read-only")


def start_job(p: Project, user: User, action: str, steps, cwd=None, on_success=None) -> dict:
    try:
        jid = runner.start(
            action=action, steps=steps, cwd=cwd or p.path, project_id=p.id,
            username=user.username, on_success=on_success, env=git_ops.git_env(p),
        )
    except BusyError as e:
        raise HTTPException(409, str(e))
    return {"job_id": jid}


def check_ssh_key(name: str) -> str:
    name = (name or "").strip()
    if name and name not in {k["name"] for k in git_ops.list_ssh_keys()}:
        raise HTTPException(400, f"SSH key '{name}' not found in {settings.ssh_dir}")
    return name


@router.get("/ssh-keys")
def ssh_keys(_: User = Depends(require("operator"))):
    return {"dir": str(settings.ssh_dir), "keys": git_ops.list_ssh_keys()}


# ---------- import of existing compose stacks ----------
class ImportIn(BaseModel):
    slug: str
    name: str | None = None
    ssh_key: str = ""


@router.get("/discover")
def discover(_: User = Depends(require("admin")), db: Session = Depends(get_db)):
    known = set(db.scalars(select(Project.slug)))
    return discover_stacks(known)


@router.post("/import")
def import_stack(data: ImportIn, user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    if not settings.allow_local_paths:
        raise HTTPException(403, "Local paths are disabled (DM_ALLOW_LOCAL_PATHS=false)")
    known = set(db.scalars(select(Project.slug)))
    stack = next((s for s in discover_stacks(known) if s["slug"] == data.slug), None)
    if not stack:
        raise HTTPException(404, "Stack not found among running containers")
    if stack["registered"]:
        raise HTTPException(409, "Stack is already registered as a project")
    if not stack["accessible"]:
        raise HTTPException(400, f"Directory {stack['working_dir'] or '(unknown)'} is not accessible from the panel "
                                 "(mount it into the container at the same path)")
    path = Path(stack["working_dir"]).resolve()
    managed = path.is_relative_to(settings.projects_dir)
    p = Project(
        slug=stack["slug"], name=data.name or stack["slug"],
        description="Импортирован из запущенного compose-стека",
        source="git" if stack["git_repo_url"] else "local",
        path=str(path), managed=managed,
        repo_url=stack["git_repo_url"], branch=stack["git_branch"],
        compose_files=stack["compose_files"], env_file=stack["env_file"],
        ssh_key=check_ssh_key(data.ssh_key), webhook_secret=secrets.token_urlsafe(24),
    )
    db.add(p)
    db.commit()
    audit(db, user, "project.import", p.slug, str(path))
    return project_out(p, user)


# ---------- CRUD ----------
@router.get("")
def list_projects(user: User = Depends(require("viewer")), db: Session = Depends(get_db)):
    running, total = Counter(), Counter()
    try:
        for c in list_containers():
            if c["project"]:
                total[c["project"]] += 1
                if c["state"] == "running":
                    running[c["project"]] += 1
    except HTTPException:
        pass
    return [project_out(p, user, running, total) for p in db.scalars(select(Project).order_by(Project.name))]


@router.post("")
def create_project(data: ProjectIn, user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    slug = data.slug or slugify(data.name)
    if db.scalar(select(Project).where(Project.slug == slug)):
        raise HTTPException(409, f"Project with slug '{slug}' already exists")

    managed = True
    if data.source == "local":
        if not settings.allow_local_paths:
            raise HTTPException(403, "Local paths are disabled (DM_ALLOW_LOCAL_PATHS=false)")
        path = Path(data.path).expanduser().resolve()
        if not path.is_dir():
            raise HTTPException(400, f"Directory not found: {path}")
        managed = False
    else:
        path = settings.projects_dir / slug
        if path.exists() and any(path.iterdir()):
            raise HTTPException(409, f"Directory {path} already exists and is not empty")

    if data.source == "git" and not data.repo_url:
        raise HTTPException(400, "repo_url is required")

    p = Project(
        slug=slug, name=data.name, description=data.description,
        source="git" if data.source == "git" else "local",
        path=str(path), managed=managed, repo_url=data.repo_url.strip(), branch=data.branch.strip(),
        git_username=data.git_username.strip(), git_token_enc=encrypt(data.git_token.strip()),
        ssh_key=check_ssh_key(data.ssh_key),
        compose_files=data.compose_files.strip() or "docker-compose.yml", env_file=data.env_file.strip(),
        webhook_secret=secrets.token_urlsafe(24),
    )
    db.add(p)
    db.commit()
    audit(db, user, "project.create", slug, f"source={data.source}")

    result = project_out(p, user)
    if data.source == "empty":
        path.mkdir(parents=True, exist_ok=True)
        cf = path / compose.compose_files(p)[0]
        if not cf.exists():
            cf.write_text("services:\n  web:\n    image: nginx:alpine\n    ports:\n      - \"8080:80\"\n", encoding="utf-8")
    elif data.source == "git":
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            path.rmdir()
        result.update(_clone(p, user))
    return result


def _clone(p: Project, user: User) -> dict:
    pid = p.id

    def done():
        db = SessionLocal()
        proj = db.get(Project, pid)
        if proj and not proj.branch:
            try:
                proj.branch = git_ops.run(proj, "rev-parse", "--abbrev-ref", "HEAD").strip()
                db.commit()
            except git_ops.GitError:
                pass
        db.close()

    return start_job(p, user, "git.clone", git_ops.clone_steps(p), cwd=str(settings.projects_dir), on_success=done)


@router.get("/{project_id}")
def get_one(project_id: int, user: User = Depends(require("viewer")), db: Session = Depends(get_db)):
    p = get_project(db, project_id)
    return project_out(p, user)


@router.patch("/{project_id}")
def update_project(project_id: int, data: ProjectPatch, user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    p = get_project(db, project_id)
    for field in ("name", "description", "repo_url", "git_username", "compose_files", "env_file", "webhook_enabled"):
        v = getattr(data, field)
        if v is not None:
            setattr(p, field, v.strip() if isinstance(v, str) else v)
    if data.env_file:
        safe_path(p, data.env_file)
    if data.ssh_key is not None:
        p.ssh_key = check_ssh_key(data.ssh_key)
    if data.git_token:
        p.git_token_enc = encrypt(data.git_token.strip())
    if data.clear_token:
        p.git_token_enc = ""
    if data.regenerate_webhook or not p.webhook_secret:
        p.webhook_secret = secrets.token_urlsafe(24)
    db.commit()
    audit(db, user, "project.update", p.slug, data.model_dump_json(exclude={"git_token"}, exclude_defaults=True))
    return project_out(p, user)


@router.post("/{project_id}/env")
def set_env(project_id: int, data: PathIn, user: User = Depends(require("operator")), db: Session = Depends(get_db)):
    """Select active .env file (operators may switch env without full admin rights)."""
    p = get_project(db, project_id)
    if data.path:
        target = safe_path(p, data.path)
        if not target.is_file():
            raise HTTPException(404, "File not found")
    p.env_file = data.path
    db.commit()
    audit(db, user, "project.env.select", p.slug, data.path or "(none)")
    return project_out(p, user)


@router.delete("/{project_id}")
def delete_project(
    project_id: int, remove_files: bool = False, compose_down: bool = False,
    user: User = Depends(require("admin")), db: Session = Depends(get_db),
):
    p = get_project(db, project_id)
    if runner.is_busy(p.id):
        raise HTTPException(409, "A job is running for this project")
    if compose_down and Path(p.path).exists():
        compose.run(p, "down", "--remove-orphans", timeout=300)
    if remove_files and p.managed:
        root = Path(p.path).resolve()
        if root.is_relative_to(settings.projects_dir) and root != settings.projects_dir:
            shutil.rmtree(root, ignore_errors=True)
    db.delete(p)
    db.commit()
    audit(db, user, "project.delete", p.slug, f"remove_files={remove_files} compose_down={compose_down}")
    return {"ok": True}


# ---------- compose ----------
@router.get("/{project_id}/services")
def project_services(project_id: int, _: User = Depends(require("viewer")), db: Session = Depends(get_db)):
    p = get_project(db, project_id)
    names, error = compose.services(p)
    try:
        containers = list_containers(p.slug)
        docker_error = None
    except HTTPException as e:
        containers, docker_error = [], e.detail
    by_service: dict[str, list] = {n: [] for n in names}
    for c in containers:
        by_service.setdefault(c["service"] or c["name"], []).append(c)
    return {
        "services": [{"name": n, "containers": cs} for n, cs in by_service.items()],
        "config_error": error, "docker_error": docker_error,
    }


@router.get("/{project_id}/config")
def project_config(project_id: int, _: User = Depends(require("operator")), db: Session = Depends(get_db)):
    p = get_project(db, project_id)
    ok, out = compose.config(p)
    return {"ok": ok, "output": out}


@router.post("/{project_id}/actions/{action}")
def project_action(
    project_id: int, action: str, data: ActionIn | None = None,
    user: User = Depends(require("operator")), db: Session = Depends(get_db),
):
    p = get_project(db, project_id)
    if action not in compose.ACTIONS:
        raise HTTPException(400, f"Unknown action: {action}")
    service = data.service if data else None
    no_cache = data.no_cache if data else False
    if not Path(p.path).exists():
        raise HTTPException(400, "Project directory does not exist (clone first?)")
    if service:
        names, _err = compose.services(p)
        if names and service not in names:
            raise HTTPException(400, f"Unknown service '{service}'")
    steps = compose.action_steps(p, action, service, no_cache)
    audit(db, user, f"compose.{action}", p.slug, service or "")
    return start_job(p, user, f"compose.{action}" + (f":{service}" if service else ""), steps)


# ---------- git ----------
def _require_git(p: Project):
    if p.source != "git":
        raise HTTPException(400, "Not a git project")


@router.get("/{project_id}/git/status")
def git_status(project_id: int, _: User = Depends(require("viewer")), db: Session = Depends(get_db)):
    p = get_project(db, project_id)
    if p.source != "git":
        return {"is_repo": False, "source": p.source}
    try:
        return git_ops.status(p)
    except git_ops.GitError as e:
        raise HTTPException(400, str(e))


@router.post("/{project_id}/git/fetch")
def git_fetch(project_id: int, user: User = Depends(require("operator")), db: Session = Depends(get_db)):
    p = get_project(db, project_id)
    _require_git(p)
    try:
        git_ops.fetch(p)
        return git_ops.status(p)
    except git_ops.GitError as e:
        raise HTTPException(400, str(e))


@router.get("/{project_id}/git/branches")
def git_branches(project_id: int, _: User = Depends(require("viewer")), db: Session = Depends(get_db)):
    p = get_project(db, project_id)
    _require_git(p)
    try:
        return git_ops.branches(p)
    except git_ops.GitError as e:
        raise HTTPException(400, str(e))


@router.get("/{project_id}/git/log")
def git_log(project_id: int, n: int = 50, _: User = Depends(require("viewer")), db: Session = Depends(get_db)):
    p = get_project(db, project_id)
    _require_git(p)
    try:
        return git_ops.log(p, min(n, 500))
    except git_ops.GitError as e:
        raise HTTPException(400, str(e))


@router.post("/{project_id}/git/clone")
def git_clone(project_id: int, user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    p = get_project(db, project_id)
    _require_git(p)
    path = Path(p.path)
    if path.exists() and any(path.iterdir()):
        raise HTTPException(409, "Directory is not empty")
    if path.exists():
        path.rmdir()
    audit(db, user, "git.clone", p.slug)
    return _clone(p, user)


@router.post("/{project_id}/git/pull")
def git_pull(project_id: int, user: User = Depends(require("operator")), db: Session = Depends(get_db)):
    p = get_project(db, project_id)
    _require_git(p)
    audit(db, user, "git.pull", p.slug)
    return start_job(p, user, "git.pull", git_ops.pull_steps(p))


@router.post("/{project_id}/git/checkout")
def git_checkout(project_id: int, data: CheckoutIn, user: User = Depends(require("operator")), db: Session = Depends(get_db)):
    p = get_project(db, project_id)
    _require_git(p)
    pid, branch = p.id, data.branch

    def done():
        s = SessionLocal()
        proj = s.get(Project, pid)
        if proj:
            proj.branch = branch
            s.commit()
        s.close()

    audit(db, user, "git.checkout", p.slug, branch)
    return start_job(p, user, f"git.checkout:{branch}", git_ops.checkout_steps(p, branch), on_success=done)


@router.post("/{project_id}/git/reset")
def git_reset(project_id: int, user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    p = get_project(db, project_id)
    _require_git(p)
    audit(db, user, "git.reset", p.slug)
    return start_job(p, user, "git.reset", git_ops.reset_steps(p))


# ---------- files / env ----------
@router.get("/{project_id}/env-files")
def env_files(project_id: int, _: User = Depends(require("viewer")), db: Session = Depends(get_db)):
    p = get_project(db, project_id)
    root = Path(p.path)
    found: set[str] = set()
    if root.exists():
        for pat in ENV_PATTERNS:
            for f in root.glob(pat):
                if f.is_file():
                    found.add(f.relative_to(root).as_posix())
    return {"files": sorted(found), "active": p.env_file}


@router.get("/{project_id}/files")
def list_or_read(project_id: int, path: str = "", _: User = Depends(require("operator")), db: Session = Depends(get_db)):
    p = get_project(db, project_id)
    target = safe_path(p, path)
    if not target.exists():
        raise HTTPException(404, "Not found")
    root = Path(p.path).resolve()
    if target.is_dir():
        entries = []
        for e in sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            try:
                st = e.stat()
            except OSError:
                continue
            entries.append({
                "name": e.name, "path": e.relative_to(root).as_posix(),
                "type": "dir" if e.is_dir() else "file", "size": st.st_size, "mtime": st.st_mtime,
            })
        return {"type": "dir", "path": target.relative_to(root).as_posix() if target != root else "", "entries": entries}
    size = target.stat().st_size
    if size > settings.max_file_size:
        raise HTTPException(413, f"File too large ({size} bytes)")
    raw = target.read_bytes()
    if b"\x00" in raw[:8000]:
        return {"type": "file", "path": path, "binary": True, "size": size, "content": ""}
    return {"type": "file", "path": path, "binary": False, "size": size, "content": raw.decode("utf-8", errors="replace")}


@router.put("/{project_id}/files")
def write_file(project_id: int, data: FileIn, user: User = Depends(require("operator")), db: Session = Depends(get_db)):
    p = get_project(db, project_id)
    target = safe_path(p, data.path)
    check_writable(p, target)
    if target.is_dir():
        raise HTTPException(400, "Path is a directory")
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8", newline="") as f:
        f.write(data.content)
    audit(db, user, "file.write", p.slug, data.path)
    return {"ok": True}


@router.post("/{project_id}/files/mkdir")
def make_dir(project_id: int, data: PathIn, user: User = Depends(require("operator")), db: Session = Depends(get_db)):
    p = get_project(db, project_id)
    target = safe_path(p, data.path)
    check_writable(p, target)
    target.mkdir(parents=True, exist_ok=True)
    audit(db, user, "file.mkdir", p.slug, data.path)
    return {"ok": True}


@router.post("/{project_id}/files/rename")
def rename_file(project_id: int, data: RenameIn, user: User = Depends(require("operator")), db: Session = Depends(get_db)):
    p = get_project(db, project_id)
    src, dst = safe_path(p, data.path), safe_path(p, data.new_path)
    check_writable(p, src)
    check_writable(p, dst)
    if not src.exists():
        raise HTTPException(404, "Not found")
    if dst.exists():
        raise HTTPException(409, "Destination exists")
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dst)
    audit(db, user, "file.rename", p.slug, f"{data.path} -> {data.new_path}")
    return {"ok": True}


@router.delete("/{project_id}/files")
def delete_file(project_id: int, path: str = Query(...), user: User = Depends(require("operator")), db: Session = Depends(get_db)):
    p = get_project(db, project_id)
    target = safe_path(p, path)
    if target == Path(p.path).resolve():
        raise HTTPException(400, "Cannot delete project root")
    check_writable(p, target)
    if not target.exists():
        raise HTTPException(404, "Not found")
    if target.is_dir():
        shutil.rmtree(target)
    else:
        target.unlink()
    if p.env_file and safe_path(p, p.env_file) == target:
        p.env_file = ""
        db.commit()
    audit(db, user, "file.delete", p.slug, path)
    return {"ok": True}


# ---------- combined logs of all services ----------
@router.websocket("/{project_id}/logs")
async def ws_project_logs(ws: WebSocket, project_id: int):
    """Stream `docker compose logs -f` for the whole project (or selected services)."""
    from .docker_res import _pump

    db = SessionLocal()
    try:
        user = ws_user(ws, db)
        p = db.get(Project, project_id)
    finally:
        db.close()
    if not user or not p:
        await ws.close(code=4401 if not user else 4404)
        return
    await ws.accept()

    tail = ws.query_params.get("tail", "200")
    tail = tail if tail.isdigit() or tail == "all" else "200"
    services = [s for s in ws.query_params.get("services", "").split(",") if re.fullmatch(r"[A-Za-z0-9][\w.-]*", s)]
    args = [*compose.base(p, ansi="always"), "logs", "-f", "--tail", tail]
    if ws.query_params.get("timestamps") == "1":
        args.append("--timestamps")
    args += services

    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()
    try:
        proc = subprocess.Popen(args, cwd=p.path, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, bufsize=0)
    except (FileNotFoundError, NotADirectoryError, OSError) as e:
        await ws.send_text(f"\r\n[error] {e}\r\n")
        await ws.close()
        return

    def reader():
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        try:
            assert proc.stdout is not None
            while True:
                data = proc.stdout.read(4096)
                if not data:
                    break
                loop.call_soon_threadsafe(q.put_nowait, decoder.decode(data))
        except Exception:  # noqa: BLE001
            pass
        finally:
            loop.call_soon_threadsafe(q.put_nowait, None)

    threading.Thread(target=reader, daemon=True).start()
    try:
        await _pump(ws, q)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        if proc.poll() is None:
            proc.kill()
        try:
            await ws.close()
        except RuntimeError:
            pass
