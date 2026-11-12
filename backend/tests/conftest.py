import os
import sys
import tempfile
from pathlib import Path

import pytest

_tmp = Path(tempfile.mkdtemp(prefix="dm-test-"))
os.environ["DM_DATA_DIR"] = str(_tmp / "data")
os.environ["DM_ADMIN_PASSWORD"] = "testpass123"
os.environ["DM_SSH_KEYS_DIR"] = str(_tmp / "ssh")
os.environ["DM_UPDATE_CHECK_HOURS"] = "1000"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def auth(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "testpass123"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="session")
def tmp_root():
    return _tmp
