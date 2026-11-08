import sqlite3
from dataclasses import asdict, dataclass

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from . import members, sales
from .auth import CurrentMember, SignedIn
from .db import Db, PageLimit
from .errors import ApiError
from .tokens import format_card_number
from .wallet_api import WalletError

router = APIRouter(prefix="/v1/me", tags=["member"])


@dataclass
class Me:
    card_number: str
    card_display: str
    display_name: str
    role: str
    balance: int


@dataclass
class MeSession(Me):
    totp_secret: str


def _profile(conn: sqlite3.Connection, member: sqlite3.Row) -> Me:
    return Me(
        card_number=member["card_number"],
        card_display=format_card_number(member["card_number"]),
        display_name=member["display_name"],
        role=member["role"],
        balance=members.balance(conn, member["id"]),
    )


@router.post("/session")
def session(conn: Db, user: SignedIn) -> MeSession:
    member = members.open_session(conn, user)
    return MeSession(**asdict(_profile(conn, member)), totp_secret=member["totp_secret"])


@router.get("")
def me(conn: Db, member: CurrentMember) -> Me:
    return _profile(conn, member)

@router.get("/history")
def history(conn: Db, member: CurrentMember, limit: PageLimit = 50) -> list[sales.HistoryItem]:
    return sales.history(conn, member["id"], limit)

class FcmTokenIn(BaseModel):
    token: str


@router.put("/fcm-token", status_code=204)
def set_fcm_token(payload: FcmTokenIn, conn: Db, member: CurrentMember) -> Response:
    conn.execute("UPDATE members SET fcm_token = ? WHERE id = ?", (payload.token, member["id"]))
    return Response(status_code=204)


@router.get("/wallet")
def wallet_enabled(request: Request, member: CurrentMember) -> dict[str, bool]:
    return {"enabled": request.app.state.wallet is not None and member["role"] == "customer"}


@router.post("/wallet/save")
def wallet_save(request: Request, conn: Db, member: CurrentMember) -> dict[str, str]:
    wallet = request.app.state.wallet
    if wallet is None:
        raise ApiError(404, "wallet_disabled", "Google Wallet is not enabled")
    if member["role"] != "customer":
        raise ApiError(403, "forbidden", "Customer access required")
    try:
        return wallet.prepare_save(conn, member)
    except WalletError as exc:
        raise ApiError(502, "wallet_unavailable", "Google Wallet is not responding") from exc
