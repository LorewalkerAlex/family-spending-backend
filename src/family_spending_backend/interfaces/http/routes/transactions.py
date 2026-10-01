"""Transaction query and Enrichment decision API."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from family_spending_backend.application.context import RequestContext
from family_spending_backend.application.enrichment import UNSET, EnrichmentMutationResult
from family_spending_backend.application.errors import ApplicationNotFoundError
from family_spending_backend.domain.transaction import Transaction
from family_spending_backend.interfaces.http.contracts import (
    ERROR_RESPONSES,
    ApiListMeta,
    ApiListResponse,
    ApiMeta,
    ApiResponse,
    EnrichmentData,
    EnrichmentDecisionData,
    EnrichmentMutationData,
    EnrichmentPatchRequest,
    TransactionData,
    TransactionViewData,
)
from family_spending_backend.interfaces.http.dependencies import (
    ContainerDependency,
    get_request_context,
)
from family_spending_backend.read_model import HouseholdReadModel

router = APIRouter(prefix="/transactions", tags=["transactions"], responses=ERROR_RESPONSES)
RequestContextDependency = Annotated[RequestContext, Depends(get_request_context)]


def _enrichment_data(enrichment: object) -> EnrichmentData:
    return EnrichmentData.model_validate(enrichment, from_attributes=True)


def _transaction_view(model: HouseholdReadModel, transaction: Transaction) -> TransactionViewData:
    transaction_id = transaction.id
    source = model.indexes.authoritative_source_by_transaction_id[transaction_id]
    return TransactionViewData(
        transaction=TransactionData.model_validate(transaction, from_attributes=True),
        authoritative_source_record_id=source.id,
        description=source.description,
        enrichment=_enrichment_data(model.indexes.enrichment_by_transaction_id[transaction_id]),
    )


def _transaction_views(model: HouseholdReadModel) -> list[TransactionViewData]:
    return [_transaction_view(model, transaction) for transaction in model.transactions]


def _mutation_data(result: EnrichmentMutationResult) -> EnrichmentMutationData:
    decision = result.decision
    return EnrichmentMutationData(
        transaction_id=result.transaction_id,
        decision=(
            EnrichmentDecisionData(
                merchant_override=decision.merchant_override,
                category_override=decision.category_override,
                note=decision.note,
            )
            if decision is not None
            else None
        ),
        enrichment=_enrichment_data(result.enrichment),
        mutation_impact=result.impact.value,
    )


@router.get("", response_model=ApiListResponse[TransactionViewData])
def list_transactions(
    container: ContainerDependency,
    context: RequestContextDependency,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    transaction_type: Literal["income", "expense"] | None = None,
    description: str | None = None,
    category: str | None = None,
    is_unclassified: bool | None = None,
    sort: Literal["date_desc", "date_asc", "amount_desc", "amount_asc"] = "date_desc",
) -> ApiListResponse[TransactionViewData]:
    items = _transaction_views(container.runtime_state.read_model())
    if transaction_type is not None:
        items = [item for item in items if item.transaction.transaction_type == transaction_type]
    if description is not None:
        items = [item for item in items if item.description == description]
    if category is not None:
        items = [item for item in items if item.enrichment.category == category]
    if is_unclassified is not None:
        items = [item for item in items if item.enrichment.is_unclassified is is_unclassified]
    key, reverse = {
        "date_desc": (lambda item: item.transaction.transaction_date, True),
        "date_asc": (lambda item: item.transaction.transaction_date, False),
        "amount_desc": (lambda item: item.transaction.amount, True),
        "amount_asc": (lambda item: item.transaction.amount, False),
    }[sort]
    items.sort(key=key, reverse=reverse)
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


@router.get("/{transaction_id}", response_model=ApiResponse[TransactionViewData])
def get_transaction(
    transaction_id: str,
    container: ContainerDependency,
    context: RequestContextDependency,
) -> ApiResponse[TransactionViewData]:
    model = container.runtime_state.read_model()
    transaction = model.indexes.transaction_by_id.get(transaction_id)
    if transaction is None:
        raise ApplicationNotFoundError(f"Transaction {transaction_id!r} does not exist")
    return ApiResponse(
        data=_transaction_view(model, transaction),
        meta=ApiMeta(request_id=context.request_id),
    )


@router.patch(
    "/{transaction_id}/enrichment",
    response_model=ApiResponse[EnrichmentMutationData],
)
def update_enrichment(
    transaction_id: str,
    payload: EnrichmentPatchRequest,
    container: ContainerDependency,
    context: RequestContextDependency,
) -> ApiResponse[EnrichmentMutationData]:
    fields = payload.model_fields_set
    result = container.enrichment_service.update(
        transaction_id,
        merchant_override=payload.merchant_override if "merchant_override" in fields else UNSET,
        category_override=payload.category_override if "category_override" in fields else UNSET,
        note=payload.note if "note" in fields else UNSET,
    )
    return ApiResponse(data=_mutation_data(result), meta=ApiMeta(request_id=context.request_id))
