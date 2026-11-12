"""Metrics sampler: container CPU/memory/network and host CPU/memory/disk, kept for N hours.

Container CPU is computed from deltas between our own samples (stats one_shot=True is fast,
but carries no previous reading), so the first sample of a container reports 0%.
"""
import logging
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sqlalchemy import delete, select

from .config import settings
from .db import SessionLocal
from .dockerc import api
from .models import ContainerMetric, HostMetric

log = logging.getLogger("dockermanager.metrics")

_prev_cpu: dict[str, tuple[int, int]] = {}  # container -> (total_usage, system_usage)
_prev_host: tuple[int, int] | None = None  # (idle, total) jiffies from /proc/stat


def _container_sample(c: dict) -> dict | None:
    try:
        s = api().stats(c["Id"], stream=False, one_shot=True)
    except TypeError:  # old docker SDK without one_shot
        s = api().stats(c["Id"], stream=False)
    except Exception:  # noqa: BLE001 — container stopped meanwhile
        return None
    cid = c["Id"][:12]
    cpu_stats = s.get("cpu_stats") or {}
    total = (cpu_stats.get("cpu_usage") or {}).get("total_usage", 0)
    system = cpu_stats.get("system_cpu_usage", 0)
    ncpu = cpu_stats.get("online_cpus") or 1
    cpu = 0.0
    prev = _prev_cpu.get(cid)
    if prev and system > prev[1]:
        cpu = (total - prev[0]) / (system - prev[1]) * ncpu * 100
    _prev_cpu[cid] = (total, system)
    mem_stats = s.get("memory_stats") or {}
    mem = mem_stats.get("usage", 0) - (mem_stats.get("stats") or {}).get("inactive_file", 0)
    nets = s.get("networks") or {}
    labels = c.get("Labels") or {}
    return {
        "container": cid, "name": (c.get("Names") or ["/?"])[0].lstrip("/"),
        "project": labels.get("com.docker.compose.project", ""), "cpu": round(max(cpu, 0), 2),
        "mem": max(mem, 0), "mem_limit": mem_stats.get("limit", 0),
        "net_rx": sum(n.get("rx_bytes", 0) for n in nets.values()),
        "net_tx": sum(n.get("tx_bytes", 0) for n in nets.values()),
    }


def _host_sample() -> dict:
    """/proc in a container still shows host-wide CPU and memory."""
    global _prev_host
    res: dict = {}
    try:
        parts = [int(x) for x in Path("/proc/stat").read_text().split("\n")[0].split()[1:]]
        idle = parts[3] + (parts[4] if len(parts) > 4 else 0)  # idle + iowait
        total = sum(parts)
        if _prev_host and total > _prev_host[1]:
            res["cpu"] = round(100 * (1 - (idle - _prev_host[0]) / (total - _prev_host[1])), 2)
        _prev_host = (idle, total)
    except (OSError, ValueError, IndexError):
        pass
    try:
        info = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            k, v = line.split(":", 1)
            info[k] = int(v.split()[0]) * 1024
        res["mem_total"] = info.get("MemTotal", 0)
        res["mem_used"] = info.get("MemTotal", 0) - info.get("MemAvailable", 0)
    except (OSError, ValueError):
        pass
    try:
        du = shutil.disk_usage(settings.data_dir)
        res["disk_total"], res["disk_used"] = du.total, du.used
    except OSError:
        pass
    return res


def sample_once() -> None:
    now = int(time.time())
    rows = []
    try:
        running = api().containers(filters={"status": "running"})
        with ThreadPoolExecutor(max_workers=8) as pool:
            rows = [r for r in pool.map(_container_sample, running) if r]
    except Exception as e:  # noqa: BLE001
        log.debug("container metrics skipped: %s", e)
    host = _host_sample()
    db = SessionLocal()
    try:
        db.add_all(ContainerMetric(ts=now, **r) for r in rows)
        if host:
            db.add(HostMetric(ts=now, **host))
        db.execute(delete(ContainerMetric).where(ContainerMetric.ts < now - settings.metrics_retention_hours * 3600))
        db.execute(delete(HostMetric).where(HostMetric.ts < now - settings.metrics_retention_hours * 3600))
        db.commit()
    finally:
        db.close()


def _loop() -> None:
    while True:
        try:
            sample_once()
        except Exception as e:  # noqa: BLE001
            log.warning("metrics sample failed: %s", e)
        time.sleep(settings.metrics_interval)


def start_background() -> None:
    if settings.metrics_interval > 0:
        threading.Thread(target=_loop, daemon=True).start()


# ---------- queries ----------
def _bucket(points: list, max_points: int = 300) -> list:
    if len(points) <= max_points:
        return points
    step = len(points) / max_points
    return [points[int(i * step)] for i in range(max_points)]


def host_series(hours: float) -> list[dict]:
    since = int(time.time() - hours * 3600)
    db = SessionLocal()
    try:
        rows = db.scalars(select(HostMetric).where(HostMetric.ts >= since).order_by(HostMetric.ts)).all()
    finally:
        db.close()
    return _bucket([{"ts": r.ts, "cpu": r.cpu, "mem_used": r.mem_used, "mem_total": r.mem_total,
                     "disk_used": r.disk_used, "disk_total": r.disk_total} for r in rows])


def container_series(hours: float, project: str | None = None, container: str | None = None) -> list[dict]:
    since = int(time.time() - hours * 3600)
    q = select(ContainerMetric).where(ContainerMetric.ts >= since).order_by(ContainerMetric.ts)
    if project:
        q = q.where(ContainerMetric.project == project)
    if container:
        q = q.where(ContainerMetric.container == container[:12])
    db = SessionLocal()
    try:
        rows = db.scalars(q).all()
    finally:
        db.close()
    by: dict[str, dict] = {}
    for r in rows:
        s = by.setdefault(r.name, {"name": r.name, "container": r.container, "project": r.project, "points": []})
        s["points"].append([r.ts, r.cpu, r.mem, r.mem_limit, r.net_rx, r.net_tx])
    for s in by.values():
        s["points"] = _bucket(s["points"])
    return sorted(by.values(), key=lambda s: s["name"])
