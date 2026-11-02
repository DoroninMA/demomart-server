import sqlite3
from dataclasses import dataclass
from threading import Lock
from typing import Annotated, Protocol

import firebase_admin
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from firebase_admin import auth, credentials

from . import members
from .config import Settings
from .db import Db
from .errors import ApiError

_firebase_lock = Lock()
_bearer = HTTPBearer(auto_error=False)


@dataclass
class AuthUser:
    uid: str
    email: str | None
    email_verified: bool
    name: str | None


class AuthVerifier(Protocol):
    def verify(self, id_token: str) -> AuthUser: ...


def init_firebase(settings: Settings) -> None:
    with _firebase_lock:
        try:
            firebase_admin.get_app()
        except ValueError:
            credential = credentials.Certificate(settings.google_credentials) if settings.google_credentials else None
            firebase_admin.initialize_app(credential)


class FakeVerifier:
    def verify(self, id_token: str) -> AuthUser:
        parts = id_token.split(":", 3)
        if len(parts) != 4 or parts[0] != "fake" or not parts[1]:
            raise ApiError(401, "unauthenticated", "Invalid ID token")
        _, uid, email, name = parts
        return AuthUser(uid, email or None, True, name or None)


class FirebaseVerifier:
    def __init__(self):
        self._app = firebase_admin.get_app()

    def verify(self, id_token: str) -> AuthUser:
        try:
            claims = auth.verify_id_token(id_token, app=self._app, clock_skew_seconds=10)
            return AuthUser(
                uid=claims["uid"],
                email=claims.get("email"),
                email_verified=claims.get("email_verified") is True,
                name=claims.get("name"),
            )
        except Exception as exc:
            raise ApiError(401, "unauthenticated", "Invalid ID token") from exc


def auth_user(
    request: Request,
    bearer: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> AuthUser:
    if bearer is None:
        raise ApiError(401, "unauthenticated", "Bearer ID token required")
    return request.app.state.verifier.verify(bearer.credentials)


SignedIn = Annotated[AuthUser, Depends(auth_user)]


def current_member(conn: Db, user: SignedIn) -> sqlite3.Row:
    member = members.by_uid(conn, user.uid)
    if member is None:
        raise ApiError(401, "session_required", "Open a session first")
    return member


CurrentMember = Annotated[sqlite3.Row, Depends(current_member)]


def require_cashier(member: CurrentMember) -> sqlite3.Row:
    if member["role"] != "cashier":
        raise ApiError(403, "forbidden", "Cashier access required")
    return member
