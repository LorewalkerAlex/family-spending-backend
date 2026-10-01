"""Product Feedback API."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status

from family_spending_backend.application.context import RequestContext
from family_spending_backend.domain.feedback import FeedbackContext
from family_spending_backend.interfaces.http.contracts import (
    ERROR_RESPONSES,
    ApiListMeta,
    ApiListResponse,
    ApiMeta,
    ApiResponse,
    FeedbackCreateRequest,
    FeedbackData,
    FeedbackStatusRequest,
)
from family_spending_backend.interfaces.http.dependencies import (
    ContainerDependency,
    get_request_context,
)

router = APIRouter(prefix="/feedback", tags=["feedback"], responses=ERROR_RESPONSES)
RequestContextDependency = Annotated[RequestContext, Depends(get_request_context)]


def _data(item: object) -> FeedbackData:
    return FeedbackData.model_validate(item, from_attributes=True)


@router.get("", response_model=ApiListResponse[FeedbackData])
def list_feedback(
    container: ContainerDependency,
    context: RequestContextDependency,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    status_filter: Annotated[Literal["open", "resolved"] | None, Query(alias="status")] = None,
    sort: Literal["created_desc", "created_asc"] = "created_desc",
) -> ApiListResponse[FeedbackData]:
    items = [_data(item) for item in container.feedback_service.list_items()]
    if status_filter is not None:
        items = [item for item in items if item.status == status_filter]
    items.sort(key=lambda item: item.created_at, reverse=sort == "created_desc")
    total = len(items)
    return ApiListResponse(
        data=items[offset : offset + limit],
        meta=ApiListMeta(
            request_id=context.request_id,
            offset=offset,
            limit=limit,
            total=total,
            sort=sort,
        ),
    )


@router.post("", response_model=ApiResponse[FeedbackData], status_code=status.HTTP_201_CREATED)
def create_feedback(
    payload: FeedbackCreateRequest,
    container: ContainerDependency,
    context: RequestContextDependency,
) -> ApiResponse[FeedbackData]:
    item = container.feedback_service.create(
        content=payload.content,
        context=FeedbackContext(**payload.context.model_dump()),
    )
    return ApiResponse(data=_data(item), meta=ApiMeta(request_id=context.request_id))


@router.patch("/{feedback_id}", response_model=ApiResponse[FeedbackData])
def update_feedback_status(
    feedback_id: str,
    payload: FeedbackStatusRequest,
    container: ContainerDependency,
    context: RequestContextDependency,
) -> ApiResponse[FeedbackData]:
    item = container.feedback_service.update_status(feedback_id, payload.status)
    return ApiResponse(data=_data(item), meta=ApiMeta(request_id=context.request_id))
