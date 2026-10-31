import os
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone

from firebase_admin import auth

from . import members, sales
from .auth import init_firebase
from .config import Settings
from .db import connect, init_schema, write_transaction
from .errors import ApiError

_REGISTER = "SEED"
_DEMO_MEMBERS = (
    ("anna@demo.test", "Anna K.", "customer", (54_890, 39_255, 41_570, 12_799)),
    ("ben@demo.test", "Ben T.", "customer", (8_295, 6_499, 9_450)),
    ("chloe@demo.test", "Chloe M.", "customer", ()),
    ("bob@demo.test", "Bob", "cashier", ()),
)


def _firebase_uid(email: str, name: str, password: str) -> str:
    try:
        user = auth.get_user_by_email(email)
    except auth.UserNotFoundError:
        return auth.create_user(
            email=email, display_name=name, password=password, email_verified=True
        ).uid
    return auth.update_user(user.uid, display_name=name, password=password, email_verified=True).uid


def _ensure_member(
    conn: sqlite3.Connection, uid: str | None, email: str, name: str, role: str
) -> sqlite3.Row:
    with write_transaction(conn):
        member = members.by_email(conn, email)
        if member is None:
            return members.create_member(conn, uid, email, name, role)
        return conn.execute(
            """
            UPDATE members SET firebase_uid = COALESCE(?, firebase_uid), display_name = ?, role = ?
            WHERE id = ? RETURNING *
            """,
            (uid, name, role, member["id"]),
        ).fetchone()


def _seed_sales(
    conn: sqlite3.Connection, member_id: int, amounts: tuple[int, ...], now: datetime
) -> None:
    for index, amount in enumerate(amounts, start=1):
        at = (now - timedelta(days=29 - index * 6)).replace(hour=8 + index * 2, minute=index * 7)
        receipt_no = member_id * 10 + index
        result = sales.commit(conn, _REGISTER, receipt_no, member_id, amount, 0, at=at)
        if index == 4 and result.status == "committed":
            try:
                sales.refund(conn, _REGISTER, receipt_no)
            except ApiError as exc:
                if exc.code != "already_refunded":
                    raise


def run_seed(
    conn: sqlite3.Connection,
    *,
    password: str | None,
    google_email: str | None,
    create_firebase_users: bool,
) -> dict[str, int]:
    if create_firebase_users and not password:
        raise ValueError("SEED_PASSWORD is required in firebase mode")
    if google_email and google_email.lower() in {member[0] for member in _DEMO_MEMBERS}:
        raise ValueError("SEED_GOOGLE_EMAIL must differ from the built-in demo emails")

    now = datetime.now(timezone.utc)
    balances = {}
    for email, name, role, amounts in _DEMO_MEMBERS:
        uid = _firebase_uid(email, name, password) if create_firebase_users else f"seed-{email.split('@')[0]}"
        member = _ensure_member(conn, uid, email, name, role)
        if role == "customer":
            _seed_sales(conn, member["id"], amounts, now)
            balances[name] = members.balance(conn, member["id"])

    if google_email:
        member = _ensure_member(conn, None, google_email, "Demo User", "customer")
        _seed_sales(conn, member["id"], (28_410, 31_085, 26_660), now)
        balances["Demo User"] = members.balance(conn, member["id"])
    return balances


def main() -> None:
    settings = Settings.from_env()
    password = os.getenv("SEED_PASSWORD")
    google_email = os.getenv("SEED_GOOGLE_EMAIL") or None
    create_firebase_users = settings.auth_mode == "firebase"
    if create_firebase_users:
        if not password:
            raise SystemExit("SEED_PASSWORD is required in firebase mode")
        init_firebase(settings)

    with closing(connect(settings.database_path)) as conn:
        init_schema(conn)
        balances = run_seed(
            conn, password=password, google_email=google_email, create_firebase_users=create_firebase_users
        )
    for name, balance in balances.items():
        print(f"{name} {balance}")


if __name__ == "__main__":
    main()
