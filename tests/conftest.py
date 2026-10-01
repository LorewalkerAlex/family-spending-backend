from collections.abc import AsyncIterator
from pathlib import Path

import httpx2
import pytest
from fastapi import FastAPI

from family_spending_backend.config import Settings
from family_spending_backend.interfaces.http.app import create_app


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def api_app(tmp_path: Path) -> tuple[FastAPI, Path]:
    data_root = tmp_path / "data"
    settings = Settings(
        _env_file=None,
        environment="test",
        data_root=data_root,
        schema_version="1",
        parser_version="cmb-v1",
    )
    return create_app(settings), data_root


@pytest.fixture
async def api_client(
    api_app: tuple[FastAPI, Path],
) -> AsyncIterator[tuple[httpx2.AsyncClient, Path]]:
    app, data_root = api_app

    async with app.router.lifespan_context(app):
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            yield client, data_root
