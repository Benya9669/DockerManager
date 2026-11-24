"""Background job runner: executes command steps in a thread and streams output to websocket subscribers."""
import asyncio
import codecs
import os
import subprocess
import threading
from typing import Callable

from .db import SessionLocal
from .models import Job, utcnow

MAX_OUTPUT = 1_000_000

# (label shown to user, argv) or (label, callable(JobContext) -> bool | None)
Step = tuple[str, "list[str] | Callable[[JobContext], bool | None]"]


class BusyError(Exception):
    pass


class LiveJob:
    def __init__(self, job_id: int):
        self.id = job_id
        self.chunks: list[str] = []
        self.subscribers: set[asyncio.Queue] = set()
        self.done = False
        self.status = "running"
        self.proc: subprocess.Popen | None = None
        self.cancelled = False
        self.lock = threading.Lock()


class JobRunner:
    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self.live: dict[int, LiveJob] = {}
        self.busy: set[int] = set()
        self._lock = threading.Lock()

    def is_busy(self, project_id: int) -> bool:
        return project_id in self.busy

    def start(
        self,
        *,
        action: str,
        steps: list[Step],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        project_id: int | None = None,
        username: str = "",
        on_success: Callable[[], None] | None = None,
        on_failure: "Callable[[JobContext], None] | None" = None,
    ) -> int:
        with self._lock:
            if project_id is not None:
                if project_id in self.busy:
                    raise BusyError("Another job is already running for this project")
                self.busy.add(project_id)
        try:
            db = SessionLocal()
            job = Job(project_id=project_id, action=action, status="running", username=username)
            db.add(job)
            db.commit()
            job_id = job.id
            db.close()
        except Exception:
            self.busy.discard(project_id)  # type: ignore[arg-type]
            raise
        live = LiveJob(job_id)
        self.live[job_id] = live
        threading.Thread(
            target=self._run, args=(live, steps, cwd, env, project_id, on_success, on_failure), daemon=True
        ).start()
        return job_id

    def cancel(self, job_id: int) -> bool:
        live = self.live.get(job_id)
        if not live or live.done:
            return False
        live.cancelled = True
        if live.proc and live.proc.poll() is None:
            live.proc.kill()
        return True

    def subscribe(self, job_id: int) -> tuple[LiveJob | None, asyncio.Queue, list[str]]:
        q: asyncio.Queue = asyncio.Queue()
        live = self.live.get(job_id)
        if not live:
            return None, q, []
        with live.lock:
            snapshot = list(live.chunks)
            if live.done:
                q.put_nowait(("done", live.status))
            else:
                live.subscribers.add(q)
        return live, q, snapshot

    def unsubscribe(self, live: LiveJob | None, q: asyncio.Queue) -> None:
        if live:
            with live.lock:
                live.subscribers.discard(q)

    # --- internals ---
    def _push(self, live: LiveJob, item: tuple[str, str]) -> None:
        for q in list(live.subscribers):
            if self.loop:
                self.loop.call_soon_threadsafe(q.put_nowait, item)

    def _emit(self, live: LiveJob, text: str) -> None:
        if not text:
            return
        with live.lock:
            live.chunks.append(text)
            self._push(live, ("line", text))

    def _run(self, live: LiveJob, steps, cwd, env, project_id, on_success, on_failure=None) -> None:
        status = "success"
        full_env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", **(env or {})}
        ctx = JobContext(self, live, cwd, full_env)
        try:
            for label, step in steps:
                ctx.data["step"] = label
                if live.cancelled:
                    status = "cancelled"
                    break
                if callable(step):
                    # python step: gets a JobContext, returns False on failure
                    if label:
                        ctx.emit(f"\x1b[36m» {label}\x1b[0m\n")
                    ok = step(ctx)
                    if live.cancelled:
                        status = "cancelled"
                        break
                    if ok is False:
                        status = "failed"
                        break
                    continue
                self._emit(live, f"\x1b[36m$ {label}\x1b[0m\n")
                rc = ctx.run(step)
                if live.cancelled:
                    status = "cancelled"
                    self._emit(live, "\x1b[33mCancelled\x1b[0m\n")
                    break
                if rc != 0:
                    status = "failed"
                    if rc != -999:
                        self._emit(live, f"\x1b[31mExit code {rc}\x1b[0m\n")
                    break
            if status == "success" and on_success:
                try:
                    on_success()
                except Exception as e:  # noqa: BLE001
                    self._emit(live, f"\x1b[31mPost-step failed: {e}\x1b[0m\n")
                    status = "failed"
        except Exception as e:  # noqa: BLE001
            status = "failed"
            self._emit(live, f"\x1b[31mInternal error: {e}\x1b[0m\n")
        if status == "failed" and on_failure:
            try:
                on_failure(ctx)
            except Exception as e:  # noqa: BLE001
                self._emit(live, f"\x1b[31mFailure handler error: {e}\x1b[0m\n")
        if status == "success":
            self._emit(live, "\x1b[32mDone\x1b[0m\n")
        output = "".join(live.chunks)[-MAX_OUTPUT:]
        try:
            db = SessionLocal()
            job = db.get(Job, live.id)
            if job:
                job.status = status
                job.output = output
                job.finished_at = utcnow()
                db.commit()
            db.close()
        finally:
            with live.lock:
                live.done = True
                live.status = status
                self._push(live, ("done", status))
            self.live.pop(live.id, None)
            if project_id is not None:
                self.busy.discard(project_id)


class JobContext:
    """Handed to python steps: stream text into the job and run commands with live output/cancel."""

    def __init__(self, runner: JobRunner, live: LiveJob, cwd: str | None, env: dict[str, str]):
        self.runner, self.live, self.cwd, self.env = runner, live, cwd, env
        self.job_id = live.id
        self.data: dict = {}  # shared between steps of one job

    @property
    def cancelled(self) -> bool:
        return self.live.cancelled

    def emit(self, text: str) -> None:
        self.runner._emit(self.live, text)

    def info(self, text: str) -> None:
        self.emit(f"{text}\n")

    def error(self, text: str) -> None:
        self.emit(f"\x1b[31m{text}\x1b[0m\n")

    def ok(self, text: str) -> None:
        self.emit(f"\x1b[32m{text}\x1b[0m\n")

    def run(self, argv: list[str], cwd: str | None = None, env: dict[str, str] | None = None,
            label: str | None = None) -> int:
        """Run a command streaming its output; returns exit code (-999 if it could not start)."""
        if label:
            self.emit(f"\x1b[36m$ {label}\x1b[0m\n")
        try:
            proc = subprocess.Popen(
                argv, cwd=cwd or self.cwd, env={**self.env, **(env or {})}, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, bufsize=0,
            )
        except (FileNotFoundError, NotADirectoryError, PermissionError) as e:
            self.error(str(e))
            return -999
        self.live.proc = proc
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        assert proc.stdout is not None
        while True:
            data = proc.stdout.read(4096)
            if not data:
                break
            self.emit(decoder.decode(data))
        self.emit(decoder.decode(b"", final=True))
        return proc.wait()


runner = JobRunner()
