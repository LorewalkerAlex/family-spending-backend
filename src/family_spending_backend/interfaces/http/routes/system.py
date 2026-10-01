"""Health and operational status routes."""

from typing import Annotated

from fastapi import APIRouter, Depends

from family_spending_backend import __version__
from family_spending_backend.application.context import RequestContext
from family_spending_backend.interfaces.http.contracts import (
    ERROR_RESPONSES,
    ApiMeta,
    ApiResponse,
    HealthData,
    RuntimeCountsData,
    RuntimeStatusData,
)
from family_spending_backend.interfaces.http.dependencies import (
    ContainerDependency,
    get_request_context,
)

router = APIRouter(tags=["system"], responses=ERROR_RESPONSES)
RequestContextDependency = Annotated[RequestContext, Depends(get_request_context)]


@router.get("/health", response_model=ApiResponse[HealthData])
def health(
    context: RequestContextDependency,
) -> ApiResponse[HealthData]:
    return ApiResponse(
        data=HealthData(
            status="ok",
            service="family-spending-backend",
            version=__version__,
        ),
        meta=ApiMeta(request_id=context.request_id),
    )


@router.get("/runtime/status", response_model=ApiResponse[RuntimeStatusData])
def runtime_status(
    container: ContainerDependency,
    context: RequestContextDependency,
) -> ApiResponse[RuntimeStatusData]:
    snapshot = container.runtime_state.snapshot()
    return ApiResponse(
        data=RuntimeStatusData(
            phase=snapshot.phase,
            started_at=snapshot.started_at,
            generation=snapshot.generation,
            queued_mutations=snapshot.queued_mutations,
            last_successful_mutation=snapshot.last_successful_mutation,
            last_failed_mutation=snapshot.last_failed_mutation,
            last_imap_poll=snapshot.last_imap_poll,
            last_scheduler_tick=snapshot.last_scheduler_tick,
            parser_cache_hits=snapshot.parser_cache_hits,
            parser_cache_misses=snapshot.parser_cache_misses,
            counts=RuntimeCountsData(
                source_records=snapshot.counts.source_records,
                transactions=snapshot.counts.transactions,
                enrichments=snapshot.counts.enrichments,
                mapping_reviews=snapshot.counts.mapping_reviews,
                feedback=snapshot.counts.feedback,
            ),
            schema_version=snapshot.schema_version,
            parser_version=snapshot.parser_version,
        ),
        meta=ApiMeta(request_id=context.request_id),
    )
