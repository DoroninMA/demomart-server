import json
from types import SimpleNamespace

import pytest
from requests import Timeout

from loyalty.wallet_api import GoogleWalletApi, WalletConflict, WalletError
from test_wallet_jwt import rsa_sa_info


class FakeSession:
    def __init__(self):
        self.status = 200
        self.calls = []

    def request(self, method, url, json=None, timeout=None):
        self.calls.append((method, url, json, timeout))
        return SimpleNamespace(status_code=self.status, text="API response", json=lambda: {"id": "I.object"})


@pytest.fixture
def fake_session(tmp_path, rsa_sa_info):
    key = tmp_path / "test-sa.json"
    key.write_text(json.dumps({key: value for key, value in rsa_sa_info.items() if key != "_public_pem"}))
    session = FakeSession()
    return GoogleWalletApi(str(key), session_factory=lambda credentials: session), session


def test_api_get_404_is_none(fake_session):
    api, session = fake_session
    session.status = 404
    assert api.get_object("I.object") is None


def test_api_insert_409_raises_conflict(fake_session):
    api, session = fake_session
    session.status = 409
    with pytest.raises(WalletConflict):
        api.insert_class({"id": "I.class"})


def test_api_patch_sends_body(fake_session):
    api, session = fake_session
    api.patch_object("I.object", {"state": "ACTIVE"})
    assert session.calls == [("PATCH", "https://walletobjects.googleapis.com/walletobjects/v1/loyaltyObject/I.object",
                              {"state": "ACTIVE"}, 10)]


def test_api_5xx_raises_wallet_error(fake_session):
    api, session = fake_session
    session.status = 503
    with pytest.raises(WalletError) as exc:
        api.get_class("I.class")
    assert exc.value.status == 503


def test_api_timeout_raises_wallet_error(fake_session, monkeypatch):
    api, session = fake_session

    def fail(*args, **kwargs):
        raise Timeout()

    monkeypatch.setattr(session, "request", fail)
    with pytest.raises(WalletError) as exc:
        api.get_class("I.class")
    assert exc.value.status == 503
