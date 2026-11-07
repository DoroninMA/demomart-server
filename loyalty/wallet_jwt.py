from collections.abc import Sequence

from google.auth import crypt, jwt


def make_save_jwt(sa_info: dict, object_id: str, origins: Sequence[str], now: int) -> str:
    signer = crypt.RSASigner.from_service_account_info(sa_info)
    return jwt.encode(signer, {
        "iss": sa_info["client_email"],
        "aud": "google",
        "typ": "savetowallet",
        "iat": now,
        "origins": list(origins),
        "payload": {"loyaltyObjects": [{"id": object_id}]},
    }).decode("ascii")


def save_url(jwt: str) -> str:
    return "https://pay.google.com/gp/v/save/" + jwt
