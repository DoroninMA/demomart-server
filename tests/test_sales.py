from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import pytest

from conftest import auth, give_points, identify, make_cashier, make_customer
from loyalty import sales


@pytest.fixture
def cashier(db):
    return make_cashier(db)


def sale_body(ref=None, *, register="R1", receipt=127, amount=2300, redeem=0):
    return {
        "register_id": register, "receipt_no": receipt, "customer_ref": ref,
        "amount_cents": amount, "redeem_points": redeem,
    }


@pytest.fixture
def purchase(client, db):
    customer = make_customer(client, "u1", name="Anna")
    give_points(db, customer["card_number"], 1355)
    return sale_body(identify(client, db, customer), redeem=500)


def post_sale(client, cashier, body):
    return client.post("/v1/pos/commit", json=body, headers=cashier)


def refund(client, cashier, body):
    return client.post(
        "/v1/pos/refund",
        json={"register_id": body["register_id"], "receipt_no": body["receipt_no"]},
        headers=cashier,
    )


def sale_count(db):
    return db.execute("SELECT COUNT(*) FROM sales").fetchone()[0]


def ledger_count(db):
    return db.execute("SELECT COUNT(*) FROM ledger").fetchone()[0]


def expire(db, body):
    db.execute(
        "UPDATE identifications SET expires_at = '2000-01-01T00:00:00Z' WHERE ref = ?",
        (body["customer_ref"],),
    )


def test_commit_spec_example(client, cashier, purchase):
    response = post_sale(client, cashier, purchase)
    assert response.status_code == 200
    result = response.json()
    assert (result["paid_cents"], result["earned_points"], result["balance"]) == (1800, 18, 873)
    assert "member_id" not in result


def test_commit_retry_is_idempotent(client, db, cashier, purchase):
    before = ledger_count(db)
    first = post_sale(client, cashier, purchase)
    second = post_sale(client, cashier, purchase)
    assert first.status_code == second.status_code == 200
    assert first.json()["sale_id"] == second.json()["sale_id"]
    assert ledger_count(db) == before + 2


def test_concurrent_commit_retries_write_one_sale(client, db, cashier, purchase):
    before = sale_count(db), ledger_count(db)
    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(lambda _: post_sale(client, cashier, purchase), range(2)))
    assert [response.status_code for response in responses] == [200, 200]
    assert responses[0].json()["sale_id"] == responses[1].json()["sale_id"]
    assert (sale_count(db), ledger_count(db)) == (before[0] + 1, before[1] + 2)


def test_commit_retry_after_ref_expired(client, db, cashier, purchase):
    first = post_sale(client, cashier, purchase)
    assert first.status_code == 200
    expire(db, purchase)
    second = post_sale(client, cashier, purchase)
    assert second.status_code == 200
    assert second.json()["sale_id"] == first.json()["sale_id"]


def test_new_commit_with_expired_ref(client, db, cashier, purchase):
    expire(db, purchase)
    response = post_sale(client, cashier, purchase)
    assert response.status_code == 422
    assert response.json()["error"] == "customer_ref_expired"


def test_commit_same_receipt_different_body(client, cashier, purchase):
    assert post_sale(client, cashier, purchase).status_code == 200
    response = post_sale(client, cashier, {**purchase, "amount_cents": 2400})
    assert response.status_code == 409
    assert response.json()["error"] == "sale_conflict"


def test_replay_of_refunded_sale(client, cashier, purchase):
    assert post_sale(client, cashier, purchase).status_code == 200
    assert refund(client, cashier, purchase).status_code == 200
    response = post_sale(client, cashier, purchase)
    assert response.status_code == 200
    assert response.json()["status"] == "refunded"


def test_next_receipt(client, cashier):
    def next_receipt(register):
        response = client.get("/v1/pos/next-receipt", params={"register_id": register}, headers=cashier)
        assert response.status_code == 200
        assert response.json()["register_id"] == register
        return response.json()["next_receipt_no"]

    assert next_receipt("R1") == 1
    assert post_sale(client, cashier, sale_body()).status_code == 200
    assert next_receipt("R1") == 128
    assert next_receipt("R2") == 1


def test_two_registers_same_receipt_no(client, cashier):
    first = post_sale(client, cashier, sale_body(receipt=1))
    second = post_sale(client, cashier, sale_body(register="R2", receipt=1))
    assert first.status_code == second.status_code == 200
    assert first.json()["sale_id"] != second.json()["sale_id"]


def test_balance_spent_between_quote_and_commit(client, db, cashier):
    customer = make_customer(client, "u1")
    give_points(db, customer["card_number"], 600)
    ref = identify(client, db, customer)
    quote = client.post(
        "/v1/pos/quote", json={"customer_ref": ref, "amount_cents": 500, "redeem_points": 500},
        headers=cashier,
    )
    assert quote.status_code == 200
    assert post_sale(client, cashier, sale_body(ref, register="R2", amount=500, redeem=500)).status_code == 200
    before = sale_count(db), ledger_count(db)
    response = post_sale(client, cashier, sale_body(ref, amount=500, redeem=500))
    assert response.status_code == 422
    assert response.json()["error"] == "insufficient_points"
    assert (sale_count(db), ledger_count(db)) == before


def test_refund_reverses_points(client, cashier, purchase):
    assert post_sale(client, cashier, purchase).status_code == 200
    response = refund(client, cashier, purchase)
    assert response.status_code == 200
    assert (response.json()["balance"], response.json()["status"]) == (1355, "refunded")


