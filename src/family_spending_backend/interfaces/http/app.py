"""FastAPI application composition boundary."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import RequestResponseEndpoint

from family_spending_backend import __version__
from family_spending_backend.application.context import bind_request_id, reset_request_id
from family_spending_backend.bootstrap import build_container
from family_spending_backend.config import Settings, get_settings
from family_spending_backend.interfaces.http.errors import register_exception_handlers
from family_spending_backend.interfaces.http.routes.analytics import router as analytics_router
from family_spending_backend.interfaces.http.routes.feedback import router as feedback_router
from family_spending_backend.interfaces.http.routes.manual_inputs import (
    router as manual_inputs_router,
)
from family_spending_backend.interfaces.http.routes.mapping_reviews import (
    router as mapping_reviews_router,
)
from family_spending_backend.interfaces.http.routes.scheduled_inputs import (
    router as scheduled_inputs_router,
)
from family_spending_backend.interfaces.http.routes.system import router as system_router
from family_spending_backend.interfaces.http.routes.transactions import (
    router as transactions_router,
)

API_PREFIX = "/api/v1"
REQUEST_ID_HEADER = "X-Request-ID"


def _request_id(header_value: str | None) -> str:
    if header_value is not None:
        candidate = header_value.strip()
        if candidate and len(candidate) <= 128 and candidate.isprintable():
            return candidate
    return str(uuid4())


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    container = build_container(resolved_settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        with container.lifespan():
            yield

    app = FastAPI(
        title="Family Spending Backend API",
        version=__version__,
        lifespan=lifespan,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
    )
    app.state.container = container

    @app.middleware("http")
    async def request_context(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        request.state.request_id = _request_id(request.headers.get(REQUEST_ID_HEADER))
        token = bind_request_id(request.state.request_id)
        try:
            response = await call_next(request)
            response.headers[REQUEST_ID_HEADER] = request.state.request_id
            return response
        finally:
            reset_request_id(token)

    register_exception_handlers(app)
    app.include_router(system_router, prefix=API_PREFIX)
    app.include_router(analytics_router, prefix=API_PREFIX)
    app.include_router(feedback_router, prefix=API_PREFIX)
    app.include_router(scheduled_inputs_router, prefix=API_PREFIX)
    app.include_router(manual_inputs_router, prefix=API_PREFIX)
    app.include_router(mapping_reviews_router, prefix=API_PREFIX)
    app.include_router(transactions_router, prefix=API_PREFIX)
    return app
