import asyncio
import json
import threading

from docker.errors import APIError, NotFound
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from ..db import SessionLocal
from ..deps import ROLE_LEVEL, audit, require, ws_user
from ..dockerc import api, list_containers
from ..jobs import runner
from ..models import User
from ..db import get_db
from sqlalchemy.orm import Session

router = APIRouter(prefix="/api/docker", tags=["docker"])


def _err(e: Exception):
    if isinstance(e, NotFound):
        raise HTTPException(404, str(e.explanation if hasattr(e, "explanation") else e))
    if isinstance(e, APIError):
        raise HTTPException(e.status_code or 400, str(e.explanation or e))
    raise e


# ---------- system ----------
@router.get("/info")
def info(_: User = Depends(require("viewer"))):
    i = api().info()
    v = api().version()
    return {
        "server_version": v.get("Version"), "api_version": v.get("ApiVersion"), "os": i.get("OperatingSystem"),
        "arch": i.get("Architecture"), "cpus": i.get("NCPU"), "mem_total": i.get("MemTotal"),
        "containers": i.get("Containers"), "running": i.get("ContainersRunning"),
        "stopped": i.get("ContainersStopped"), "images": i.get("Images"), "name": i.get("Name"),
    }


@router.get("/df")
def disk_usage(_: User = Depends(require("viewer"))):
    d = api().df()
    def total(items, key="Size"):
        return sum((x.get(key) or 0) for x in (items or []))
    images = d.get("Images") or []
    return {
        "images": {"count": len(images), "size": total(images), "reclaimable": sum((x.get("Size") or 0) for x in images if not x.get("Containers"))},
        "containers": {"count": len(d.get("Containers") or []), "size": total(d.get("Containers"), "SizeRw")},
        "volumes": {"count": len(d.get("Volumes") or []), "size": sum(((v.get("UsageData") or {}).get("Size") or 0) for v in (d.get("Volumes") or []))},
        "build_cache": {"count": len(d.get("BuildCache") or []), "size": total(d.get("BuildCache"))},
    }


# ---------- cleanup ----------
class PruneIn(BaseModel):
    containers: bool = True
    images: bool = True
    all_images: bool = False  # remove all unused images, not only dangling
    build_cache: bool = True
    networks: bool = False
    volumes: bool = False
    older_than_hours: int = Field(default=0, ge=0)


def prune_steps(o: PruneIn) -> list[tuple[str, list[str]]]:
    until = ["--filter", f"until={o.older_than_hours}h"] if o.older_than_hours else []
    s = f" (older than {o.older_than_hours}h)" if o.older_than_hours else ""
    steps = []
    if o.containers:
        steps.append((f"docker container prune{s}", ["docker", "container", "prune", "-f", *until]))
    if o.images:
        a = ["-a"] if o.all_images else []
        steps.append((f"docker image prune{' -a' if o.all_images else ''}{s}", ["docker", "image", "prune", "-f", *a, *until]))
    if o.build_cache:
        steps.append((f"docker builder prune{s}", ["docker", "builder", "prune", "-f", *until]))
    if o.networks:
        steps.append((f"docker network prune{s}", ["docker", "network", "prune", "-f", *until]))
    if o.volumes:
        # volume prune does not support "until"; -a removes named unused volumes too
        steps.append(("docker volume prune -a", ["docker", "volume", "prune", "-f", "-a"]))
    return steps


