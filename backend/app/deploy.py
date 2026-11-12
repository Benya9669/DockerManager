"""Safe deploy: snapshot -> update -> healthcheck -> (auto)rollback.

A snapshot captures what is needed to bring a project back: git commit, contents of the
compose files and the active env file, and the image IDs the containers were running
(so `image: foo:latest` can be re-tagged to the previous image on rollback).
"""
import json
import time
from pathlib import Path

from . import compose, git_ops
from .db import SessionLocal
from .dockerc import api
from .jobs import JobContext
from .models import Deployment, Project, utcnow
from .security import decrypt, encrypt


# ---------- snapshots ----------
def _head(p: Project) -> str:
    if p.source != "git" or not git_ops.is_repo(p):
        return ""
    try:
        return git_ops.run(p, "rev-parse", "HEAD").strip()
    except git_ops.GitError:
        return ""


def _containers(p: Project) -> list[dict]:
    return api(p.server_id).containers(all=True, filters={"label": f"com.docker.compose.project={p.slug}"})


def snapshot(p: Project) -> dict:
    root = Path(p.path)
    files: dict[str, str] = {}
    for name in compose.compose_files(p) + ([p.env_file] if p.env_file else []):
        f = root / name
        if f.is_file() and f.stat().st_size < 1_000_000:
            files[name] = f.read_text(encoding="utf-8", errors="replace")
    images: dict[str, str] = {}
    try:
        for c in _containers(p):
            ref, iid = c.get("Image"), c.get("ImageID")
            if ref and iid and not ref.startswith("sha256:"):
                images[ref] = iid
    except Exception:  # noqa: BLE001  (docker unavailable)
        pass
    return {"commit": _head(p), "env_file": p.env_file, "files": files, "images": images}


def _save(dep_id: int, **fields) -> None:
    db = SessionLocal()
    try:
        d = db.get(Deployment, dep_id)
        if d:
            for k, v in fields.items():
                setattr(d, k, v)
            db.commit()
    finally:
        db.close()


# ---------- health ----------
def check_health(p: Project) -> tuple[str, list[str], int]:
    """Returns (ok|wait|fail, messages, total restart count)."""
    cs = _containers(p)
    if not cs:
        return "fail", ["контейнеры проекта не найдены"], 0
    state, msgs, restarts = "ok", [], 0
    for c in cs:
        info = api(p.server_id).inspect_container(c["Id"])
        st = info.get("State") or {}
        name = info.get("Name", "?").lstrip("/")
        restarts += info.get("RestartCount") or 0
        health = (st.get("Health") or {}).get("Status")
        status = st.get("Status")
        if status == "running":
            if health == "unhealthy":
                state = "fail"
                msgs.append(f"{name}: unhealthy")
            elif health == "starting":
                state = "wait" if state == "ok" else state
                msgs.append(f"{name}: healthcheck выполняется")
            else:
                msgs.append(f"{name}: работает" + (" (healthy)" if health == "healthy" else ""))
        elif status == "exited":
            code = st.get("ExitCode")
            if code == 0:
                msgs.append(f"{name}: завершился с кодом 0 (одноразовый)")
            else:
                state = "fail"
                msgs.append(f"{name}: упал с кодом {code}")
        else:  # created / restarting / paused
            state = "wait" if state == "ok" else state
            msgs.append(f"{name}: {status}")
    return state, msgs, restarts


STABLE_FOR = 10  # seconds all containers must stay healthy (patched in tests)
POLL = 2


def wait_healthy(ctx: JobContext, p: Project, timeout: int, stable_for: int | None = None) -> bool:
    stable_for = STABLE_FOR if stable_for is None else stable_for
    ctx.info(f"Проверка здоровья: до {timeout} с, стабильно {stable_for} с")
    start = time.time()
    ok_since: float | None = None
    base_restarts: int | None = None
    last = ""
    while time.time() - start < timeout:
        if ctx.cancelled:
            return False
        try:
            state, msgs, restarts = check_health(p)
        except Exception as e:  # noqa: BLE001
            ctx.error(f"Ошибка проверки: {e}")
            return False
        if base_restarts is None:
            base_restarts = restarts
        elif restarts > base_restarts:
            state = "fail"
            msgs.append(f"контейнеры перезапускаются (рестартов: {restarts - base_restarts})")
        summary = "; ".join(msgs)
        if summary != last:
            ctx.info("  " + summary)
            last = summary
        if state == "fail":
            ctx.error("Проверка здоровья не пройдена")
            return False
        if state == "ok":
            ok_since = ok_since or time.time()
            if time.time() - ok_since >= stable_for:
                ctx.ok("Все контейнеры работают стабильно")
                return True
        else:
            ok_since = None
        time.sleep(POLL)
    ctx.error(f"Таймаут {timeout} с: контейнеры не пришли в рабочее состояние")
    return False


# ---------- restore ----------
def _split_ref(ref: str) -> tuple[str, str]:
    if "@" in ref:
        return ref, ""
    name, sep, tag = ref.rpartition(":")
    if sep and "/" not in tag:
        return name, tag
    return ref, "latest"


