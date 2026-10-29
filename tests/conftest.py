from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from loyalty.config import Settings
from loyalty.db import connect
from loyalty.main import create_app


@pytest.fixture
def settings(tmp_path):
    return Settings(str(tmp_path / "t.db"), "fake", None)


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def db(client, settings):
    with closing(connect(settings.database_path)) as conn:
        yield conn


def auth(uid, email="x@demo.test", name="X"):
    return {"Authorization": f"Bearer fake:{uid}:{email}:{name}"}
