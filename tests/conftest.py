import time
from contextlib import ExitStack, closing

import pytest
from fastapi.testclient import TestClient

from loyalty.config import Settings
from loyalty.db import connect
from loyalty.main import create_app
from loyalty.tokens import make_token


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



def make_cashier(db):
    db.execute(
        """
        INSERT INTO members (firebase_uid, email, display_name, card_number, totp_secret, role, created_at)
        VALUES ('cashier1', 'cashier@demo.test', 'Cashier', '10000000', 'TEST', 'cashier', '2026-11-09T12:00:00Z')
        ON CONFLICT(firebase_uid) DO NOTHING
        """
    )
    return auth("cashier1", "cashier@demo.test", "Cashier")


def make_customer(client, uid, email=None, name="Customer"):
    response = client.post("/v1/me/session", headers=auth(uid, email or f"{uid}@demo.test", name))
    assert response.status_code == 200, response.text
    return response.json()


def give_points(db, card_number, points):
    member_id = db.execute("SELECT id FROM members WHERE card_number = ?", (card_number,)).fetchone()[0]
    at = "2026-10-01T12:00:00Z"
    sale_id = db.execute(
        """
        INSERT INTO sales (
            register_id, receipt_no, member_id, amount_cents, redeem_points, paid_cents,
            earned_points, status, created_at
        )
        SELECT 'TEST', COALESCE(MAX(receipt_no), 0) + 1, ?, 0, 0, 0, ?, 'committed', ?
        FROM sales WHERE register_id = 'TEST'
        """,
        (member_id, points, at),
    ).lastrowid
    db.execute(
        "INSERT INTO ledger (member_id, sale_id, kind, points, created_at) VALUES (?, ?, 'earn', ?, ?)",
        (member_id, sale_id, points, at),
    )


def identify(client, db, customer):
    token = make_token(customer["card_number"], customer["totp_secret"], time.time())
    response = client.post("/v1/pos/identify", json={"token": token}, headers=make_cashier(db))
    assert response.status_code == 200, response.text
    return response.json()["customer_ref"]

@pytest.fixture
def client_with(settings):
    with ExitStack() as stack:
        def make_client(*listeners):
            return stack.enter_context(TestClient(create_app(settings, listeners=list(listeners))))

        yield make_client
