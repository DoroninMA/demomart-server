import logging

from fastapi import FastAPI

from .config import Settings
from .errors import install_error_handler

logger = logging.getLogger(__name__)


def create_app(settings: Settings) -> FastAPI:
    if settings.auth_mode == "fake":
        logger.warning("AUTH_MODE=fake — anyone can sign in, never use on a public server")

    app = FastAPI(title="DemoMart Loyalty")
    install_error_handler(app)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
