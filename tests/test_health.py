from loyalty.config import Settings


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_default_auth_mode_is_firebase(monkeypatch):
    monkeypatch.delenv("AUTH_MODE", raising=False)
    assert Settings.from_env().auth_mode == "firebase"
