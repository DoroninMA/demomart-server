import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast


@dataclass(frozen=True)
class WalletSettings:
    issuer_id: str = ""
    service_account: str | None = None
    class_suffix: str = "demomart_loyalty_v1"
    logo_url: str | None = None
    barcode_mode: Literal["rotating", "static"] = "rotating"
    origins: tuple[str, ...] = ()

    @property
    def enabled(self) -> bool:
        return bool(self.issuer_id)

    @classmethod
    def from_env(cls) -> "WalletSettings":
        issuer = os.getenv("WALLET_ISSUER_ID", "").strip()
        if not issuer:
            return cls()
        key = os.getenv("WALLET_SERVICE_ACCOUNT")
        if not key or not Path(key).is_file():
            raise ValueError("WALLET_SERVICE_ACCOUNT must point to an existing file")
        logo = os.getenv("WALLET_LOGO_URL")
        if not logo or not logo.startswith("https://"):
            raise ValueError("WALLET_LOGO_URL must be an HTTPS URL")
        mode = os.getenv("WALLET_BARCODE_MODE") or "rotating"
        if mode not in ("rotating", "static"):
            raise ValueError("WALLET_BARCODE_MODE must be rotating or static")
        suffix = os.getenv("WALLET_CLASS_SUFFIX") or "demomart_loyalty_v1"
        if not re.fullmatch(r"[A-Za-z0-9._-]+", suffix):
            raise ValueError("WALLET_CLASS_SUFFIX contains invalid characters")
        origins = tuple(part.strip() for part in os.getenv("WALLET_ORIGINS", "").split(",") if part.strip())
        return cls(issuer, key, suffix, logo, cast(Literal["rotating", "static"], mode), origins)


@dataclass(frozen=True)
class Settings:
    database_path: str
    auth_mode: Literal["firebase", "fake"]
    google_credentials: str | None
    wallet: WalletSettings = WalletSettings()

    @classmethod
    def from_env(cls) -> "Settings":
        mode = os.getenv("AUTH_MODE", "firebase")
        if mode not in ("firebase", "fake"):
            raise ValueError("AUTH_MODE must be firebase or fake")
        return cls(
            database_path=os.getenv("DATABASE_PATH") or "./loyalty.db",
            auth_mode=cast(Literal["firebase", "fake"], mode),
            google_credentials=os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or None,
            wallet=WalletSettings.from_env(),
        )
