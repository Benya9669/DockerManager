import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def env(name: str, default=None):
    """Env var value; empty/blank strings count as unset (compose passes `${X:-}` as "")."""
    v = os.getenv(name)
    if v is None or not v.strip():
        return default
    return v.strip()


def _bool(name: str, default: bool) -> bool:
    v = env(name)
    if v is None:
        return default
    return v.lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    v = env(name)
    try:
        return int(v) if v is not None else default
    except ValueError:
        return default


class Settings:
    def __init__(self) -> None:
        self.data_dir = Path(env("DM_DATA_DIR", BASE_DIR / "data")).resolve()
        self.projects_dir = Path(env("DM_PROJECTS_DIR", self.data_dir / "projects")).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.projects_dir.mkdir(parents=True, exist_ok=True)

        self.database_url = env("DM_DATABASE_URL", f"sqlite:///{(self.data_dir / 'dm.db').as_posix()}")
        self.secret_key = env("DM_SECRET_KEY") or self._load_or_create_secret()
        self.admin_username = env("DM_ADMIN_USERNAME", "admin")
        self.admin_password = env("DM_ADMIN_PASSWORD", "")
        self.token_ttl_minutes = _int("DM_TOKEN_TTL_MINUTES", 720)
        # Allow admins to register existing folders on the host as projects
        self.allow_local_paths = _bool("DM_ALLOW_LOCAL_PATHS", True)
        # Public base URL, used to show webhook URLs in the UI
        self.public_url = env("DM_PUBLIC_URL", "").rstrip("/")
        self.static_dir = Path(env("DM_STATIC_DIR", BASE_DIR / "frontend" / "dist")).resolve()
        # Where SSH private keys for git live (selectable per project)
        self.ssh_dir = Path(env("DM_SSH_KEYS_DIR", Path.home() / ".ssh")).resolve()
        self.max_file_size = _int("DM_MAX_FILE_SIZE", 2 * 1024 * 1024)
        # Scheduled cleanup
        self.auto_prune_hours = float(env("DM_AUTO_PRUNE_INTERVAL_HOURS", "0") or 0)
        self.auto_prune_older_than = _int("DM_AUTO_PRUNE_OLDER_THAN_HOURS", 72)
        # Backups
        self.backup_dir = Path(env("DM_BACKUP_DIR", self.data_dir / "backups")).resolve()
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.backup_keep = _int("DM_BACKUP_KEEP", 7)  # archives kept per target
        self.backup_interval_hours = float(env("DM_BACKUP_INTERVAL_HOURS", "0") or 0)
        self.backup_stop_containers = _bool("DM_BACKUP_STOP_CONTAINERS", False)
        # Self-update
        self.update_repo = env("DM_UPDATE_REPO", "Benya9669/DockerManager")  # GitHub owner/repo with releases
        self.update_token = env("DM_UPDATE_GITHUB_TOKEN", "")  # needed only for private repos
        self.update_mode = env("DM_UPDATE_MODE", "git")  # git: git pull + rebuild; image: pull image from GHCR
        self.update_ssh_key = env("DM_UPDATE_SSH_KEY", "")  # key file name in the SSH dir for git pull of the panel repo
        self.auto_update = _bool("DM_AUTO_UPDATE", False)
        self.update_check_hours = float(env("DM_UPDATE_CHECK_HOURS", "6") or 6)

    def _load_or_create_secret(self) -> str:
        p = self.data_dir / "secret.key"
        if p.exists():
            return p.read_text().strip()
        key = secrets.token_urlsafe(48)
        p.write_text(key)
        return key


settings = Settings()