def apply_snapshot(ctx: JobContext, p: Project, snap: dict) -> bool:
    root = Path(p.path).resolve()
    commit = snap.get("commit")
    if commit and _head(p) and _head(p) != commit:
        rc = ctx.run([*git_ops.git_args(p), "reset", "--keep", commit], cwd=p.path, env=git_ops.git_env(p),
                     label=f"git reset --keep {commit[:8]}")
        if rc != 0:
            ctx.error("Не удалось вернуть коммит (есть конфликтующие локальные изменения?)")
            return False
    for name, content in (snap.get("files") or {}).items():
        f = (root / name).resolve()
        if not f.is_relative_to(root):
            continue
        cur = f.read_text(encoding="utf-8", errors="replace") if f.is_file() else None
        if cur != content:
            f.parent.mkdir(parents=True, exist_ok=True)
            with open(f, "w", encoding="utf-8", newline="") as fh:
                fh.write(content)
            ctx.info(f"  восстановлен файл {name}")
    for ref, iid in (snap.get("images") or {}).items():
        repo, tag = _split_ref(ref)
        if not tag:
            continue
        try:
            current = api(p.server_id).inspect_image(ref)["Id"]
        except Exception:  # noqa: BLE001
            current = None
        if current != iid:
            try:
                api(p.server_id).tag(iid, repo, tag)
                ctx.info(f"  образ {ref} → {iid[7:19]}")
            except Exception as e:  # noqa: BLE001
                ctx.error(f"  не удалось вернуть образ {ref}: {e}")
    env_file = snap.get("env_file", p.env_file)
    if env_file != p.env_file:
        p.env_file = env_file
        db = SessionLocal()
        proj = db.get(Project, p.id)
        if proj:
            proj.env_file = env_file
            db.commit()
        db.close()
        ctx.info(f"  активный env: {env_file or '(нет)'}")
    rc = ctx.run([*compose.base(p), "up", "-d", "--build", "--remove-orphans"], cwd=p.path,
                 label="compose up -d --build --remove-orphans")
    return rc == 0


# ---------- public ----------
def deploy_steps(p: Project, username: str, no_cache: bool = False, kind: str = "deploy"):
    """Steps + failure handler for runner.start()."""

    def step_snapshot(ctx: JobContext):
        snap = snapshot(p)
        db = SessionLocal()
        d = Deployment(project_id=p.id, job_id=ctx.job_id, kind=kind, username=username,
                       commit_before=snap["commit"], before_enc=encrypt(json.dumps(snap)))
        db.add(d)
        db.commit()
        ctx.data["dep_id"] = d.id
        db.close()
        ctx.info(f"Снимок текущего состояния сохранён (коммит {snap['commit'][:8] or '—'}, "
                 f"образов: {len(snap['images'])})")

    def step_health(ctx: JobContext):
        return wait_healthy(ctx, p, p.health_timeout or 90)

    def step_finalize(ctx: JobContext):
        after = snapshot(p)
        _save(ctx.data["dep_id"], status="success", commit_after=after["commit"],
              after_enc=encrypt(json.dumps(after)), finished_at=utcnow())
        ctx.ok("Деплой успешен")

    def on_failure(ctx: JobContext):
        dep_id = ctx.data.get("dep_id")
        if not dep_id:
            return
        if not p.auto_rollback:
            _save(dep_id, status="failed", finished_at=utcnow())
            ctx.error("Автооткат выключен — проект оставлен как есть")
            return
        db = SessionLocal()
        d = db.get(Deployment, dep_id)
        snap = json.loads(decrypt(d.before_enc)) if d and d.before_enc else None
        db.close()
        if not snap:
            return
        ctx.emit("\n\x1b[33m↺ Автооткат к предыдущему состоянию\x1b[0m\n")
        ok = apply_snapshot(ctx, p, snap) and wait_healthy(ctx, p, p.health_timeout or 90)
        _save(dep_id, status="rolled_back" if ok else "failed", finished_at=utcnow(),
              message="автооткат выполнен" if ok else "автооткат не удался")
        (ctx.ok if ok else ctx.error)("Откат выполнен, работает предыдущая версия" if ok else "Откат не удался")

    steps = [("Снимок состояния", step_snapshot), *compose.action_steps(p, "deploy", no_cache=no_cache),
             ("Проверка здоровья", step_health), ("", step_finalize)]
    return steps, on_failure


def rollback_steps(p: Project, target: Deployment, username: str):
    """Return the project to the state right after `target` deployment succeeded."""
    target_snap = json.loads(decrypt(target.after_enc))

    def step_snapshot(ctx: JobContext):
        snap = snapshot(p)
        db = SessionLocal()
        d = Deployment(project_id=p.id, job_id=ctx.job_id, kind="rollback", username=username,
                       commit_before=snap["commit"], before_enc=encrypt(json.dumps(snap)),
                       message=f"откат к деплою #{target.id}")
        db.add(d)
        db.commit()
        ctx.data["dep_id"] = d.id
        db.close()

    def step_apply(ctx: JobContext):
        return apply_snapshot(ctx, p, target_snap)

    def step_health(ctx: JobContext):
        return wait_healthy(ctx, p, p.health_timeout or 90)

    def step_finalize(ctx: JobContext):
        after = snapshot(p)
        _save(ctx.data["dep_id"], status="success", commit_after=after["commit"],
              after_enc=encrypt(json.dumps(after)), finished_at=utcnow())
        ctx.ok(f"Проект возвращён к состоянию деплоя #{target.id}")

    def on_failure(ctx: JobContext):
        if ctx.data.get("dep_id"):
            _save(ctx.data["dep_id"], status="failed", finished_at=utcnow())

    return [("Снимок состояния", step_snapshot), (f"Откат к деплою #{target.id}", step_apply),
            ("Проверка здоровья", step_health), ("", step_finalize)], on_failure
