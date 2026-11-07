from base64 import b32decode

from .config import WalletSettings
from .tokens import STEP_SECONDS, format_card_number


def class_id(wallet: WalletSettings) -> str:
    return f"{wallet.issuer_id}.{wallet.class_suffix}"


def object_id(wallet: WalletSettings, card_number: str) -> str:
    return f"{wallet.issuer_id}.member_{card_number}"


def class_body(wallet: WalletSettings) -> dict:
    return {
        "id": class_id(wallet),
        "issuerName": "DemoMart",
        "programName": "DemoMart Rewards",
        "programLogo": {"sourceUri": {"uri": wallet.logo_url}},
        "hexBackgroundColor": "#1E5B47",
        "reviewStatus": "UNDER_REVIEW",
    }


def secret_hex(totp_secret: str) -> str:
    padded = totp_secret + "=" * (-len(totp_secret) % 8)
    return b32decode(padded, casefold=True).hex()


def _points(balance: int) -> dict:
    return {
        "loyaltyPoints": {"label": "Points", "balance": {"int": balance}},
        "secondaryLoyaltyPoints": {
            "label": "Worth",
            "balance": {"money": {"micros": max(balance, 0) * 10_000, "currencyCode": "EUR"}},
        },
    }


def points_patch(balance: int) -> dict:
    return {**_points(balance), "notifyPreference": "NOTIFY_ON_UPDATE"}


def object_body(
    wallet: WalletSettings, *, card_number: str, display_name: str, balance: int,
    totp_secret: str, wallet_code: str | None,
) -> dict:
    display = format_card_number(card_number)
    body = {
        "id": object_id(wallet, card_number),
        "classId": class_id(wallet),
        "state": "ACTIVE",
        "accountId": display,
        "accountName": display_name,
        **_points(balance),
    }
    barcode = {"type": "QR_CODE", "alternateText": display}
    if wallet.barcode_mode == "static":
        if not wallet_code:
            raise ValueError("Static barcode requires a wallet_code")
        body["barcode"] = {**barcode, "value": f"DMW1:{card_number}:{wallet_code}"}
    else:
        body["rotatingBarcode"] = {
            **barcode,
            "valuePattern": f"DM1:{card_number}:{{totp_value_0}}",
            "totpDetails": {
                "periodMillis": str(STEP_SECONDS * 1000),
                "algorithm": "TOTP_SHA1",
                "parameters": [{"key": secret_hex(totp_secret), "valueLength": 6}],
            },
        }
    return body
