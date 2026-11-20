import os
import sys
import tempfile
from pathlib import Path

import pytest

# Isolated SQLite DB + deterministic config, set BEFORE the app is imported.
_tmp = Path(tempfile.mkdtemp()) / "test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp.as_posix()}"
os.environ["OPENAI_API_KEY"] = "sk-test"
os.environ["TWILIO_ACCOUNT_SID"] = "ACtest"
os.environ["TWILIO_AUTH_TOKEN"] = "twilio-test-token"
os.environ["PUBLIC_BASE_URL"] = "https://voice.example.com"
os.environ["TWILIO_VALIDATE_SIGNATURES"] = "true"
os.environ["VOICE_CALLBACK_WORKER_ENABLED"] = "false"
os.environ["QDRANT_URL"] = ""

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.core.db import Base, engine  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402
import app.voice.models  # noqa: E402,F401
import app.leads.models  # noqa: E402,F401
import app.analytics.models  # noqa: E402,F401


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def client():
    return TestClient(fastapi_app)


@pytest.fixture
def tenant(client):
    r = client.post("/v1/tenants", json={"name": "SmileCare Dental", "contact_email": "hi@smile.example"})
    assert r.status_code == 200, r.text
    return r.json()
