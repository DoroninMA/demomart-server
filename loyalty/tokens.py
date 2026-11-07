import hmac
import re
import secrets
from datetime import datetime, timezone
from typing import Literal

import pyotp

from .errors import ApiError

TOKEN_PATTERN = re.compile(r"DM1:([0-9]{8}):([0-9]{6})")
WALLET_PATTERN = re.compile(r"DMW1:([0-9]{8}):([A-Z2-9]{10})")
WALLET_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
STEP_SECONDS = 30


def new_secret() -> str:
    return pyotp.random_base32()


def new_card_number() -> str:
    return str(10_000_000 + secrets.randbelow(90_000_000))


def format_card_number(card: str) -> str:
    return f"DM {card[:4]} {card[4:]}"


def make_token(card: str, secret: str, at: float) -> str:
    code = pyotp.TOTP(secret).at(datetime.fromtimestamp(at, timezone.utc))
    return f"DM1:{card}:{code}"


def parse_token(token: str) -> tuple[str, str]:
    match = TOKEN_PATTERN.fullmatch(token)
    if not match:
        raise ApiError(422, "token_invalid", "Invalid card token")
    return match[1], match[2]


def new_wallet_code() -> str:
    return "".join(secrets.choice(WALLET_ALPHABET) for _ in range(10))


def parse_any(token: str) -> tuple[Literal["app", "wallet"], str, str]:
    if match := WALLET_PATTERN.fullmatch(token):
        return "wallet", match[1], match[2]
    card, code = parse_token(token)
    return "app", card, code


def check_wallet_code(expected: str | None, code: str) -> None:
    if expected is None or not hmac.compare_digest(expected, code):
        raise ApiError(422, "token_invalid", "Invalid card token")


def check_code(secret: str, code: str, at: float) -> None:
    if not re.fullmatch(r"[0-9]{6}", code):
        raise ApiError(422, "token_invalid", "Invalid card token")

    totp = pyotp.TOTP(secret)
    now = datetime.fromtimestamp(at, timezone.utc)
    for offset in (0, -1, 1):
        if at + offset * STEP_SECONDS >= 0 and hmac.compare_digest(totp.at(now, offset), code):
            return
    for offset in (*range(-10, -1), *range(2, 11)):
        if at + offset * STEP_SECONDS >= 0 and hmac.compare_digest(totp.at(now, offset), code):
            raise ApiError(422, "token_expired", "Code expired, ask customer to refresh")
    raise ApiError(422, "token_invalid", "Invalid card token")
