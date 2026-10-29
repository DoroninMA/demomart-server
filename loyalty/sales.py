import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from . import members, rules
from .db import timestamp, write_transaction
from .errors import ApiError


@dataclass
class SaleResult:
    sale_id: int
    register_id: str
    receipt_no: int
    member_id: int | None
    display_name: str | None
    amount_cents: int
    redeem_points: int
    paid_cents: int
    earned_points: int
    status: str
    balance: int | None
    created_at: str


@dataclass
class HistoryItem:
    sale_id: int
    kind: Literal["sale", "refund"]
    at: str
    paid_cents: int
    points_delta: int


_SELECT_SALE = """
    SELECT sales.*, members.display_name,
           CASE WHEN sales.member_id IS NOT NULL THEN (
               SELECT COALESCE(SUM(points), 0) FROM ledger WHERE member_id = sales.member_id
           ) END AS balance
    FROM sales LEFT JOIN members ON members.id = sales.member_id
"""


def _lookup(conn: sqlite3.Connection, register_id: str, receipt_no: int) -> sqlite3.Row | None:
    return conn.execute(
        _SELECT_SALE + " WHERE register_id = ? AND receipt_no = ?", (register_id, receipt_no)
    ).fetchone()


def _result(row: sqlite3.Row) -> SaleResult:
    return SaleResult(
        sale_id=row["id"],
        register_id=row["register_id"],
        receipt_no=row["receipt_no"],
        member_id=row["member_id"],
        display_name=row["display_name"],
        amount_cents=row["amount_cents"],
        redeem_points=row["redeem_points"],
        paid_cents=row["paid_cents"],
        earned_points=row["earned_points"],
        status=row["status"],
        balance=row["balance"],
        created_at=row["created_at"],
    )


def _write_ledger(
    conn: sqlite3.Connection, member_id: int | None, sale_id: int, at: str, *entries: tuple[str, int]
) -> None:
    if member_id is not None:
        conn.executemany(
            "INSERT INTO ledger (member_id, sale_id, kind, points, created_at) VALUES (?, ?, ?, ?, ?)",
            ((member_id, sale_id, kind, points, at) for kind, points in entries if points),
        )


def _commit(
    conn: sqlite3.Connection,
    existing: sqlite3.Row | None,
    register_id: str,
    receipt_no: int,
    member_id: int | None,
    amount_cents: int,
    redeem_points: int,
    at: datetime | None,
) -> SaleResult:
    if existing is not None:
        stored = existing["member_id"], existing["amount_cents"], existing["redeem_points"]
        if stored != (member_id, amount_cents, redeem_points):
            raise ApiError(409, "sale_conflict", "Receipt number already used for a different sale")
        return _result(existing)

    balance = members.balance(conn, member_id) if member_id is not None else 0
    quote = rules.quote(amount_cents, redeem_points, balance)
    earned_points = quote.earn_points if member_id is not None else 0
    created_at = timestamp(at)
    sale_id = conn.execute(
        """
        INSERT INTO sales (
            register_id, receipt_no, member_id, amount_cents, redeem_points, paid_cents,
            earned_points, status, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, 'committed', ?)
        """,
        (register_id, receipt_no, member_id, amount_cents, redeem_points, quote.paid_cents, earned_points, created_at),
    ).lastrowid
    _write_ledger(conn, member_id, sale_id, created_at, ("redeem", -redeem_points), ("earn", earned_points))
    return _result(_lookup(conn, register_id, receipt_no))


def commit(
    conn: sqlite3.Connection,
    register_id: str,
    receipt_no: int,
    member_id: int | None,
    amount_cents: int,
    redeem_points: int,
    at: datetime | None = None,
) -> SaleResult:
    with write_transaction(conn):
        existing = _lookup(conn, register_id, receipt_no)
        return _commit(conn, existing, register_id, receipt_no, member_id, amount_cents, redeem_points, at)


def commit_identified(
    conn: sqlite3.Connection,
    register_id: str,
    receipt_no: int,
    customer_ref: str | None,
    amount_cents: int,
    redeem_points: int,
) -> SaleResult:
    with write_transaction(conn):
        existing = _lookup(conn, register_id, receipt_no)
        now = datetime.now(timezone.utc)
        member_id = None
        if customer_ref is not None:
            member = members.resolve_ref(conn, customer_ref, now, allow_expired=existing is not None)
            member_id = member["id"]
        return _commit(conn, existing, register_id, receipt_no, member_id, amount_cents, redeem_points, now)


def next_receipt_no(conn: sqlite3.Connection, register_id: str) -> int:
    last = conn.execute(
        "SELECT MAX(receipt_no) FROM sales WHERE register_id = ?", (register_id,)
    ).fetchone()[0]
    return (last or 0) + 1


def refund(conn: sqlite3.Connection, register_id: str, receipt_no: int) -> SaleResult:
    with write_transaction(conn):
        existing = _lookup(conn, register_id, receipt_no)
        if existing is None:
            raise ApiError(404, "sale_not_found", "Sale not found")
        if existing["status"] == "refunded":
            raise ApiError(409, "already_refunded", "Sale already refunded")

        refunded_at = timestamp()
        conn.execute(
            "UPDATE sales SET status = 'refunded', refunded_at = ? WHERE id = ?",
            (refunded_at, existing["id"]),
        )
        _write_ledger(
            conn, existing["member_id"], existing["id"], refunded_at,
            ("reverse_earn", -existing["earned_points"]), ("reverse_redeem", existing["redeem_points"]),
        )
        return _result(_lookup(conn, register_id, receipt_no))


def recent(conn: sqlite3.Connection, register_id: str, limit: int = 20) -> list[SaleResult]:
    rows = conn.execute(
        _SELECT_SALE + " WHERE register_id = ? ORDER BY sales.created_at DESC, sales.id DESC LIMIT ?",
        (register_id, limit),
    )
    return [_result(row) for row in rows]


def history(conn: sqlite3.Connection, member_id: int, limit: int = 50) -> list[HistoryItem]:
    rows = conn.execute(
        """
        SELECT id AS sale_id, 'sale' AS kind, created_at AS at, paid_cents,
               earned_points - redeem_points AS points_delta
        FROM sales WHERE member_id = ?
        UNION ALL
        SELECT id, 'refund', refunded_at, paid_cents, redeem_points - earned_points
        FROM sales WHERE member_id = ? AND status = 'refunded'
        ORDER BY at DESC, sale_id DESC, kind ASC LIMIT ?
        """,
        (member_id, member_id, limit),
    )
    return [HistoryItem(**dict(row)) for row in rows]
