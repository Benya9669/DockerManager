import os
import subprocess
from pathlib import Path

from . import git_ops
from .models import Project

Step = tuple[str, list[str]]


def compose_files(p: Project) -> list[str]:
    return [f.strip() for f in (p.compose_files or "").split(",") if f.strip()]


def base(p: Project, ansi: str = "never") -> list[str]:
    args = ["docker", "compose", "--ansi", ansi, "-p", p.slug]
    for f in compose_files(p):
        args += ["-f", f]
    if p.env_file:
        args += ["--env-file", p.env_file]
    return args


def env(p: Project) -> dict[str, str]:
    """Process env for docker/compose commands of this project (DOCKER_HOST for remote servers)."""
    from .servers import docker_env
    return {**os.environ, **docker_env(p)}


def run(p: Project, *args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        [*base(p), *args], cwd=p.path, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout, env=env(p),
    )


def services(p: Project) -> tuple[list[str], str | None]:
    if not Path(p.path).exists():
        return [], "Project directory does not exist"
    try:
        r = run(p, "config", "--services")
    except subprocess.TimeoutExpired:
        return [], "docker compose config timed out"
    except FileNotFoundError:
        return [], "docker CLI not found"
    if r.returncode != 0:
        return [], (r.stderr or r.stdout).strip()
    return [s for s in r.stdout.splitlines() if s.strip()], None


def config(p: Project) -> tuple[bool, str]:
    r = run(p, "config")
    return r.returncode == 0, (r.stdout if r.returncode == 0 else (r.stderr or r.stdout))


ACTIONS = {"up", "down", "restart", "stop", "start", "pull", "build", "rebuild", "deploy", "recreate", "cleanup"}


def action_steps(p: Project, action: str, service: str | None = None, no_cache: bool = False) -> list[Step]:
    b = base(p)
    svc = [service] if service else []
    s = f" {service}" if service else ""
    nc = ["--no-cache"] if no_cache else []
    if action == "build":
        return [(f"compose build --pull{' --no-cache' if no_cache else ''}{s}", [*b, "build", "--pull", *nc, *svc])]
    if action == "rebuild":
        # build images and recreate containers from them
        return [
            (f"compose build --pull{' --no-cache' if no_cache else ''}{s}", [*b, "build", "--pull", *nc, *svc]),
            (f"compose up -d --force-recreate --remove-orphans{s}", [*b, "up", "-d", "--force-recreate", "--remove-orphans", *svc]),
        ]
    if action == "cleanup":
        label = f"label=com.docker.compose.project={p.slug}"
        return [
            ("remove stopped containers of project", ["docker", "container", "prune", "-f", "--filter", label]),
            ("remove unused images built for project", ["docker", "image", "prune", "-a", "-f", "--filter", label]),
            ("remove dangling images", ["docker", "image", "prune", "-f"]),
        ]
    if action == "up":
        return [(f"compose up -d{s}", [*b, "up", "-d", "--remove-orphans", *svc])]
    if action == "recreate":
        return [(f"compose up -d --force-recreate{s}", [*b, "up", "-d", "--force-recreate", *svc])]
    if action == "down":
        return [("compose down", [*b, "down", "--remove-orphans"])]
    if action in ("restart", "stop", "start"):
        return [(f"compose {action}{s}", [*b, action, *svc])]
    if action == "pull":
        return [(f"compose pull{s}", [*b, "pull", *svc])]
    if action == "deploy":
        steps: list[Step] = []
        if p.source == "git" and git_ops.is_repo(p):
            steps += git_ops.pull_steps(p)
        steps += [
            ("compose pull --ignore-pull-failures", [*b, "pull", "--ignore-pull-failures"]),
        ]
        if no_cache:
            steps.append(("compose build --pull --no-cache", [*b, "build", "--pull", "--no-cache"]))
        steps.append(("compose up -d --build --remove-orphans", [*b, "up", "-d", "--build", "--remove-orphans"]))
        return steps
    raise ValueError(f"Unknown action {action}")
