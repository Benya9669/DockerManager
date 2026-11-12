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

Step = tuple[str, list[str]]  # (label shown to user, argv)


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
            target=self._run, args=(live, steps, cwd, env, project_id, on_success), daemon=True
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

    def _run(self, live: LiveJob, steps, cwd, env, project_id, on_success) -> None:
        status = "success"
        full_env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", **(env or {})}
        try:
            for label, argv in steps:
                if live.cancelled:
                    status = "cancelled"
                    break
                self._emit(live, f"\x1b[36m$ {label}\x1b[0m\n")
                try:
                    proc = subprocess.Popen(
                        argv, cwd=cwd, env=full_env, stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, bufsize=0,
                    )
                except FileNotFoundError as e:
                    self._emit(live, f"\x1b[31m{e}\x1b[0m\n")
                    status = "failed"
                    break
                live.proc = proc
                decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
                assert proc.stdout is not None
                while True:
                    data = proc.stdout.read(4096)
                    if not data:
                        break
                    self._emit(live, decoder.decode(data))
                self._emit(live, decoder.decode(b"", final=True))
                rc = proc.wait()
                if live.cancelled:
                    status = "cancelled"
                    self._emit(live, "\x1b[33mCancelled\x1b[0m\n")
                    break
                if rc != 0:
                    status = "failed"
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
        finally:
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


runner = JobRunner()
