import pytest
from fastapi.testclient import TestClient

from loyalty.config import Settings
from loyalty.main import create_app


@pytest.fixture
def client(tmp_path):
    settings = Settings(str(tmp_path / "t.db"), "fake", None)
    with TestClient(create_app(settings)) as test_client:
        yield test_client
