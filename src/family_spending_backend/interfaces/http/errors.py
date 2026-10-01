"""Unified API V1 exception mapping."""

import logging
from dataclasses import dataclass

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from family_spending_backend.application.errors import (
    ApplicationConflictError,
    ApplicationNotFoundError,
    ApplicationValidationError,
)
from family_spending_backend.domain.errors import DomainInvariantError
from family_spending_backend.interfaces.http.contracts import (
    ApiErrorBody,
    ErrorDetail,
    ErrorResponse,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ApiError(Exception):
    status_code: int
    code: str
    message: str
    details: tuple[ErrorDetail, ...] = ()


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "unavailable")


def _response(
    *,
    request: Request,
    status_code: int,
    code: str,
    message: str,
    details: list[ErrorDetail] | None = None,
) -> JSONResponse:
    request_id = _request_id(request)
    body = ErrorResponse(
        error=ApiErrorBody(
            code=code,
            message=message,
            request_id=request_id,
            details=details,
        )
    )
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(mode="json"),
        headers={"X-Request-ID": request_id},
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApplicationNotFoundError)
    async def handle_not_found(
        request: Request,
        error: ApplicationNotFoundError,
    ) -> JSONResponse:
        return _response(
            request=request,
            status_code=404,
            code="resource.not_found",
            message=str(error),
        )

    @app.exception_handler(ApplicationConflictError)
    async def handle_conflict(
        request: Request,
        error: ApplicationConflictError,
    ) -> JSONResponse:
        return _response(
            request=request,
            status_code=409,
            code="state.conflict",
            message=str(error),
        )

    @app.exception_handler(ApplicationValidationError)
    async def handle_application_validation(
        request: Request,
        error: ApplicationValidationError,
    ) -> JSONResponse:
        return _response(
            request=request,
            status_code=422,
            code="application.invalid",
            message=str(error),
        )

    @app.exception_handler(DomainInvariantError)
    async def handle_domain_invariant(
        request: Request,
        error: DomainInvariantError,
    ) -> JSONResponse:
        return _response(
            request=request,
            status_code=422,
            code="domain.invalid",
            message=str(error),
        )

    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, error: ApiError) -> JSONResponse:
        return _response(
            request=request,
            status_code=error.status_code,
            code=error.code,
            message=error.message,
            details=list(error.details) or None,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        details = [
            ErrorDetail(
                location=list(item["loc"]),
                message=item["msg"],
                type=item["type"],
            )
            for item in error.errors()
        ]
        return _response(
            request=request,
            status_code=422,
            code="request.validation_failed",
            message="The request is invalid.",
            details=details,
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(
        request: Request,
        error: StarletteHTTPException,
    ) -> JSONResponse:
        code = "http.not_found" if error.status_code == 404 else "http.error"
        message = (
            "The requested resource was not found."
            if error.status_code == 404
            else str(error.detail)
        )
        return _response(
            request=request,
            status_code=error.status_code,
            code=code,
            message=message,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, error: Exception) -> JSONResponse:
        logger.exception("Unhandled request failure", exc_info=error)
        return _response(
            request=request,
            status_code=500,
            code="internal.error",
            message="An unexpected error occurred.",
        )
