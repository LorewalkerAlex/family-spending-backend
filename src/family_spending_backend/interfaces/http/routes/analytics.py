"""Read-model-backed spending and financial analytics API."""

from collections.abc import Mapping
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from family_spending_backend.application.context import RequestContext
from family_spending_backend.interfaces.http.contracts import ApiMeta, ApiResponse
from family_spending_backend.interfaces.http.dependencies import (
    ContainerDependency,
    get_request_context,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])
RequestContextDependency = Annotated[RequestContext, Depends(get_request_context)]


def _json_data(value: object) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_data(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_data(item) for item in value]
    return value


@router.get("/spending", response_model=ApiResponse[dict[str, Any]])
def get_spending(
    container: ContainerDependency, context: RequestContextDependency
) -> ApiResponse[dict[str, Any]]:
    payload = _json_data(container.runtime_state.read_model().spending_projection.payload)
    return ApiResponse(data=payload, meta=ApiMeta(request_id=context.request_id))


@router.get("/financial", response_model=ApiResponse[dict[str, Any]])
def get_financial(
    container: ContainerDependency, context: RequestContextDependency
) -> ApiResponse[dict[str, Any]]:
    payload = _json_data(container.runtime_state.read_model().financial_projection.payload)
    return ApiResponse(data=payload, meta=ApiMeta(request_id=context.request_id))
