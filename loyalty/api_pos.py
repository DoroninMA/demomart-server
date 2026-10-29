import sqlite3
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, StrictInt

from . import members, rules, tokens
from .auth import require_cashier
from .db import Db
from .errors import ApiError

router = APIRouter(prefix="/v1/pos", tags=["pos"])
Cashier = Annotated[sqlite3.Row, Depends(require_cashier)]


class IdentifyIn(BaseModel):
    token: str


@dataclass
class Customer:
    customer_ref: str
    display_name: str
    card_display: str
    balance: int


class QuoteIn(BaseModel):
    customer_ref: str | None
    amount_cents: StrictInt
    redeem_points: StrictInt


@router.post("/identify")
def identify(payload: IdentifyIn, conn: Db, _cashier: Cashier) -> Customer:
    card, code = tokens.parse_token(payload.token)
    member = members.by_card(conn, card)
    if member is None:
        raise ApiError(404, "member_not_found", "Card not found")
    now = datetime.now(timezone.utc)
    tokens.check_code(member["totp_secret"], code, now.timestamp())
    return Customer(
        customer_ref=members.new_identification(conn, member["id"], now),
        display_name=member["display_name"],
        card_display=tokens.format_card_number(card),
        balance=members.balance(conn, member["id"]),
    )


@router.post("/quote")
def quote(payload: QuoteIn, conn: Db, _cashier: Cashier) -> rules.Quote:
    if payload.customer_ref is None:
        result = rules.quote(payload.amount_cents, payload.redeem_points, 0)
        return replace(result, earn_points=0)

    member = members.resolve_ref(conn, payload.customer_ref, datetime.now(timezone.utc))
    return rules.quote(payload.amount_cents, payload.redeem_points, members.balance(conn, member["id"]))