@router.post("/prune")
def prune(data: PruneIn, user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    steps = prune_steps(data)
    if not steps:
        raise HTTPException(400, "Nothing selected")
    audit(db, user, "docker.prune", "", data.model_dump_json())
    return {"job_id": runner.start(action="docker.prune", steps=steps, username=user.username)}


# ---------- containers ----------
@router.get("/containers")
def containers(_: User = Depends(require("viewer"))):
    return list_containers()


@router.get("/containers/{cid}")
def inspect_container(cid: str, user: User = Depends(require("viewer"))):
    try:
        data = api().inspect_container(cid)
    except Exception as e:  # noqa: BLE001
        _err(e)
    if ROLE_LEVEL.get(user.role, -1) < ROLE_LEVEL["operator"]:
        # env vars usually hold secrets (DB passwords, API keys) — hide from viewers
        if isinstance(data.get("Config"), dict):
            data["Config"]["Env"] = ["*** скрыто: нужна роль оператора ***"]
        data.pop("HostConfig", None)
    return data


@router.get("/containers/{cid}/stats")
def container_stats(cid: str, _: User = Depends(require("viewer"))):
    try:
        s = api().stats(cid, stream=False)
    except Exception as e:  # noqa: BLE001
        _err(e)
    cpu = mem = mem_limit = 0.0
    try:
        cd = s["cpu_stats"]["cpu_usage"]["total_usage"] - s["precpu_stats"]["cpu_usage"]["total_usage"]
        sd = s["cpu_stats"].get("system_cpu_usage", 0) - s["precpu_stats"].get("system_cpu_usage", 0)
        n = s["cpu_stats"].get("online_cpus") or 1
        cpu = (cd / sd) * n * 100 if sd > 0 else 0
        mem = s["memory_stats"].get("usage", 0) - (s["memory_stats"].get("stats", {}).get("inactive_file", 0))
        mem_limit = s["memory_stats"].get("limit", 0)
    except (KeyError, TypeError):
        pass
    return {"cpu_percent": round(cpu, 2), "mem_usage": mem, "mem_limit": mem_limit}


@router.post("/containers/{cid}/{action}")
def container_action(cid: str, action: str, user: User = Depends(require("operator")), db: Session = Depends(get_db)):
    a = api()
    try:
        if action == "start":
            a.start(cid)
        elif action == "stop":
            a.stop(cid, timeout=20)
        elif action == "restart":
            a.restart(cid, timeout=20)
        elif action == "kill":
            a.kill(cid)
        elif action == "pause":
            a.pause(cid)
        elif action == "unpause":
            a.unpause(cid)
        elif action == "remove":
            a.remove_container(cid, force=True)
        else:
            raise HTTPException(400, "Unknown action")
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        _err(e)
    audit(db, user, f"container.{action}", cid[:12])
    return {"ok": True}


async def _pump(ws: WebSocket, q: asyncio.Queue, on_input=None) -> None:
    """Forward queue items to ws, and ws messages to on_input, until either side ends."""
    async def sender():
        while True:
            item = await q.get()
            if item is None:
                break
            await ws.send_text(item)

    async def receiver():
        while True:
            msg = await ws.receive_text()
            if on_input:
                on_input(msg)

    tasks = [asyncio.create_task(sender()), asyncio.create_task(receiver())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in tasks:
            t.cancel()


@router.websocket("/containers/{cid}/logs")
async def ws_logs(ws: WebSocket, cid: str):
    db = SessionLocal()
    user = ws_user(ws, db)
    db.close()
    if not user:
        await ws.close(code=4401)
        return
    await ws.accept()
    tail = ws.query_params.get("tail", "500")
    timestamps = ws.query_params.get("timestamps") == "1"
    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()
    holder: dict = {}

    def worker():
        try:
            stream = api().logs(cid, stream=True, follow=True, tail=int(tail) if tail.isdigit() else "all", timestamps=timestamps)
            holder["stream"] = stream
            for chunk in stream:
                loop.call_soon_threadsafe(q.put_nowait, chunk.decode("utf-8", errors="replace"))
        except Exception as e:  # noqa: BLE001
            loop.call_soon_threadsafe(q.put_nowait, f"\r\n[error] {e}\r\n")
        finally:
            loop.call_soon_threadsafe(q.put_nowait, None)

    threading.Thread(target=worker, daemon=True).start()
    try:
        await _pump(ws, q)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        s = holder.get("stream")
        if s is not None and hasattr(s, "close"):
            try:
                s.close()
            except Exception:  # noqa: BLE001
                pass
        try:
            await ws.close()
        except RuntimeError:
            pass


@router.websocket("/containers/{cid}/exec")
async def ws_exec(ws: WebSocket, cid: str):
    db = SessionLocal()
    user = ws_user(ws, db, role="operator")
    if user:
        audit(db, user, "container.exec", cid[:12], ws.query_params.get("cmd", ""))
    db.close()
    if not user:
        await ws.close(code=4401)
        return
    await ws.accept()
    cmd = ws.query_params.get("cmd") or "command -v bash >/dev/null 2>&1 && exec bash || exec sh"
    a = api()
    try:
        exec_id = a.exec_create(cid, ["/bin/sh", "-c", cmd], tty=True, stdin=True, stdout=True, stderr=True,
                                environment={"TERM": "xterm-256color"})["Id"]
        sock = a.exec_start(exec_id, tty=True, socket=True)
    except Exception as e:  # noqa: BLE001
        await ws.send_text(f"\r\n[error] {e}\r\n")
        await ws.close()
        return
    raw = getattr(sock, "_sock", sock)
    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()

    def reader():
        try:
            while True:
                data = raw.recv(4096)
                if not data:
                    break
                loop.call_soon_threadsafe(q.put_nowait, data.decode("utf-8", errors="replace"))
        except Exception:  # noqa: BLE001
            pass
        finally:
            loop.call_soon_threadsafe(q.put_nowait, None)

    def on_input(msg: str):
        try:
            m = json.loads(msg)
        except ValueError:
            return
        if m.get("type") == "input":
            raw.sendall(m["data"].encode())
        elif m.get("type") == "resize":
            try:
                a.exec_resize(exec_id, height=int(m["rows"]), width=int(m["cols"]))
            except Exception:  # noqa: BLE001
                pass

    threading.Thread(target=reader, daemon=True).start()
    try:
        await _pump(ws, q, on_input)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        try:
            raw.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            await ws.close()
        except RuntimeError:
            pass


# ---------- images ----------
class PullIn(BaseModel):
    image: str = Field(min_length=1, max_length=512, pattern=r"^[A-Za-z0-9][\w./:@-]*$")


@router.get("/images")
def images(_: User = Depends(require("viewer"))):
    used = {c["image"] for c in list_containers()}
    used_ids = {c.get("ImageID") for c in api().containers(all=True)}
    res = []
    for i in api().images():
        tags = i.get("RepoTags") or []
        tags = [t for t in tags if t != "<none>:<none>"]
        res.append({
            "id": i["Id"], "short_id": i["Id"].split(":")[-1][:12], "tags": tags,
            "size": i.get("Size"), "created": i.get("Created"),
            "in_use": i["Id"] in used_ids or any(t in used for t in tags),
            "dangling": not tags,
            "project": (i.get("Labels") or {}).get("com.docker.compose.project"),
        })
    return sorted(res, key=lambda x: -(x["created"] or 0))


@router.post("/images/pull")
def pull_image(data: PullIn, user: User = Depends(require("operator")), db: Session = Depends(get_db)):
    audit(db, user, "image.pull", data.image)
    jid = runner.start(action=f"image.pull:{data.image}", steps=[(f"docker pull {data.image}", ["docker", "pull", data.image])], username=user.username)
    return {"job_id": jid}


@router.delete("/images/{image_id}")
def remove_image(image_id: str, force: bool = False, user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    try:
        api().remove_image(image_id, force=force)
    except Exception as e:  # noqa: BLE001
        _err(e)
    audit(db, user, "image.remove", image_id[:24])
    return {"ok": True}


# ---------- volumes ----------
@router.get("/volumes")
def volumes(_: User = Depends(require("viewer"))):
    used: set[str] = set()
    for c in api().containers(all=True):
        for m in c.get("Mounts") or []:
            if m.get("Type") == "volume":
                used.add(m.get("Name"))
    vols = api().volumes().get("Volumes") or []
    return [
        {
            "name": v["Name"], "driver": v.get("Driver"), "mountpoint": v.get("Mountpoint"),
            "created": v.get("CreatedAt"), "in_use": v["Name"] in used,
            "project": (v.get("Labels") or {}).get("com.docker.compose.project"),
        }
        for v in vols
    ]


@router.delete("/volumes/{name}")
def remove_volume(name: str, user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    try:
        api().remove_volume(name)
    except Exception as e:  # noqa: BLE001
        _err(e)
    audit(db, user, "volume.remove", name)
    return {"ok": True}


# ---------- networks ----------
@router.get("/networks")
def networks(_: User = Depends(require("viewer"))):
    return [
        {
            "id": n["Id"], "short_id": n["Id"][:12], "name": n["Name"], "driver": n.get("Driver"),
            "scope": n.get("Scope"), "created": n.get("Created"),
            "subnets": [c.get("Subnet") for c in ((n.get("IPAM") or {}).get("Config") or []) if c.get("Subnet")],
            "project": (n.get("Labels") or {}).get("com.docker.compose.project"),
            "builtin": n["Name"] in ("bridge", "host", "none"),
        }
        for n in api().networks()
    ]


@router.delete("/networks/{nid}")
def remove_network(nid: str, user: User = Depends(require("admin")), db: Session = Depends(get_db)):
    try:
        api().remove_network(nid)
    except Exception as e:  # noqa: BLE001
        _err(e)
    audit(db, user, "network.remove", nid[:12])
    return {"ok": True}
