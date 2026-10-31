import sqlite3
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from . import members, rules, sales, tokens
from .auth import require_cashier
from .db import Db, PageLimit, SQLITE_MAX_INT
from .errors import ApiError
from .notify import notify_listeners

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


REGISTER_PATTERN = r"^[A-Za-z0-9_-]{1,32}$"


class ReceiptIn(BaseModel):
    register_id: Annotated[str, Field(pattern=REGISTER_PATTERN)]
    receipt_no: Annotated[StrictInt, Field(ge=1, le=SQLITE_MAX_INT)]


class CommitIn(ReceiptIn, QuoteIn):
    pass


class SaleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sale_id: int
    register_id: str
    receipt_no: int
    display_name: str | None
    amount_cents: int
    redeem_points: int
    paid_cents: int
    earned_points: int
    status: str
    balance: int | None
    created_at: str


@dataclass
class NextReceipt:
    register_id: str
    next_receipt_no: int


RegisterQuery = Annotated[str, Query(pattern=REGISTER_PATTERN)]


@router.post("/commit", response_model=SaleOut)
def commit(payload: CommitIn, request: Request, conn: Db, _cashier: Cashier) -> sales.SaleResult:
    result, is_new = sales.commit_identified(
        conn, payload.register_id, payload.receipt_no, payload.customer_ref,
        payload.amount_cents, payload.redeem_points,
    )
    if is_new:
        notify_listeners(conn, request.app.state.listeners, result)
    return result


@router.post("/refund", response_model=SaleOut)
def refund(payload: ReceiptIn, request: Request, conn: Db, _cashier: Cashier) -> sales.SaleResult:
    result = sales.refund(conn, payload.register_id, payload.receipt_no)
    notify_listeners(conn, request.app.state.listeners, result)
    return result


@router.get("/sales", response_model=list[SaleOut])
def recent_sales(
    register_id: RegisterQuery, conn: Db, _cashier: Cashier, limit: PageLimit = 20
) -> list[sales.SaleResult]:
    return sales.recent(conn, register_id, limit)


@router.get("/next-receipt")
def next_receipt(register_id: RegisterQuery, conn: Db, _cashier: Cashier) -> NextReceipt:
    return NextReceipt(register_id, sales.next_receipt_no(conn, register_id))
