from datetime import datetime, timedelta, timezone

from conftest import auth
from loyalty.seed import run_seed

EXPECTED = {"Anna K.": 1355, "Ben T.": 240, "Chloe M.": 0}


def seed(db, google_email=None):
    return run_seed(db, password=None, google_email=google_email, create_firebase_users=False)


def test_seed_balances(db):
    assert seed(db) == EXPECTED


def test_seed_with_google_email(db):
    assert seed(db, "google@demo.test") == {**EXPECTED, "Demo User": 860}
    row = db.execute("SELECT firebase_uid FROM members WHERE email = 'google@demo.test'").fetchone()
    assert row[0] is None


def test_seed_is_idempotent(db):
    first = seed(db)
    members_before = db.execute("SELECT COUNT(*) FROM members").fetchone()[0]
    sales_before = db.execute("SELECT COUNT(*) FROM sales").fetchone()[0]
    ledger_before = db.execute("SELECT COUNT(*) FROM ledger").fetchone()[0]
    assert seed(db) == first
    assert db.execute("SELECT COUNT(*) FROM members").fetchone()[0] == members_before
    assert db.execute("SELECT COUNT(*) FROM sales").fetchone()[0] == sales_before
    assert db.execute("SELECT COUNT(*) FROM ledger").fetchone()[0] == ledger_before


def test_seed_history_spans_days(db):
    seed(db)
    rows = db.execute(
        """
        SELECT sales.created_at, sales.status
        FROM sales JOIN members ON sales.member_id = members.id
        WHERE members.email = 'anna@demo.test'
        """
    ).fetchall()
    dates = [datetime.fromisoformat(row["created_at"]) for row in rows]
    now = datetime.now(timezone.utc)
    assert all(now - timedelta(days=30) <= date <= now for date in dates)
    assert len({date.date() for date in dates}) >= 3
    assert sum(row["status"] == "refunded" for row in rows) == 1


def test_seed_preserves_google_link_on_retry(client, db):
    seed(db, "google@demo.test")
    headers = auth("google-uid", "google@demo.test")
    session = client.post("/v1/me/session", headers=headers)
    assert session.status_code == 200 and session.json()["balance"] == 860
    assert seed(db, "google@demo.test")["Demo User"] == 860
    assert client.get("/v1/me", headers=headers).json()["card_number"] == session.json()["card_number"]


def test_seed_cashier_can_use_pos(client, db):
    seed(db)
    response = client.get(
        "/v1/pos/sales", params={"register_id": "SEED"}, headers=auth("seed-bob", "bob@demo.test", "Bob")
    )
    assert response.status_code == 200
    assert response.json()
