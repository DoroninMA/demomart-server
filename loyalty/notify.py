import logging
import sqlite3
from collections.abc import Callable, Sequence
from typing import Protocol

from firebase_admin import messaging

from .sales import SaleResult

logger = logging.getLogger(__name__)


class BalanceListener(Protocol):
    def balance_changed(self, member: sqlite3.Row, balance: int, sale: SaleResult) -> None: ...


class FcmNotifier:
    def __init__(self, send: Callable[[messaging.Message], str] = messaging.send):
        self._send = send

    def balance_changed(self, member: sqlite3.Row, balance: int, sale: SaleResult) -> None:
        token = member["fcm_token"]
        if not token:
            return

        delta = sale.earned_points - sale.redeem_points
        if sale.status == "refunded":
            delta = -delta
        self._send(messaging.Message(
            token=token,
            data={
                "type": "balance_changed",
                "balance": str(balance),
                "sale_id": str(sale.sale_id),
                "delta": str(delta),
            },
        ))


def notify_listeners(
    conn: sqlite3.Connection, listeners: Sequence[BalanceListener], sale: SaleResult
) -> None:
    if not listeners or sale.balance is None or not (sale.earned_points or sale.redeem_points):
        return

    member = conn.execute("SELECT * FROM members WHERE id = ?", (sale.member_id,)).fetchone()
    for listener in listeners:
        try:
            listener.balance_changed(member, sale.balance, sale)
        except Exception:
            logger.exception("Balance listener failed for sale %s", sale.sale_id)
