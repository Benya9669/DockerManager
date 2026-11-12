import base64
import os
import subprocess
from pathlib import Path

from .models import Project
from .security import decrypt

GIT_ENV = {
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_SSH_COMMAND": "ssh -o StrictHostKeyChecking=accept-new -o BatchMode=yes",
}


class GitError(Exception):
    pass


def git_args(p: Project) -> list[str]:
    """Base git command with credentials passed via header (never stored in .git/config)."""
    args = ["git", "-c", "credential.helper="]
    token = decrypt(p.git_token_enc)
    if token and p.repo_url.startswith("http"):
        user = p.git_username or "oauth2"
        basic = base64.b64encode(f"{user}:{token}".encode()).decode()
        args += ["-c", f"http.extraHeader=Authorization: Basic {basic}"]
    return args


def is_repo(p: Project) -> bool:
    return (Path(p.path) / ".git").exists()


def run(p: Project, *args: str, timeout: int = 60) -> str:
    try:
        r = subprocess.run(
            [*git_args(p), *args], cwd=p.path, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout, env={**os.environ, **GIT_ENV},
        )
    except subprocess.TimeoutExpired:
        raise GitError("git command timed out")
    if r.returncode != 0:
        raise GitError((r.stderr or r.stdout).strip() or f"git exited with {r.returncode}")
    return r.stdout


def status(p: Project) -> dict:
    if not is_repo(p):
        return {"is_repo": False}
    branch = run(p, "rev-parse", "--abbrev-ref", "HEAD").strip()
    commit = {}
    try:
        h, sh, subj, author, date = run(p, "log", "-1", "--format=%H%x1f%h%x1f%s%x1f%an%x1f%aI").strip().split("\x1f")
        commit = {"hash": h, "short": sh, "subject": subj, "author": author, "date": date}
    except (GitError, ValueError):
        pass
    changes = [line for line in run(p, "status", "--porcelain").splitlines() if line.strip()]
    ahead = behind = None
    upstream = None
    try:
        upstream = run(p, "rev-parse", "--abbrev-ref", "@{u}").strip()
        left, right = run(p, "rev-list", "--left-right", "--count", "HEAD...@{u}").split()
        ahead, behind = int(left), int(right)
    except GitError:
        pass
    return {
        "is_repo": True, "branch": branch, "commit": commit, "changes": changes,
        "upstream": upstream, "ahead": ahead, "behind": behind,
    }


def fetch(p: Project) -> None:
    run(p, "fetch", "--prune", "origin", timeout=120)


def branches(p: Project) -> dict:
    local = [b for b in run(p, "branch", "--format=%(refname:short)").splitlines() if b]
    remote = [
        b.removeprefix("origin/")
        for b in run(p, "branch", "-r", "--format=%(refname:short)").splitlines()
        if b and b != "origin/HEAD" and b.startswith("origin/") and b != "origin"
    ]
    return {"local": local, "remote": sorted(set(remote))}


def log(p: Project, n: int = 50) -> list[dict]:
    out = run(p, "log", f"-{n}", "--format=%H%x1f%h%x1f%s%x1f%an%x1f%aI")
    res = []
    for line in out.splitlines():
        parts = line.split("\x1f")
        if len(parts) == 5:
            res.append(dict(zip(["hash", "short", "subject", "author", "date"], parts)))
    return res


def clone_steps(p: Project) -> list[tuple[str, list[str]]]:
    args = [*git_args(p), "clone", "--progress"]
    if p.branch:
        args += ["--branch", p.branch]
    args += [p.repo_url, p.path]
    return [(f"git clone {p.repo_url} ({p.branch or 'default branch'})", args)]


def pull_steps(p: Project) -> list[tuple[str, list[str]]]:
    return [("git pull --ff-only", [*git_args(p), "pull", "--ff-only", "--progress"])]


def checkout_steps(p: Project, branch: str) -> list[tuple[str, list[str]]]:
    return [
        ("git fetch origin", [*git_args(p), "fetch", "--prune", "origin"]),
        (f"git checkout {branch}", [*git_args(p), "checkout", branch]),
        ("git pull --ff-only", [*git_args(p), "pull", "--ff-only"]),
    ]


def reset_steps(p: Project) -> list[tuple[str, list[str]]]:
    return [
        ("git fetch origin", [*git_args(p), "fetch", "--prune", "origin"]),
        ("git reset --hard @{u}", [*git_args(p), "reset", "--hard", "@{u}"]),
    ]
