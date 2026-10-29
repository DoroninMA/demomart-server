import time

import pytest

from conftest import auth, give_points, identify, make_cashier, make_customer
from loyalty.tokens import make_token


def test_identify_with_fresh_token(client, db):
    customer = make_customer(client, "u1", name="Anna")
    token = make_token(customer["card_number"], customer["totp_secret"], time.time())
    response = client.post("/v1/pos/identify", json={"token": token}, headers=make_cashier(db))
    assert response.status_code == 200
    body = response.json()
    assert body["display_name"] == "Anna"
    assert body["customer_ref"] and "member_id" not in body


def test_identify_requires_cashier(client):
    make_customer(client, "u1")
    response = client.post("/v1/pos/identify", json={"token": "unused"}, headers=auth("u1", "u1@demo.test"))
    assert response.status_code == 403
    assert response.json()["error"] == "forbidden"


def test_identify_expired_token(client, db):
    customer = make_customer(client, "u1")
    token = make_token(customer["card_number"], customer["totp_secret"], time.time() - 299)
    response = client.post("/v1/pos/identify", json={"token": token}, headers=make_cashier(db))
    assert response.status_code == 422
    assert response.json()["error"] == "token_expired"


def test_identify_unknown_card(client, db):
    response = client.post(
        "/v1/pos/identify", json={"token": "DM1:99999999:000000"}, headers=make_cashier(db)
    )
    assert response.status_code == 404
    assert response.json()["error"] == "member_not_found"


def request_quote(client, db, ref, amount=2300, redeem=0):
    return client.post(
        "/v1/pos/quote",
        json={"customer_ref": ref, "amount_cents": amount, "redeem_points": redeem},
        headers=make_cashier(db),
    )


def test_quote_matches_rules(client, db):
    customer = make_customer(client, "u1")
    give_points(db, customer["card_number"], 1355)
    response = request_quote(client, db, identify(client, db, customer), redeem=500)
    assert response.status_code == 200
    assert response.json() == {
        "amount_cents": 2300, "redeem_points": 500, "discount_cents": 500,
        "paid_cents": 1800, "earn_points": 18, "max_redeem_points": 1300,
    }


def test_quote_without_customer(client, db):
    response = request_quote(client, db, None)
    assert response.status_code == 200
    assert response.json()["paid_cents"] == 2300
    assert response.json()["earn_points"] == 0


@pytest.mark.parametrize("amount", [0, -1, 1_000_001])
def test_quote_invalid_amount(client, db, amount):
    response = request_quote(client, db, None, amount=amount)
    assert response.status_code == 422
    assert response.json()["error"] == "amount_invalid"
    assert db.execute("SELECT COUNT(*) FROM sales").fetchone()[0] == 0


def test_quote_unknown_ref(client, db):
    response = request_quote(client, db, "nope")
    assert response.status_code == 422
    assert response.json()["error"] == "customer_ref_invalid"


def test_quote_expired_ref(client, db):
    ref = identify(client, db, make_customer(client, "u1"))
    db.execute("UPDATE identifications SET expires_at = '2000-01-01T00:00:00Z' WHERE ref = ?", (ref,))
    response = request_quote(client, db, ref)
    assert response.status_code == 422
    assert response.json()["error"] == "customer_ref_expired"
