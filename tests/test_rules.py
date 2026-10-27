import pytest

from loyalty.errors import ApiError
from loyalty.rules import max_redeem, quote


def test_spec_example_23_eur_redeem_500():
    result = quote(2300, 500, balance=1355)
    assert (result.discount_cents, result.paid_cents, result.earn_points) == (500, 1800, 18)
    assert result.max_redeem_points == 1300


def test_earn_rounds_down_full_euros():
    assert quote(1870, 0, balance=0).earn_points == 18


@pytest.mark.parametrize("points", [99, -100])
def test_redeem_must_be_nonnegative_multiple_of_100(points):
    with pytest.raises(ApiError) as exc:
        quote(2300, points, 1355)
    assert exc.value.code == "redeem_step"


def test_redeem_more_than_balance():
    with pytest.raises(ApiError) as exc:
        quote(2300, 1400, 1355)
    assert exc.value.code == "insufficient_points"


def test_redeem_more_than_amount():
    with pytest.raises(ApiError) as exc:
        quote(350, 400, 1000)
    assert exc.value.code == "redeem_exceeds_amount"


def test_full_redeem_pays_zero_earns_zero():
    result = quote(500, 500, 900)
    assert (result.paid_cents, result.earn_points) == (0, 0)


def test_max_redeem_small_amount():
    assert max_redeem(350, 1000) == 300


def test_negative_balance_still_allows_purchase_without_redemption():
    result = quote(350, 0, -100)
    assert (result.max_redeem_points, result.earn_points) == (0, 3)


@pytest.mark.parametrize("amount", [0, -1, 1_000_001])
def test_amount_invalid(amount):
    with pytest.raises(ApiError) as exc:
        quote(amount, 0, 0)
    assert exc.value.code == "amount_invalid"
