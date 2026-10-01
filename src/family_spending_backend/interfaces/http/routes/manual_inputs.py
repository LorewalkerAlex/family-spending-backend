"""Manual Evidence lifecycle API."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status

from family_spending_backend.application.context import RequestContext
from family_spending_backend.application.manual_input import ManualInputResult
from family_spending_backend.domain.manual import ManualEvidence, create_manual_evidence
from family_spending_backend.interfaces.http.contracts import (
    ERROR_RESPONSES,
    ApiListMeta,
    ApiListResponse,
    ApiMeta,
    ApiResponse,
    ManualInputData,
    ManualInputDeletionData,
    ManualInputMutationData,
    ManualInputWriteRequest,
    TransactionData,
)
from family_spending_backend.interfaces.http.dependencies import (
    ContainerDependency,
    get_request_context,
)

router = APIRouter(prefix="/manual-inputs", tags=["manual-inputs"], responses=ERROR_RESPONSES)
RequestContextDependency = Annotated[RequestContext, Depends(get_request_context)]


def _transaction_data(transaction: object) -> TransactionData:
    return TransactionData.model_validate(transaction, from_attributes=True)


def _mutation_data(result: ManualInputResult) -> ManualInputMutationData:
    return ManualInputMutationData(
        item=ManualInputData(
            evidence_id=result.evidence.evidence_id,
            source_record_id=result.source_record_id,
            transaction_type=result.evidence.transaction_type,
            transaction_date=result.evidence.transaction_date,
            amount=result.evidence.amount,
            currency=result.evidence.currency,
            description=result.evidence.description,
            transaction_id=result.transaction.id,
            source_role=result.source_role,
            transaction=_transaction_data(result.transaction),
        ),
        action=result.action,
        mutation_impact=result.impact.value,
    )


def _evidence(
    payload: ManualInputWriteRequest,
    *,
    evidence_id: str | None = None,
) -> ManualEvidence:
    return create_manual_evidence(
        evidence_id=evidence_id,
        transaction_type=payload.transaction_type,
        transaction_date=payload.transaction_date,
        amount=payload.amount,
        currency=payload.currency,
        description=payload.description,
    )


@router.get("", response_model=ApiListResponse[ManualInputData])
def list_manual_inputs(
    container: ContainerDependency,
    context: RequestContextDependency,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    sort: Literal["date_desc", "date_asc"] = "date_desc",
) -> ApiListResponse[ManualInputData]:
    model = container.runtime_state.read_model()
    links = {link.source_record_id: link for link in model.source_links}
    transactions = {item.id: item for item in model.transactions}
    items = []
    for source in model.source_records:
        if source.source_type != "manual":
            continue
        link = links.get(source.id)
        transaction = transactions.get(link.transaction_id) if link is not None else None
        items.append(
            ManualInputData(
                evidence_id=source.identity.evidence_identity,
                source_record_id=source.id,
                transaction_type=source.transaction_type,
                transaction_date=source.transaction_date,
                amount=source.amount,
                currency=source.currency,
                description=source.description,
                transaction_id=link.transaction_id if link is not None else None,
                source_role=link.role if link is not None else None,
                transaction=_transaction_data(transaction) if transaction is not None else None,
            )
        )
    items.sort(key=lambda item: item.transaction_date, reverse=sort == "date_desc")
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


@router.post(
    "",
    response_model=ApiResponse[ManualInputMutationData],
    status_code=status.HTTP_201_CREATED,
)
def create_manual_input(
    payload: ManualInputWriteRequest,
    container: ContainerDependency,
    context: RequestContextDependency,
) -> ApiResponse[ManualInputMutationData]:
    evidence = _evidence(payload)
    result = container.manual_input_service.create(evidence)
    return ApiResponse(data=_mutation_data(result), meta=ApiMeta(request_id=context.request_id))


@router.put("/{evidence_id}", response_model=ApiResponse[ManualInputMutationData])
def correct_manual_input(
    evidence_id: str,
    payload: ManualInputWriteRequest,
    container: ContainerDependency,
    context: RequestContextDependency,
) -> ApiResponse[ManualInputMutationData]:
    result = container.manual_input_service.correct(
        evidence_id,
        _evidence(payload, evidence_id=evidence_id),
    )
    return ApiResponse(data=_mutation_data(result), meta=ApiMeta(request_id=context.request_id))


@router.delete("/{evidence_id}", response_model=ApiResponse[ManualInputDeletionData])
def delete_manual_input(
    evidence_id: str,
    container: ContainerDependency,
    context: RequestContextDependency,
) -> ApiResponse[ManualInputDeletionData]:
    result = container.manual_input_service.delete(evidence_id)
    return ApiResponse(
        data=ManualInputDeletionData(
            evidence_id=result.evidence_id,
            source_record_id=result.source_record_id,
            transaction_id=result.transaction_id,
            transaction_removed=result.transaction_removed,
            mutation_impact=result.impact.value,
        ),
        meta=ApiMeta(request_id=context.request_id),
    )
