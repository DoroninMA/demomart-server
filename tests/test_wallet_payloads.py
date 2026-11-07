from dataclasses import replace

import pytest

from loyalty.config import WalletSettings
from loyalty.tokens import make_token
from loyalty.wallet_payloads import class_body, class_id, object_body, object_id, points_patch, secret_hex


WS = WalletSettings(issuer_id="123", logo_url="https://example.test/logo.png")
CARD = "48210093"
SECRET = "JBSWY3DPEHPK3PXP" * 2


def body(wallet=WS, balance=1355, wallet_code=None):
    return object_body(wallet, card_number=CARD, display_name="Anna K.", balance=balance,
                       totp_secret=SECRET, wallet_code=wallet_code)


def test_ids():
    assert class_id(WS) == "123.demomart_loyalty_v1"
    assert object_id(WS, CARD) == "123.member_48210093"


def test_rotating_object_matches_app_token():
    obj = body()
    assert "barcode" not in obj
    assert obj["id"] == object_id(WS, CARD)
    assert obj["classId"] == class_id(WS)
    barcode = obj["rotatingBarcode"]
    assert barcode["valuePattern"] == "DM1:48210093:{totp_value_0}"
    assert barcode["valuePattern"].replace("{totp_value_0}", "877905") == make_token(CARD, SECRET, 1_800_000_000)
    assert barcode["totpDetails"] == {
        "periodMillis": "30000", "algorithm": "TOTP_SHA1",
        "parameters": [{"key": secret_hex(SECRET), "valueLength": 6}],
    }


def test_static_object():
    static = replace(WS, barcode_mode="static")
    obj = body(static, wallet_code="ABCDEFGH23")
    assert "rotatingBarcode" not in obj
    assert obj["barcode"] == {"type": "QR_CODE", "value": "DMW1:48210093:ABCDEFGH23",
                              "alternateText": "DM 4821 0093"}
    with pytest.raises(ValueError, match="wallet_code"):
        body(static)


def test_points_and_worth():
    obj = body()
    assert obj["accountId"] == "DM 4821 0093"
    assert obj["accountName"] == "Anna K."
    assert obj["loyaltyPoints"] == {"label": "Points", "balance": {"int": 1355}}
    assert obj["secondaryLoyaltyPoints"] == {
        "label": "Worth", "balance": {"money": {"micros": 13_550_000, "currencyCode": "EUR"}},
    }


def test_negative_balance_worth_zero():
    patch = points_patch(-100)
    assert patch["loyaltyPoints"]["balance"]["int"] == -100
    assert patch["secondaryLoyaltyPoints"]["balance"]["money"]["micros"] == 0
    assert patch["notifyPreference"] == "NOTIFY_ON_UPDATE"


def test_class_body():
    cls = class_body(WS)
    assert cls["id"] == class_id(WS)
    assert cls["issuerName"] == "DemoMart"
    assert cls["programName"] == "DemoMart Rewards"
    assert cls["hexBackgroundColor"] == "#1E5B47"
    assert cls["reviewStatus"] == "UNDER_REVIEW"
    assert cls["programLogo"]["sourceUri"]["uri"] == WS.logo_url


def test_secret_hex():
    assert secret_hex("GEZDGNBVGY3TQOJQ" * 2) == b"12345678901234567890".hex()
