import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from google.auth import jwt
from google.auth._helpers import padded_urlsafe_b64decode

from loyalty.wallet_jwt import make_save_jwt, save_url


@pytest.fixture(scope="session")
def rsa_sa_info():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return {
        "client_email": "wallet@example.test",
        "private_key_id": "test-key",
        "private_key": key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                         serialization.NoEncryption()).decode(),
        "token_uri": "https://oauth2.googleapis.com/token",
        "_public_pem": key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo),
    }


def test_jwt_claims_and_signature(rsa_sa_info):
    token = make_save_jwt(rsa_sa_info, "I.member_48210093", ["https://demo.test"], now=1_800_000_000)
    signed, signature = token.encode().rsplit(b".", 1)
    public = serialization.load_pem_public_key(rsa_sa_info["_public_pem"])
    public.verify(padded_urlsafe_b64decode(signature), signed, padding.PKCS1v15(), hashes.SHA256())
    assert jwt.decode_header(token)["alg"] == "RS256"
    assert jwt.decode(token, verify=False) == {
        "iss": rsa_sa_info["client_email"], "aud": "google", "typ": "savetowallet",
        "iat": 1_800_000_000, "origins": ["https://demo.test"],
        "payload": {"loyaltyObjects": [{"id": "I.member_48210093"}]},
    }
    assert len(token) < 1800


def test_save_url_prefix():
    assert save_url("signed-token") == "https://pay.google.com/gp/v/save/signed-token"
