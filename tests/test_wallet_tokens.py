import sqlite3

import pytest

from conftest import make_cashier, make_customer
from loyalty.config import Settings
from loyalty.db import init_schema
from loyalty.tokens import new_wallet_code, parse_any


def test_parse_any_kinds():
    assert parse_any("DM1:48210093:877905") == ("app", "48210093", "877905")
    assert parse_any("DMW1:48210093:ABCDEFGH23") == ("wallet", "48210093", "ABCDEFGH23")


def test_wallet_code_alphabet():
    code = new_wallet_code()
    assert len(code) == 10
    assert set(code) <= set("ABCDEFGHJKLMNPQRSTUVWXYZ23456789")


@pytest.mark.parametrize("stored, expected", [
    ("ABCDEFGH23", 200), ("ABCDEFGH24", 422), (None, 422),
])
def test_identify_with_wallet_code(client, db, stored, expected):
    customer = make_customer(client, "anna", name="Anna")
    card = customer["card_number"]
    db.execute("UPDATE members SET wallet_code = ? WHERE card_number = ?", (stored, card))
    response = client.post("/v1/pos/identify", headers=make_cashier(db),
                           json={"token": f"DMW1:{card}:ABCDEFGH23"})
    assert response.status_code == expected
    if expected == 200:
        assert response.json()["display_name"] == "Anna"
    else:
        assert response.json()["error"] == "token_invalid"


def test_migration_adds_columns(tmp_path):
    with sqlite3.connect(tmp_path / "old.db", isolation_level=None) as conn:
        conn.execute("CREATE TABLE members (id INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO members VALUES (1)")
        init_schema(conn)
        init_schema(conn)
        assert conn.execute("SELECT wallet_code, wallet_object_created FROM members").fetchone() == (None, 0)


def test_wallet_settings_from_env(monkeypatch, tmp_path):
    monkeypatch.delenv("WALLET_ISSUER_ID", raising=False)
    assert not Settings.from_env().wallet.enabled
    key = tmp_path / "sa.json"
    key.write_text("{}")
    monkeypatch.setenv("WALLET_ISSUER_ID", "123")
    monkeypatch.setenv("WALLET_SERVICE_ACCOUNT", str(key))
    monkeypatch.setenv("WALLET_LOGO_URL", "https://example.test/logo.png")
    monkeypatch.setenv("WALLET_ORIGINS", "a, b")
    settings = Settings.from_env().wallet
    assert settings.enabled and settings.origins == ("a", "b")
    assert settings.barcode_mode == "rotating"


def test_wallet_enabled_requires_sa_and_logo(monkeypatch, tmp_path):
    monkeypatch.setenv("WALLET_ISSUER_ID", "123")
    monkeypatch.setenv("WALLET_SERVICE_ACCOUNT", str(tmp_path / "missing"))
    with pytest.raises(ValueError, match="WALLET_SERVICE_ACCOUNT"):
        Settings.from_env()
    key = tmp_path / "sa.json"
    key.write_text("{}")
    monkeypatch.setenv("WALLET_SERVICE_ACCOUNT", str(key))
    monkeypatch.setenv("WALLET_LOGO_URL", "http://example.test/logo.png")
    with pytest.raises(ValueError, match="WALLET_LOGO_URL"):
        Settings.from_env()
    monkeypatch.setenv("WALLET_LOGO_URL", "https://example.test/logo.png")
    monkeypatch.setenv("WALLET_BARCODE_MODE", "broken")
    with pytest.raises(ValueError, match="WALLET_BARCODE_MODE"):
        Settings.from_env()
