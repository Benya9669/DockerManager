import os
import re
from pathlib import Path


def _read() -> str:
    v = (os.getenv("DM_VERSION") or "").strip()
    if v:
        return v
    f = Path(__file__).resolve().parents[2] / "VERSION"  # repo root, or /app in the image
    if f.is_file():
        return f.read_text().strip()
    return "0.0.0-dev"


VERSION = _read()
GIT_SHA = (os.getenv("DM_GIT_SHA") or "").strip()


def parse(v: str | None) -> tuple[int, ...]:
    nums = re.findall(r"\d+", v or "")
    return tuple(int(x) for x in nums[:3]) if nums else ()


def is_newer(candidate: str | None, current: str = VERSION) -> bool:
    return bool(candidate) and parse(candidate) > parse(current)
