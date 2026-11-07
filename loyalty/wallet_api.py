from threading import local
from typing import Protocol

from google.auth.exceptions import GoogleAuthError
from google.auth.transport.requests import AuthorizedSession
from google.oauth2.service_account import Credentials
from requests import RequestException

BASE = "https://walletobjects.googleapis.com/walletobjects/v1"
SCOPE = "https://www.googleapis.com/auth/wallet_object.issuer"


class WalletError(Exception):
    def __init__(self, status: int, text: str):
        self.status = status
        self.text = text
        super().__init__(f"Wallet request failed ({status})")


class WalletConflict(WalletError):
    pass


class WalletApi(Protocol):
    def get_class(self, id: str) -> dict | None: ...
    def insert_class(self, body: dict) -> None: ...
    def patch_class(self, id: str, body: dict) -> None: ...
    def get_object(self, id: str) -> dict | None: ...
    def insert_object(self, body: dict) -> None: ...
    def patch_object(self, id: str, body: dict) -> None: ...


class GoogleWalletApi:
    def __init__(self, sa_path: str, session_factory=AuthorizedSession):
        self._credentials = Credentials.from_service_account_file(sa_path, scopes=[SCOPE])
        self._session_factory = session_factory
        self._sessions = local()

    def _request(self, method: str, path: str, body: dict | None = None) -> dict | None:
        if not hasattr(self._sessions, "session"):
            self._sessions.session = self._session_factory(self._credentials.with_scopes([SCOPE]))
        try:
            response = self._sessions.session.request(method, f"{BASE}/{path}", json=body, timeout=10)
        except (RequestException, GoogleAuthError) as exc:
            raise WalletError(503, str(exc)) from None

        if method == "GET" and response.status_code == 404:
            return None
        if method == "POST" and response.status_code == 409:
            raise WalletConflict(409, response.text)
        if not 200 <= response.status_code < 300:
            raise WalletError(response.status_code, response.text)
        if method == "GET":
            try:
                return response.json()
            except ValueError:
                raise WalletError(502, "Invalid Wallet JSON response") from None
        return None

    def get_class(self, id: str) -> dict | None:
        return self._request("GET", f"loyaltyClass/{id}")

    def insert_class(self, body: dict) -> None:
        self._request("POST", "loyaltyClass", body)

    def patch_class(self, id: str, body: dict) -> None:
        self._request("PATCH", f"loyaltyClass/{id}", body)

    def get_object(self, id: str) -> dict | None:
        return self._request("GET", f"loyaltyObject/{id}")

    def insert_object(self, body: dict) -> None:
        self._request("POST", "loyaltyObject", body)

    def patch_object(self, id: str, body: dict) -> None:
        self._request("PATCH", f"loyaltyObject/{id}", body)
