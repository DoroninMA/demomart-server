import logging
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager, closing
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import api_me, api_pos
from .auth import AuthVerifier, FakeVerifier, FirebaseVerifier, init_firebase
from .config import Settings
from .db import connect, init_schema
from .errors import install_error_handler
from .notify import BalanceListener, FcmNotifier
from .wallet_api import WalletApi
from .wallet_service import WalletService, WalletUpdater

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings,
    verifier: AuthVerifier | None = None,
    listeners: list[BalanceListener] | None = None,
    *,
    wallet: WalletService | None = None,
    wallet_api: WalletApi | None = None,
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

    executor = None
    if settings.wallet.enabled:
        if wallet is None:
            wallet = WalletService.from_settings(settings.wallet, wallet_api)
        executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="wallet")
        listeners = [*listeners, WalletUpdater.for_service(wallet, executor, settings.database_path)]
    else:
        wallet = None

    @asynccontextmanager
    async def lifespan(_app):
        try:
            yield
        finally:
            if executor is not None:
                executor.shutdown(wait=False, cancel_futures=True)

    app = FastAPI(title="DemoMart Loyalty", lifespan=lifespan)
    app.state.settings = settings
    app.state.verifier = verifier
    app.state.listeners = listeners
    app.state.wallet = wallet
    install_error_handler(app)
    app.include_router(api_me.router)
    app.include_router(api_pos.router)
    app.mount("/static", StaticFiles(directory=Path(__file__).with_name("static")), name="static")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
