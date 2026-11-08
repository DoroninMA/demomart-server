from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, closing
from dataclasses import replace
from threading import Event

import pytest
from fastapi.testclient import TestClient

from conftest import auth, give_points, identify, make_cashier, make_customer
from loyalty.config import WalletSettings
from loyalty.db import connect
from loyalty.main import create_app
from loyalty.wallet_api import WalletConflict, WalletError
from loyalty.wallet_payloads import points_patch
from loyalty.wallet_service import WalletService
from test_wallet_jwt import rsa_sa_info


class FakeWalletApi:
    def __init__(self):
        self.classes = {}
        self.objects = {}
        self.calls = []

    def get_class(self, id):
        return self.classes.get(id)

    def insert_class(self, body):
        self.calls.append(("insert_class", body))
        self.classes[body["id"]] = body

    def patch_class(self, id, body):
        self.calls.append(("patch_class", body))
        self.classes[id].update(body)

    def get_object(self, id):
        return self.objects.get(id)

    def insert_object(self, body):
        self.calls.append(("insert_object", body))
        self.objects[body["id"]] = body.copy()

    def patch_object(self, id, body):
        self.calls.append(("patch_object", body))
        self.objects[id].update(body)


class InlineExecutor:
    def submit(self, fn, *args):
        fn(*args)

    def shutdown(self, **kwargs):
        pass


@pytest.fixture
def wallet_env(settings, rsa_sa_info, monkeypatch):
    with ExitStack() as stack:
        def start(mode="rotating", inline=True):
            if inline:
                monkeypatch.setattr("loyalty.main.ThreadPoolExecutor", lambda **_: InlineExecutor())
            wallet = WalletSettings(issuer_id="123", logo_url="https://example.test/logo.png", barcode_mode=mode)
            api = FakeWalletApi()
            service = WalletService(wallet, api, rsa_sa_info)
            app = create_app(replace(settings, wallet=wallet), wallet=service)
            client = stack.enter_context(TestClient(app))
            db = stack.enter_context(closing(connect(settings.database_path)))
            customer = make_customer(client, "anna", name="Anna")
            give_points(db, customer["card_number"], 1355)
            return client, db, customer, api
        yield start


def save(client):
    return client.post("/v1/me/wallet/save", headers=auth("anna"))


def commit(client, db, customer):
    return client.post("/v1/pos/commit", headers=make_cashier(db), json={
        "customer_ref": identify(client, db, customer),
        "register_id": "R1", "receipt_no": 1, "amount_cents": 2300, "redeem_points": 500,
    })


def test_save_creates_class_and_object(wallet_env):
    client, db, customer, api = wallet_env()
    assert client.get("/v1/me/wallet", headers=auth("anna")).json() == {"enabled": True}
    result = save(client)
    assert result.status_code == 200
    assert result.json()["save_url"] == "https://pay.google.com/gp/v/save/" + result.json()["jwt"]
    assert len(api.classes) == 1
    obj = api.objects[f"123.member_{customer['card_number']}"]
    assert obj["loyaltyPoints"]["balance"]["int"] == 1355
    assert db.execute("SELECT wallet_object_created FROM members WHERE firebase_uid='anna'").fetchone()[0] == 1


def test_save_twice_no_duplicate(wallet_env):
    client, _, _, api = wallet_env()
    assert save(client).status_code == 200
    assert save(client).status_code == 200
    assert [call for call, _ in api.calls] == ["insert_class", "insert_object", "patch_object"]
    assert len(api.objects) == 1


def test_save_after_balance_change_has_current_balance(wallet_env):
    client, db, customer, api = wallet_env()
    assert save(client).status_code == 200
    give_points(db, customer["card_number"], 5)
    assert save(client).status_code == 200
    assert api.calls[-1][1]["loyaltyPoints"]["balance"]["int"] == 1360


