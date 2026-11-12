"""Discover compose stacks already running on the host (from container labels)."""
import subprocess
from pathlib import Path, PurePath

from .dockerc import api

L_PROJECT = "com.docker.compose.project"
L_WORKDIR = "com.docker.compose.project.working_dir"
L_FILES = "com.docker.compose.project.config_files"
L_ENV = "com.docker.compose.project.environment_file"


def _rel(path: str, workdir: str) -> str:
    """Path relative to workdir when inside it, otherwise unchanged (absolute)."""
    try:
        return PurePath(path).relative_to(PurePath(workdir)).as_posix()
    except ValueError:
        return path


def _git_info(path: Path) -> dict:
    if not (path / ".git").exists():
        return {}

    def g(*args: str) -> str:
        r = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else ""

    return {"repo_url": g("remote", "get-url", "origin"), "branch": g("rev-parse", "--abbrev-ref", "HEAD")}


def discover_stacks(known_slugs: set[str]) -> list[dict]:
    stacks: dict[str, dict] = {}
    for c in api().containers(all=True, filters={"label": L_PROJECT}):
        labels = c.get("Labels") or {}
        name = labels.get(L_PROJECT)
        if not name:
            continue
        s = stacks.setdefault(name, {
            "slug": name, "working_dir": "", "config_files": [], "env_files": [],
            "services": set(), "running": 0, "total": 0,
        })
        s["total"] += 1
        if c.get("State") == "running":
            s["running"] += 1
        if svc := labels.get("com.docker.compose.service"):
            s["services"].add(svc)
        if not s["working_dir"] and labels.get(L_WORKDIR):
            s["working_dir"] = labels[L_WORKDIR]
        if not s["config_files"] and labels.get(L_FILES):
            s["config_files"] = [f for f in labels[L_FILES].split(",") if f]
        if not s["env_files"] and labels.get(L_ENV):
            s["env_files"] = [f for f in labels[L_ENV].split(",") if f]

    result = []
    for s in stacks.values():
        wd = s["working_dir"]
        path = Path(wd) if wd else None
        accessible = bool(path and path.is_dir())
        files = [_rel(f, wd) for f in s["config_files"]] if wd else s["config_files"]
        env = _rel(s["env_files"][0], wd) if (wd and s["env_files"]) else ""
        git = _git_info(path) if accessible and path else {}
        result.append({
            "slug": s["slug"],
            "working_dir": wd,
            "compose_files": ",".join(files) or "docker-compose.yml",
            "env_file": env,
            "services": sorted(s["services"]),
            "running": s["running"],
            "total": s["total"],
            "accessible": accessible,
            "git_repo_url": git.get("repo_url", ""),
            "git_branch": git.get("branch", ""),
            "registered": s["slug"] in known_slugs,
        })
    return sorted(result, key=lambda x: (x["registered"], x["slug"]))
