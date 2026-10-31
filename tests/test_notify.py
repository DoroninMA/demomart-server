from types import SimpleNamespace

import pytest

from conftest import auth, give_points, identify, make_cashier, make_customer
from loyalty.notify import FcmNotifier
from test_sales import post_sale, refund, sale_body


class Spy:
    def __init__(self, *, fail=False):
        self.calls = []
        self.fail = fail

    def balance_changed(self, member, balance, sale):
        self.calls.append((member["display_name"], balance, sale.status))
        if self.fail:
            raise RuntimeError("test listener failure")


@pytest.fixture
def purchase_setup(client_with, db):
    def setup(*listeners):
        client = client_with(*listeners)
        customer = make_customer(client, "u1", name="Anna")
        give_points(db, customer["card_number"], 1355)
        body = sale_body(identify(client, db, customer), redeem=500)
        return client, make_cashier(db), body

    return setup


def test_listener_called_on_commit_and_refund(purchase_setup):
    listener = Spy()
    client, cashier, body = purchase_setup(listener)
    assert post_sale(client, cashier, body).status_code == 200
    assert refund(client, cashier, body).status_code == 200
    assert listener.calls == [("Anna", 873, "committed"), ("Anna", 1355, "refunded")]


def test_listener_not_called_on_replay(purchase_setup):
    listener = Spy()
    client, cashier, body = purchase_setup(listener)
    assert post_sale(client, cashier, body).status_code == 200
    assert post_sale(client, cashier, body).status_code == 200
    assert listener.calls == [("Anna", 873, "committed")]


def test_listener_not_called_when_ledger_unchanged(purchase_setup):
    listener = Spy()
    client, cashier, body = purchase_setup(listener)
    body.update(amount_cents=99, redeem_points=0)
    assert post_sale(client, cashier, body).status_code == 200
    assert refund(client, cashier, body).status_code == 200
    assert not listener.calls


def test_listener_failure_does_not_break_sale(purchase_setup, db):
    failing, other = Spy(fail=True), Spy()
    client, cashier, body = purchase_setup(failing, other)
    response = post_sale(client, cashier, body)
    assert response.status_code == 200
    assert db.execute("SELECT status FROM sales WHERE id = ?", (response.json()["sale_id"],)).fetchone()[0] == "committed"
    assert other.calls == [("Anna", 873, "committed")]


@pytest.mark.parametrize("status,balance,delta", [("committed", 873, "-482"), ("refunded", 1355, "482")])
def test_fcm_notifier_sends_data_message(status, balance, delta):
    sent = []
    sale = SimpleNamespace(sale_id=12, status=status, earned_points=18, redeem_points=500)
    FcmNotifier(send=sent.append).balance_changed({"fcm_token": "device-token"}, balance, sale)
    assert len(sent) == 1
    assert sent[0].notification is None
    assert sent[0].token == "device-token"
    assert sent[0].data == {
        "type": "balance_changed", "balance": str(balance), "sale_id": "12", "delta": delta,
    }


def test_fcm_notifier_skips_without_token():
    sent = []
    FcmNotifier(send=sent.append).balance_changed({"fcm_token": None}, 0, None)
    assert not sent


def test_put_fcm_token(client, db):
    headers = auth("u1")
    assert client.post("/v1/me/session", headers=headers).status_code == 200
    response = client.put("/v1/me/fcm-token", json={"token": "device-token"}, headers=headers)
    assert response.status_code == 204 and response.content == b""
    assert db.execute("SELECT fcm_token FROM members WHERE firebase_uid = 'u1'").fetchone()[0] == "device-token"
