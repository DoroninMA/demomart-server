import logging
from contextlib import closing

from fastapi import FastAPI

from . import api_me, api_pos
from .auth import AuthVerifier, FakeVerifier, FirebaseVerifier, init_firebase
from .config import Settings
from .db import connect, init_schema
from .errors import install_error_handler
from .notify import BalanceListener, FcmNotifier

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings,
    verifier: AuthVerifier | None = None,
    listeners: list[BalanceListener] | None = None,
) -> FastAPI:
    if settings.auth_mode == "fake":
        logger.warning("AUTH_MODE=fake — anyone can sign in, never use on a public server")
    else:
        init_firebase(settings)

    if verifier is None:
        verifier = FakeVerifier() if settings.auth_mode == "fake" else FirebaseVerifier()

    with closing(connect(settings.database_path)) as conn:
        init_schema(conn)

    if listeners is None:
        listeners = [FcmNotifier()] if settings.auth_mode == "firebase" else []

    app = FastAPI(title="DemoMart Loyalty")
    app.state.settings = settings
    app.state.verifier = verifier
    app.state.listeners = listeners
    install_error_handler(app)
    app.include_router(api_me.router)
    app.include_router(api_pos.router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
