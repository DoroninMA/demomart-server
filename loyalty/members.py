import sqlite3
from typing import TYPE_CHECKING

from .db import timestamp, write_transaction
from .errors import ApiError
from .tokens import new_card_number, new_secret

if TYPE_CHECKING:
    from .auth import AuthUser


def by_uid(conn: sqlite3.Connection, uid: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM members WHERE firebase_uid = ?", (uid,)).fetchone()


def by_email(conn: sqlite3.Connection, email: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM members WHERE email = ?", (email,)).fetchone()


def create_member(
    conn: sqlite3.Connection,
    uid: str | None,
    email: str | None,
    display_name: str,
    role: str = "customer",
) -> sqlite3.Row:
    secret = new_secret()
    while True:
        member = conn.execute(
            """
            INSERT INTO members (firebase_uid, email, display_name, card_number, totp_secret, role, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(card_number) DO NOTHING
            RETURNING *
            """,
            (uid, email, display_name, new_card_number(), secret, role, timestamp()),
        ).fetchone()
        if member is not None:
            return member


def open_session(conn: sqlite3.Connection, user: "AuthUser") -> sqlite3.Row:
    with write_transaction(conn):
        member = by_uid(conn, user.uid)
        if member is not None:
            return member
        member = by_email(conn, user.email) if user.email else None
        if member is not None:
            if user.email_verified and member["firebase_uid"] is None:
                return conn.execute(
                    "UPDATE members SET firebase_uid = ? WHERE id = ? RETURNING *",
                    (user.uid, member["id"]),
                ).fetchone()
            raise ApiError(409, "email_taken", "Email is already associated with a member")

        display_name = user.name or (user.email.split("@", 1)[0] if user.email else "Customer")
        return create_member(conn, user.uid, user.email, display_name)


def balance(conn: sqlite3.Connection, member_id: int) -> int:
    return conn.execute(
        "SELECT COALESCE(SUM(points), 0) FROM ledger WHERE member_id = ?", (member_id,)
    ).fetchone()[0]
