from dataclasses import dataclass

from .errors import ApiError

MAX_AMOUNT_CENTS = 1_000_000
REDEEM_STEP = 100


@dataclass(frozen=True)
class Quote:
    amount_cents: int
    redeem_points: int
    discount_cents: int
    paid_cents: int
    earn_points: int
    max_redeem_points: int


def max_redeem(amount_cents: int, balance: int) -> int:
    return max(0, min(amount_cents, balance)) // REDEEM_STEP * REDEEM_STEP


def quote(amount_cents: int, redeem_points: int, balance: int) -> Quote:
    if not 1 <= amount_cents <= MAX_AMOUNT_CENTS:
        raise ApiError(422, "amount_invalid", "Amount must be between €0.01 and €10,000")
    if redeem_points < 0 or redeem_points % REDEEM_STEP:
        raise ApiError(422, "redeem_step", "Redeem points in steps of 100")
    if redeem_points > max(0, balance):
        raise ApiError(422, "insufficient_points", "Not enough points")
    if redeem_points > amount_cents:
        raise ApiError(422, "redeem_exceeds_amount", "Discount exceeds the sale amount")

    paid_cents = amount_cents - redeem_points
    return Quote(
        amount_cents=amount_cents,
        redeem_points=redeem_points,
        discount_cents=redeem_points,
        paid_cents=paid_cents,
        earn_points=paid_cents // 100,
        max_redeem_points=max_redeem(amount_cents, balance),
    )