def test_refund_twice(client, cashier, purchase):
    assert post_sale(client, cashier, purchase).status_code == 200
    assert refund(client, cashier, purchase).status_code == 200
    response = refund(client, cashier, purchase)
    assert response.status_code == 409
    assert response.json()["error"] == "already_refunded"


def test_refund_can_go_negative(client, db, cashier):
    ref = identify(client, db, make_customer(client, "u1"))
    first = sale_body(ref, receipt=1, amount=10_000)
    second = sale_body(ref, receipt=2, amount=100, redeem=100)
    assert post_sale(client, cashier, first).json()["balance"] == 100
    assert post_sale(client, cashier, second).json()["balance"] == 0
    assert refund(client, cashier, first).json()["balance"] == -100


def test_sale_without_member_and_refund(client, db, cashier):
    body = sale_body()
    response = post_sale(client, cashier, body)
    assert response.status_code == 200
    assert response.json()["earned_points"] == 0 and response.json()["balance"] is None
    response = refund(client, cashier, body)
    assert response.status_code == 200
    assert response.json()["status"] == "refunded"
    assert ledger_count(db) == 0


def test_commit_at_past_date(db):
    result = sales.commit(db, "R1", 1, None, 100, 0, at=datetime(2026, 10, 1, 10, tzinfo=timezone.utc))
    assert result.created_at == "2026-10-01T10:00:00Z"


def test_recent_sales_newest_first_with_names(client, db, cashier):
    anna_ref = identify(client, db, make_customer(client, "u1", name="Anna"))
    ben_ref = identify(client, db, make_customer(client, "u2", name="Ben"))
    assert post_sale(client, cashier, sale_body(anna_ref, receipt=10)).status_code == 200
    assert post_sale(client, cashier, sale_body(ben_ref, receipt=2)).status_code == 200
    response = client.get("/v1/pos/sales", params={"register_id": "R1", "limit": 2}, headers=cashier)
    assert response.status_code == 200
    assert [item["display_name"] for item in response.json()] == ["Ben", "Anna"]
    assert all("member_id" not in item for item in response.json())


def test_customer_history(client, cashier, purchase):
    assert post_sale(client, cashier, purchase).status_code == 200
    assert refund(client, cashier, purchase).status_code == 200
    response = client.get("/v1/me/history", params={"limit": 2}, headers=auth("u1"))
    assert response.status_code == 200
    assert [item["kind"] for item in response.json()] == ["refund", "sale"]
    assert [item["points_delta"] for item in response.json()] == [482, -482]

def test_history_breakdown(client, cashier, purchase):
    sale = post_sale(client, cashier, purchase)
    assert sale.status_code == 200
    sale_id = sale.json()["sale_id"]
    assert refund(client, cashier, purchase).status_code == 200

    response = client.get("/v1/me/history", headers=auth("u1"))

    assert response.status_code == 200
    items = {item["kind"]: item for item in response.json() if item["sale_id"] == sale_id}
    fields = ("earned_points", "redeemed_points", "points_delta")
    assert tuple(items["sale"][field] for field in fields) == (18, 500, -482)
    assert tuple(items["refund"][field] for field in fields) == (-18, -500, 482)


def test_history_pages_cover_everything_once(client, db):
    make_customer(client, "u1")
    member_id = db.execute("SELECT id FROM members WHERE firebase_uid = 'u1'").fetchone()[0]
    noon = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    for receipt in range(1, 8):
        # receipts 5..7 share one timestamp to exercise the tie-breaks
        at = noon.replace(hour=12 + min(receipt, 5))
        sales.commit(db, "R1", receipt, member_id, 1000, 0, at=at)
    sales.refund(db, "R1", 6)

    full = client.get("/v1/me/history", params={"limit": 100}, headers=auth("u1")).json()
    pages, params = [], {"limit": 3}
    while page := client.get("/v1/me/history", params=params, headers=auth("u1")).json():
        pages += page
        last = page[-1]
        params = {"limit": 3, "before_at": last["at"], "before_id": last["sale_id"], "before_kind": last["kind"]}
    assert len(full) == 8
    assert pages == full


def test_history_cursor_must_be_complete(client):
    make_customer(client, "u1")
    response = client.get("/v1/me/history", params={"before_id": 3}, headers=auth("u1"))
    assert response.status_code == 422


def test_recent_sales_pages_cover_everything_once(client, db, cashier):
    noon = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    for receipt in range(1, 8):
        # receipts 5..7 share one timestamp to exercise the tie-break
        sales.commit(db, "R1", receipt, None, 1000, 0, at=noon.replace(hour=12 + min(receipt, 5)))
    full = client.get("/v1/pos/sales", params={"register_id": "R1", "limit": 100}, headers=cashier).json()
    pages, params = [], {"register_id": "R1", "limit": 3}
    while page := client.get("/v1/pos/sales", params=params, headers=cashier).json():
        pages += page
        params = {**params, "before_at": page[-1]["created_at"], "before_id": page[-1]["sale_id"]}
    assert [sale["receipt_no"] for sale in full] == [7, 6, 5, 4, 3, 2, 1]
    assert pages == full


def test_recent_sales_cursor_must_be_complete(client, cashier):
    response = client.get("/v1/pos/sales", params={"register_id": "R1", "before_id": 3}, headers=cashier)
    assert response.status_code == 422
