"""Scheduled Input rule and execution API."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status

from family_spending_backend.application.context import RequestContext
from family_spending_backend.interfaces.http.contracts import (
    ERROR_RESPONSES,
    ApiListMeta,
    ApiListResponse,
    ApiMeta,
    ApiResponse,
    ScheduledOccurrenceData,
    ScheduledRuleData,
    ScheduledRuleWriteRequest,
    ScheduledRunData,
    ScheduledRunRequest,
)
from family_spending_backend.interfaces.http.dependencies import (
    ContainerDependency,
    get_request_context,
)

router = APIRouter(prefix="/scheduled-inputs", tags=["scheduled-inputs"], responses=ERROR_RESPONSES)
RequestContextDependency = Annotated[RequestContext, Depends(get_request_context)]


def _rule_data(item: object) -> ScheduledRuleData:
    return ScheduledRuleData.model_validate(item, from_attributes=True)


@router.get("", response_model=ApiListResponse[ScheduledRuleData])
def list_rules(
    container: ContainerDependency,
    context: RequestContextDependency,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    enabled: bool | None = None,
    sort: Literal["next_date_asc", "next_date_desc"] = "next_date_asc",
) -> ApiListResponse[ScheduledRuleData]:
    service = container.scheduled_input_service
    items = [_rule_data(item) for item in service.list_views()]
    if enabled is not None:
        items = [item for item in items if item.enabled is enabled]
    items.sort(key=lambda item: item.next_date, reverse=sort == "next_date_desc")
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


@router.post("", response_model=ApiResponse[ScheduledRuleData], status_code=status.HTTP_201_CREATED)
def create_rule(
    payload: ScheduledRuleWriteRequest,
    container: ContainerDependency,
    context: RequestContextDependency,
) -> ApiResponse[ScheduledRuleData]:
    item = container.scheduled_input_service.create_rule(**payload.model_dump())
    return ApiResponse(data=_rule_data(item), meta=ApiMeta(request_id=context.request_id))


@router.put("/{rule_id}", response_model=ApiResponse[ScheduledRuleData])
def update_rule(
    rule_id: str,
    payload: ScheduledRuleWriteRequest,
    container: ContainerDependency,
    context: RequestContextDependency,
) -> ApiResponse[ScheduledRuleData]:
    item = container.scheduled_input_service.update_rule(rule_id, **payload.model_dump())
    return ApiResponse(data=_rule_data(item), meta=ApiMeta(request_id=context.request_id))


@router.delete("/{rule_id}", response_model=ApiResponse[ScheduledRuleData])
def delete_rule(
    rule_id: str,
    container: ContainerDependency,
    context: RequestContextDependency,
) -> ApiResponse[ScheduledRuleData]:
    item = container.scheduled_input_service.delete_rule(rule_id)
    return ApiResponse(data=_rule_data(item), meta=ApiMeta(request_id=context.request_id))


@router.post("/run-due", response_model=ApiResponse[ScheduledRunData])
def run_due(
    payload: ScheduledRunRequest,
    container: ContainerDependency,
    context: RequestContextDependency,
) -> ApiResponse[ScheduledRunData]:
    result = container.scheduled_input_service.run_due(payload.as_of)
    return ApiResponse(
        data=ScheduledRunData(
            occurrences=[
                ScheduledOccurrenceData.model_validate(item, from_attributes=True)
                for item in result.occurrences
            ],
            mutation_impact=result.impact.value,
        ),
        meta=ApiMeta(request_id=context.request_id),
    )
