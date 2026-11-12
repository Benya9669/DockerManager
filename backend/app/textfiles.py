"""Plain-text downloads (logs, job output) with optional line filtering."""
import re
from datetime import datetime

from fastapi.responses import Response

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def text_download(text: str, name: str, grep: str | None = None) -> Response:
    text = ANSI.sub("", text).replace("\r\n", "\n")
    if grep:
        needle = grep.lower()
        text = "\n".join(line for line in text.split("\n") if needle in line.lower()) + "\n"
    safe = re.sub(r"[^\w.-]+", "_", name) or "log"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Response(
        content=text.encode("utf-8"), media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{safe}-{stamp}.log"'},
    )