def test_static_mode_creates_wallet_code(wallet_env):
    client, db, customer, api = wallet_env(mode="static")
    assert save(client).status_code == 200
    code = db.execute("SELECT wallet_code FROM members WHERE firebase_uid='anna'").fetchone()[0]
    assert len(code) == 10
    assert next(iter(api.objects.values()))["barcode"]["value"] == f"DMW1:{customer['card_number']}:{code}"
    assert save(client).status_code == 200
    assert db.execute("SELECT wallet_code FROM members WHERE firebase_uid='anna'").fetchone()[0] == code


def test_updater_patches_after_commit_and_refund(wallet_env):
    client, db, customer, api = wallet_env()
    assert save(client).status_code == 200
    assert commit(client, db, customer).status_code == 200
    assert api.calls[-1] == ("patch_object", points_patch(873))
    refund = client.post("/v1/pos/refund", headers=make_cashier(db),
                         json={"register_id": "R1", "receipt_no": 1})
    assert refund.status_code == 200
    assert api.calls[-1] == ("patch_object", points_patch(1355))


def test_updater_skips_members_without_object(wallet_env):
    client, db, customer, api = wallet_env()
    assert commit(client, db, customer).status_code == 200
    assert api.calls == []


def test_slow_google_does_not_block_commit(wallet_env, monkeypatch):
    client, db, customer, api = wallet_env(inline=False)
    assert save(client).status_code == 200
    started, release = Event(), Event()
    patch = api.patch_object

    def slow(*args):
        started.set()
        assert release.wait(5)
        patch(*args)

    monkeypatch.setattr(api, "patch_object", slow)
    with ThreadPoolExecutor() as pool:
        try:
            sale = pool.submit(commit, client, db, customer)
            assert started.wait(2)
            assert sale.result(timeout=0.5).status_code == 200
        finally:
            release.set()


def test_slow_save_does_not_lock_db(wallet_env, monkeypatch):
    client, db, customer, api = wallet_env()
    started, release = Event(), Event()
    insert = api.insert_object

    def slow(body):
        started.set()
        assert release.wait(5)
        insert(body)

    monkeypatch.setattr(api, "insert_object", slow)
    with ThreadPoolExecutor() as pool:
        saving = pool.submit(save, client)
        try:
            assert started.wait(2)
            assert pool.submit(commit, client, db, customer).result(timeout=0.5).status_code == 200
        finally:
            release.set()
        assert saving.result().status_code == 200
    assert next(iter(api.objects.values()))["loyaltyPoints"]["balance"]["int"] == 873


def test_concurrent_first_saves_create_class_once(wallet_env):
    client, _, _, api = wallet_env()
    with ThreadPoolExecutor() as pool:
        first = pool.submit(save, client)
        second = pool.submit(save, client)
        assert first.result().status_code == second.result().status_code == 200
    assert [call for call, _ in api.calls].count("insert_class") == 1
    assert [call for call, _ in api.calls].count("insert_object") == 1


def test_insert_class_409_is_ok(wallet_env, monkeypatch):
    client, _, _, api = wallet_env()

    def exists(body):
        raise WalletConflict(409, "already exists")

    monkeypatch.setattr(api, "insert_class", exists)
    assert save(client).status_code == 200


def google_down(*args):
    raise WalletError(503, "Unavailable")


def test_google_error_does_not_break_commit(wallet_env, monkeypatch):
    client, db, customer, api = wallet_env()
    assert save(client).status_code == 200
    monkeypatch.setattr(api, "patch_object", google_down)
    assert commit(client, db, customer).status_code == 200


def test_wallet_disabled(client):
    make_customer(client, "anna")
    assert client.get("/v1/me/wallet", headers=auth("anna")).json() == {"enabled": False}
    response = save(client)
    assert response.status_code == 404
    assert response.json()["error"] == "wallet_disabled"


def test_google_down_on_save(wallet_env, monkeypatch):
    client, _, _, api = wallet_env()
    monkeypatch.setattr(api, "insert_object", google_down)
    response = save(client)
    assert response.status_code == 502
    assert response.json()["error"] == "wallet_unavailable"
