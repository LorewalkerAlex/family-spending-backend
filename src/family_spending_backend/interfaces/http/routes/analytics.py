"""Read-model-backed spending and financial analytics API."""

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends

from family_spending_backend.application.context import RequestContext
from family_spending_backend.domain.transaction import Transaction
from family_spending_backend.interfaces.http.contracts import (
    ApiMeta,
    ApiResponse,
    FinancialAnalyticsData,
    SpendingAnalyticsData,
    SpendingReconciliationData,
)
from family_spending_backend.interfaces.http.dependencies import (
    ContainerDependency,
    get_request_context,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])
RequestContextDependency = Annotated[RequestContext, Depends(get_request_context)]


def _minor(value: Decimal) -> int:
    return int(value * Decimal("100"))


def _analytics_currency(transactions: tuple[Transaction, ...]) -> str | None:
    currencies = {item.currency for item in transactions}
    return next(iter(currencies)) if len(currencies) == 1 else None


@router.get("/spending", response_model=ApiResponse[SpendingAnalyticsData])
def get_spending(
    container: ContainerDependency, context: RequestContextDependency
) -> ApiResponse[SpendingAnalyticsData]:
    model = container.runtime_state.read_model()
    projection = model.spending_projection
    summary = projection.summary
    reconciliation = SpendingReconciliationData(
        zero_amount_transactions=summary.zero_amount_transactions,
        refund_transactions=summary.refund_transactions,
        same_merchant_refund_matches=summary.same_merchant_refund_matches,
        same_merchant_matched_amount_minor=_minor(summary.same_merchant_matched_amount),
        net_consumption_transactions=summary.net_consumption_transactions,
        fully_refunded_transactions=summary.fully_refunded_transactions,
        partially_refunded_transactions=summary.partially_refunded_transactions,
        unmatched_refund_count=summary.unmatched_refund_count,
        unmatched_refund_amount_minor=_minor(summary.unmatched_refund_amount),
        unclassified_net_transactions=summary.unclassified_net_transactions,
    )
    data = SpendingAnalyticsData.model_validate(
        {
            **projection.payload,
            "currency": _analytics_currency(model.transactions),
            "reconciliation": reconciliation,
        }
    )
    return ApiResponse(data=data, meta=ApiMeta(request_id=context.request_id))


@router.get("/financial", response_model=ApiResponse[FinancialAnalyticsData])
def get_financial(
    container: ContainerDependency, context: RequestContextDependency
) -> ApiResponse[FinancialAnalyticsData]:
    model = container.runtime_state.read_model()
    payload = model.financial_projection.payload
    data = FinancialAnalyticsData.model_validate(
        {**payload, "currency": _analytics_currency(model.transactions)}
    )
    return ApiResponse(data=data, meta=ApiMeta(request_id=context.request_id))
