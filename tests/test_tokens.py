import re

import pytest

from loyalty.errors import ApiError
from loyalty.tokens import (
    check_code,
    format_card_number,
    make_token,
    new_card_number,
    new_secret,
    parse_token,
)

T = 1_800_000_000.0
S = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"
CARD = "48210093"


def test_roundtrip_now():
    card, code = parse_token(make_token(CARD, S, T))
    assert card == CARD
    check_code(S, code, T)


def test_previous_step_accepted():
    _, code = parse_token(make_token(CARD, S, T - 30))
    check_code(S, code, T)


@pytest.mark.parametrize("phase", [0, 1, 15, 29])
@pytest.mark.parametrize("skew", [-30, -20, 20, 30])
def test_clock_skew_up_to_30s_accepted(phase, skew):
    _, code = parse_token(make_token(CARD, S, T + phase + skew))
    check_code(S, code, T + phase)


def test_five_minutes_old_is_expired():
    _, code = parse_token(make_token(CARD, S, T - 300))
    with pytest.raises(ApiError) as exc:
        check_code(S, code, T)
    assert exc.value.code == "token_expired"


def test_wrong_secret_is_invalid():
    _, code = parse_token(make_token(CARD, "A" * 32, T))
    with pytest.raises(ApiError) as exc:
        check_code(S, code, T)
    assert exc.value.code == "token_invalid"


@pytest.mark.parametrize("bad", ["", "DM1:123:000000", "XX1:48210093:123456", "DM1:48210093:12a456"])
def test_bad_format(bad):
    with pytest.raises(ApiError) as exc:
        parse_token(bad)
    assert exc.value.code == "token_invalid"


def test_format_card_number():
    assert format_card_number(CARD) == "DM 4821 0093"


def test_generated_card_and_secret_have_expected_formats():
    assert re.fullmatch(r"[1-9][0-9]{7}", new_card_number())
    assert re.fullmatch(r"[A-Z2-7]{32}", new_secret())
