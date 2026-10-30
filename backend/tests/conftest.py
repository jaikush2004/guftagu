import os
import tempfile
from pathlib import Path

# ZAROORI: database import hone se PEHLE test database ka address set karo.
# Isse tests ek alag temporary file use karte hain, aapki guftagu.db nahi.
_tmpdir = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = "sqlite:///" + Path(_tmpdir, "test.db").as_posix()

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import main  # noqa: E402
from database import Base, engine  # noqa: E402


@pytest.fixture(autouse=True)
def clean_db():
    """Har test se pehle saari tables saaf karke dobara banao."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    main.manager.users.clear()  # pichle test ke bache hue WebSocket connections bhool jao
    yield


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def make_user(client):
    """Naya user banao aur uska token aur headers wapas do."""

    def _make(name, password="secret123"):
        r = client.post("/api/signup", json={"username": name, "password": password})
        assert r.status_code == 201, r.text
        token = r.json()["token"]
        return {"name": name, "token": token, "headers": {"Authorization": f"Bearer {token}"}}

    return _make


@pytest.fixture
def recv_until():
    """WebSocket se tab tak padho jab tak mangi hui type ka event na aa jaye."""

    def _recv(ws, kind, limit=10):
        for _ in range(limit):
            data = ws.receive_json()
            if data.get("type") == kind:
                return data
        raise AssertionError(f"'{kind}' event nahi aaya")

    return _recv