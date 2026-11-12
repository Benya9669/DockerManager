"""Private registry credentials -> docker CLI config (DOCKER_CONFIG) used by all compose/pull commands."""
import base64
import json
import os
import subprocess
import tempfile

from sqlalchemy import select

from .config import settings
from .db import SessionLocal
from .models import Registry
from .security import decrypt

DOCKER_CONFIG_DIR = settings.data_dir / "docker-config"


def activate() -> None:
    """Point every docker CLI call of this process (and its children) to our config dir."""
    DOCKER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    os.environ["DOCKER_CONFIG"] = str(DOCKER_CONFIG_DIR)
    write_config()


def write_config() -> None:
    db = SessionLocal()
    try:
        auths = {}
        for r in db.scalars(select(Registry)):
            token = base64.b64encode(f"{r.username}:{decrypt(r.password_enc)}".encode()).decode()
            auths[r.url] = {"auth": token}
    finally:
        db.close()
    path = DOCKER_CONFIG_DIR / "config.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"auths": auths}, indent=2))
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)


def normalize_url(url: str) -> str:
    u = url.strip().removeprefix("https://").removeprefix("http://").rstrip("/")
    return "https://index.docker.io/v1/" if u in ("docker.io", "index.docker.io", "hub.docker.com") else u


def test_login(url: str, username: str, password: str) -> tuple[bool, str]:
    """Run `docker login` in a throwaway config dir to verify credentials."""
    with tempfile.TemporaryDirectory() as d:
        env = {**os.environ, "DOCKER_CONFIG": d}
        try:
            r = subprocess.run(
                ["docker", "login", url, "-u", username, "--password-stdin"], input=password,
                capture_output=True, text=True, timeout=30, env=env,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            return False, str(e)
    out = (r.stdout + r.stderr).strip()
    return r.returncode == 0, out
