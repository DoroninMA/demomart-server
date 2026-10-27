import os
from dataclasses import dataclass
from typing import Literal, cast


@dataclass(frozen=True)
class Settings:
    database_path: str
    auth_mode: Literal["firebase", "fake"]
    google_credentials: str | None

    @classmethod
    def from_env(cls) -> "Settings":
        mode = os.getenv("AUTH_MODE", "firebase")
        if mode not in ("firebase", "fake"):
            raise ValueError("AUTH_MODE must be firebase or fake")
        return cls(
            database_path=os.getenv("DATABASE_PATH") or "./loyalty.db",
            auth_mode=cast(Literal["firebase", "fake"], mode),
            google_credentials=os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or None,
        )
