import re
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from conftest import auth
from loyalty.auth import AuthUser
from loyalty.main import create_app


def test_session_creates_member(client):
    response = client.post("/v1/me/session", headers=auth("u1", "anna@demo.test", "Anna K."))
    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "customer" and body["balance"] == 0
    assert body["display_name"] == "Anna K."
    assert re.fullmatch(r"[0-9]{8}", body["card_number"])
    assert body["card_display"].startswith("DM ")


def test_session_is_stable(client):
    headers = auth("u1")
    first = client.post("/v1/me/session", headers=headers).json()
    second = client.post("/v1/me/session", headers=headers).json()
    assert second["card_number"] == first["card_number"]
    assert second["totp_secret"] == first["totp_secret"]


def insert_member(db, uid, email):
    return db.execute(
        """
        INSERT INTO members (firebase_uid, email, display_name, card_number, totp_secret, role, created_at)
        VALUES (?, ?, 'Seeded', '48210093', 'TEST', 'customer', '2026-11-09T12:00:00Z')
        """,
        (uid, email),
    ).lastrowid


def test_session_links_seeded_email(client, db):
    member_id = insert_member(db, None, "g@demo.test")
    response = client.post("/v1/me/session", headers=auth("u9", "g@demo.test"))
    assert response.status_code == 200
    assert response.json()["card_number"] == "48210093"
    member = db.execute("SELECT firebase_uid FROM members WHERE id = ?", (member_id,)).fetchone()
    assert member["firebase_uid"] == "u9"


def test_email_taken_by_other_uid(client, db):
    insert_member(db, "u1", "a@demo.test")
    response = client.post("/v1/me/session", headers=auth("u2", "a@demo.test"))
    assert response.status_code == 409
    assert response.json()["error"] == "email_taken"


def test_unverified_email_cannot_claim_seeded_member(client, db, settings):
    member_id = insert_member(db, None, "g@demo.test")

    class UnverifiedVerifier:
        def verify(self, id_token):
            return AuthUser("u9", "g@demo.test", False, None)

    with TestClient(create_app(settings, verifier=UnverifiedVerifier())) as unverified:
        response = unverified.post("/v1/me/session", headers=auth("u9", "g@demo.test"))
    assert response.status_code == 409
    assert response.json()["error"] == "email_taken"
    assert db.execute("SELECT firebase_uid FROM members WHERE id = ?", (member_id,)).fetchone()[0] is None


def test_me_requires_auth(client):
    response = client.get("/v1/me")
    assert response.status_code == 401
    assert response.json()["error"] == "unauthenticated"


def test_me_requires_session(client):
    response = client.get("/v1/me", headers=auth("u1"))
    assert response.status_code == 401
    assert response.json()["error"] == "session_required"


def test_me_after_session(client):
    headers = auth("u1")
    session = client.post("/v1/me/session", headers=headers).json()
    response = client.get("/v1/me", headers=headers)
    assert response.status_code == 200
    assert response.json() == {key: value for key, value in session.items() if key != "totp_secret"}


def test_parallel_requests(client):
    headers = auth("u1")
    assert client.post("/v1/me/session", headers=headers).status_code == 200
    with ThreadPoolExecutor(8) as pool:
        responses = list(pool.map(lambda _: client.get("/v1/me", headers=headers), range(20)))
    assert all(response.status_code == 200 for response in responses)
