import struct

from loyalty.wallet_setup import main
from test_wallet_service import FakeWalletApi


def test_setup_disabled_exits_1(monkeypatch, capsys):
    monkeypatch.delenv("WALLET_ISSUER_ID", raising=False)
    assert main() == 1
    assert "WALLET_ISSUER_ID" in capsys.readouterr().err


def test_setup_creates_class(monkeypatch, tmp_path, capsys):
    key = tmp_path / "key.json"
    key.write_text("{}")
    monkeypatch.setenv("WALLET_ISSUER_ID", "123")
    monkeypatch.setenv("WALLET_SERVICE_ACCOUNT", str(key))
    monkeypatch.setenv("WALLET_LOGO_URL", "https://example.test/logo.png")
    api = FakeWalletApi()
    assert main(api=api) == 0
    assert main(api=api) == 0
    assert [name for name, _ in api.calls] == ["insert_class", "patch_class"]
    assert "Wallet class ready: 123.demomart_loyalty_v1" in capsys.readouterr().out


def test_static_logo_served(client, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    response = client.get("/static/wallet-logo.png")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert struct.unpack(">II", response.content[16:24]) == (660, 660)
    assert len(response.content) <= 100_000
