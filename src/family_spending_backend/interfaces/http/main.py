"""ASGI and console entry points."""

import uvicorn

from family_spending_backend.config import get_settings
from family_spending_backend.interfaces.http.app import create_app

app = create_app()


def run() -> None:
    settings = get_settings()
    uvicorn.run(
        "family_spending_backend.interfaces.http.main:app",
        host=settings.bind_host,
        port=settings.bind_port,
        workers=1,
    )
