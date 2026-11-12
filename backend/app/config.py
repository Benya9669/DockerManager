import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


class Settings:
    def __init__(self) -> None:
        self.data_dir = Path(os.getenv("DM_DATA_DIR", BASE_DIR / "data")).resolve()
        self.projects_dir = Path(os.getenv("DM_PROJECTS_DIR", self.data_dir / "projects")).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.projects_dir.mkdir(parents=True, exist_ok=True)

        self.database_url = os.getenv("DM_DATABASE_URL", f"sqlite:///{(self.data_dir / 'dm.db').as_posix()}")
        self.secret_key = os.getenv("DM_SECRET_KEY") or self._load_or_create_secret()
        self.admin_username = os.getenv("DM_ADMIN_USERNAME", "admin")
        self.admin_password = os.getenv("DM_ADMIN_PASSWORD", "")
        self.token_ttl_minutes = int(os.getenv("DM_TOKEN_TTL_MINUTES", "720"))
        # Allow admins to register existing folders on the host as projects
        self.allow_local_paths = _bool("DM_ALLOW_LOCAL_PATHS", True)
        # Public base URL, used to show webhook URLs in the UI
        self.public_url = os.getenv("DM_PUBLIC_URL", "").rstrip("/")
        self.static_dir = Path(os.getenv("DM_STATIC_DIR", BASE_DIR / "frontend" / "dist")).resolve()
        self.max_file_size = int(os.getenv("DM_MAX_FILE_SIZE", str(2 * 1024 * 1024)))

    def _load_or_create_secret(self) -> str:
        p = self.data_dir / "secret.key"
        if p.exists():
            return p.read_text().strip()
        key = secrets.token_urlsafe(48)
        p.write_text(key)
        return key


settings = Settings()
