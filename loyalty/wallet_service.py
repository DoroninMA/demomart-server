import json
import logging
import sqlite3
import time
from collections.abc import Callable
from concurrent.futures import Executor
from contextlib import closing
from pathlib import Path
from threading import Lock

from . import members
from .config import WalletSettings
from .db import connect, write_transaction
from .notify import BalanceListener
from .sales import SaleResult
from .tokens import new_wallet_code
from .wallet_api import GoogleWalletApi, WalletApi, WalletConflict
from .wallet_jwt import make_save_jwt, save_url
from .wallet_payloads import class_body, class_id, object_body, object_id, points_patch

logger = logging.getLogger(__name__)


class WalletService:
    def __init__(self, wallet: WalletSettings, api: WalletApi, sa_info: dict, clock=time.time):
        self.wallet = wallet
        self.api = api
        self._sa_info = sa_info
        self._clock = clock
        self._class_lock = Lock()
        self._class_ready = False
        self.object_lock = Lock()

    @classmethod
    def from_settings(cls, wallet: WalletSettings, api: WalletApi | None = None) -> "WalletService":
        if not wallet.service_account:
            raise ValueError("WALLET_SERVICE_ACCOUNT is required")
        sa_info = json.loads(Path(wallet.service_account).read_text(encoding="utf-8"))
        return cls(wallet, api if api is not None else GoogleWalletApi(wallet.service_account), sa_info)

    def ensure_class(self) -> None:
        with self._class_lock:
            if self._class_ready:
                return
            class_ref = class_id(self.wallet)
            body = class_body(self.wallet)
            if self.api.get_class(class_ref) is None:
                try:
                    self.api.insert_class(body)
                except WalletConflict:
                    pass
            else:
                self.api.patch_class(class_ref, body)
            self._class_ready = True

    def prepare_save(self, conn: sqlite3.Connection, member: sqlite3.Row) -> dict:
        self.ensure_class()
        member_id = member["id"]
        card = member["card_number"]
        pass_id = object_id(self.wallet, card)
        with self.object_lock:
            with write_transaction(conn):
                current = members.by_card(conn, card)
                code = current["wallet_code"]
                if self.wallet.barcode_mode == "static" and not code:
                    code = new_wallet_code()
                    conn.execute("UPDATE members SET wallet_code = ? WHERE id = ?", (code, member_id))
                balance = members.balance(conn, member_id)

            body = object_body(self.wallet, card_number=card, display_name=current["display_name"],
                               balance=balance, totp_secret=current["totp_secret"], wallet_code=code)
            existing = self.api.get_object(pass_id)
            if existing is None:
                try:
                    self.api.insert_object(body)
                except WalletConflict:
                    self._patch_object(pass_id, body)
            else:
                self._patch_object(pass_id, body)

            with write_transaction(conn):
                conn.execute("UPDATE members SET wallet_object_created = 1 WHERE id = ?", (member_id,))
                latest_balance = members.balance(conn, member_id)
            if latest_balance != balance:
                self.api.patch_object(pass_id, points_patch(latest_balance))

        token = make_save_jwt(self._sa_info, pass_id, self.wallet.origins, int(self._clock()))
        return {"jwt": token, "save_url": save_url(token)}

    def _patch_object(self, pass_id: str, body: dict) -> None:
        # Clear the previous barcode when switching modes.
        other = "rotatingBarcode" if "barcode" in body else "barcode"
        self.api.patch_object(pass_id, {**body, other: None})


class WalletUpdater(BalanceListener):
    def __init__(
        self, wallet: WalletSettings, api: WalletApi, executor: Executor, *,
        object_lock=None, latest_balance: Callable[[int], int] | None = None,
    ):
        self._wallet = wallet
        self._api = api
        self._executor = executor
        self._object_lock = object_lock if object_lock is not None else Lock()
        self._latest_balance = latest_balance

    @classmethod
    def for_service(cls, service: WalletService, executor: Executor, database_path: str) -> "WalletUpdater":
        def latest_balance(member_id: int) -> int:
            with closing(connect(database_path)) as conn:
                return members.balance(conn, member_id)

        return cls(service.wallet, service.api, executor, object_lock=service.object_lock, latest_balance=latest_balance)

    def balance_changed(self, member: sqlite3.Row, balance: int, sale: SaleResult) -> None:
        if member["wallet_object_created"]:
            pass_id = object_id(self._wallet, member["card_number"])
            self._executor.submit(self._patch, pass_id, member["id"], balance)

    def _patch(self, pass_id: str, member_id: int, balance: int) -> None:
        try:
            with self._object_lock:
                if self._latest_balance is not None:
                    balance = self._latest_balance(member_id)
                self._api.patch_object(pass_id, points_patch(balance))
        except Exception:
            logger.exception("Wallet balance update failed for object %s", pass_id)
