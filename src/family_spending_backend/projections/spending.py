"""Pure net-spending aggregation and stable payload projection."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from family_spending_backend.domain.enrichment import ResolvedEnrichment
from family_spending_backend.domain.refund import (
    NetConsumption,
    RefundReconciliationResult,
    reconcile_refunds,
)
from family_spending_backend.domain.source import SourceRecord
from family_spending_backend.domain.transaction import Transaction
from family_spending_backend.projections.month_coverage import (
    MonthCoverage,
    build_month_coverage,
)

STATISTICS_SCHEMA_VERSION = 2
MINOR_UNIT_SCALE = Decimal("100")
ZERO = Decimal("0")


class SpendingProjectionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CategoryStatistics:
    category: str
    spending: Decimal
    transaction_count: int


@dataclass(frozen=True, slots=True)
class MerchantStatistics:
    merchant_name: str | None
    display_name: str
    is_unclassified: bool
    spending: Decimal
    transaction_count: int


@dataclass(frozen=True, slots=True)
class MonthlySpendingStatistics:
    month: str
    total_spending: Decimal
    transaction_count: int
    categories: tuple[CategoryStatistics, ...]
    merchants: tuple[MerchantStatistics, ...]


@dataclass(frozen=True, slots=True)
class SpendingStatistics:
    total_spending: Decimal
    transaction_count: int
    months: tuple[MonthlySpendingStatistics, ...]


@dataclass(frozen=True, slots=True)
class SpendingProjectionSummary:
    zero_amount_transactions: int
    refund_transactions: int
    same_merchant_refund_matches: int
    same_merchant_matched_amount: Decimal
    net_consumption_transactions: int
    fully_refunded_transactions: int
    partially_refunded_transactions: int
    unmatched_refund_count: int
    unmatched_refund_amount: Decimal
    unclassified_net_transactions: int
    months: int
    total_net_spending: Decimal
    shown_months: int
    shown_net_spending: Decimal


@dataclass(frozen=True, slots=True)
class SpendingProjection:
    summary: SpendingProjectionSummary
    statistics: SpendingStatistics
    month_coverage: tuple[MonthCoverage, ...]
    refund: RefundReconciliationResult
    payload: Mapping[str, object]


@dataclass(slots=True)
class _Aggregate:
    spending: Decimal = ZERO
    transaction_count: int = 0

    def add(self, spending: Decimal) -> None:
        self.spending += spending
        self.transaction_count += 1


@dataclass(slots=True)
class _MonthAggregate:
    total: _Aggregate
    categories: dict[str, _Aggregate]
    merchants: dict[tuple[str | None, str, bool], _Aggregate]


def aggregate_spending(
    net_consumption: tuple[NetConsumption, ...],
    transactions_by_id: Mapping[str, Transaction],
    enrichments_by_transaction_id: Mapping[str, ResolvedEnrichment],
) -> SpendingStatistics:
    by_month: dict[str, _MonthAggregate] = {}
    for consumption in net_consumption:
        if consumption.spending <= ZERO:
            raise SpendingProjectionError(
                f"Net consumption must be positive: {consumption.transaction_id!r}"
            )
        try:
            transaction = transactions_by_id[consumption.transaction_id]
            enrichment = enrichments_by_transaction_id[consumption.transaction_id]
        except KeyError as exc:
            raise SpendingProjectionError(
                f"Net consumption references missing state {consumption.transaction_id!r}"
            ) from exc
        month = transaction.transaction_date.strftime("%Y-%m")
        bucket = by_month.setdefault(month, _MonthAggregate(_Aggregate(), {}, {}))
        bucket.total.add(consumption.spending)
        bucket.categories.setdefault(enrichment.category, _Aggregate()).add(consumption.spending)
        merchant_key = (
            enrichment.merchant_name,
            enrichment.display_name,
            enrichment.merchant_name is None,
        )
        bucket.merchants.setdefault(merchant_key, _Aggregate()).add(consumption.spending)

    months: list[MonthlySpendingStatistics] = []
    for month in sorted(by_month, reverse=True):
        bucket = by_month[month]
        categories = tuple(
            CategoryStatistics(name, value.spending, value.transaction_count)
            for name, value in sorted(
                bucket.categories.items(), key=lambda item: (-item[1].spending, item[0])
            )
        )
        merchants = tuple(
            MerchantStatistics(name, display, unclassified, value.spending, value.transaction_count)
            for (name, display, unclassified), value in sorted(
                bucket.merchants.items(),
                key=lambda item: (-item[1].spending, item[0][1], item[0][0] or ""),
            )
        )
        if (
            sum((item.spending for item in categories), ZERO) != bucket.total.spending
            or sum((item.spending for item in merchants), ZERO) != bucket.total.spending
            or sum(item.transaction_count for item in categories) != bucket.total.transaction_count
            or sum(item.transaction_count for item in merchants) != bucket.total.transaction_count
        ):
            raise SpendingProjectionError(f"Monthly spending does not reconcile for {month}")
        months.append(
            MonthlySpendingStatistics(
                month,
                bucket.total.spending,
                bucket.total.transaction_count,
                categories,
                merchants,
            )
        )
    return SpendingStatistics(
        sum((item.total_spending for item in months), ZERO),
        sum(item.transaction_count for item in months),
        tuple(months),
    )


def _minor(value: Decimal, label: str) -> int:
    if not value.is_finite() or value < ZERO:
        raise SpendingProjectionError(f"{label} must be finite and non-negative")
    minor = value * MINOR_UNIT_SCALE
    if minor != minor.to_integral_value():
        raise SpendingProjectionError(f"{label} has more than two decimal places")
    return int(minor)


def _summary(total: Decimal, count: int, months: int) -> dict[str, int]:
    return {
        "total_spending_minor": _minor(total, "spending"),
        "transaction_count": count,
        "month_count": months,
    }


def serialize_spending_statistics(
    statistics: SpendingStatistics, coverage: tuple[MonthCoverage, ...]
) -> dict[str, object]:
    coverage_by_month = {item.month: item for item in coverage}
    if len(coverage_by_month) != len(coverage):
        raise SpendingProjectionError("Duplicate month coverage")
    if set(coverage_by_month) != {item.month for item in statistics.months}:
        raise SpendingProjectionError("Month coverage does not match statistics")
    shown = tuple(item for item in statistics.months if coverage_by_month[item.month].show)
    return {
        "schema_version": STATISTICS_SCHEMA_VERSION,
        "summary": {
            "all_data": _summary(
                statistics.total_spending,
                statistics.transaction_count,
                len(statistics.months),
            ),
            "shown_data": _summary(
                sum((item.total_spending for item in shown), ZERO),
                sum(item.transaction_count for item in shown),
                len(shown),
            ),
        },
        "months": [
            {
                "month": month.month,
                "is_complete": coverage_by_month[month.month].is_complete,
                "show": coverage_by_month[month.month].show,
                "total_spending_minor": _minor(month.total_spending, month.month),
                "transaction_count": month.transaction_count,
                "categories": [
                    {
                        "category": item.category,
                        "spending_minor": _minor(item.spending, item.category),
                        "transaction_count": item.transaction_count,
                    }
                    for item in month.categories
                ],
                "merchants": [
                    {
                        "merchant_name": item.merchant_name,
                        "display_name": item.display_name,
                        "is_unclassified": item.is_unclassified,
                        "spending_minor": _minor(item.spending, item.display_name),
                        "transaction_count": item.transaction_count,
                    }
                    for item in month.merchants
                ],
            }
            for month in statistics.months
        ],
    }


def build_spending_projection(
    transactions: tuple[Transaction, ...],
    authoritative_sources_by_transaction_id: Mapping[str, SourceRecord],
    enrichments_by_transaction_id: Mapping[str, ResolvedEnrichment],
    statement_dates: frozenset[date],
) -> SpendingProjection:
    transactions_by_id = {item.id: item for item in transactions}
    if len(transactions_by_id) != len(transactions):
        raise SpendingProjectionError("Duplicate Transaction id")
    refund = reconcile_refunds(
        transactions, authoritative_sources_by_transaction_id, enrichments_by_transaction_id
    )
    statistics = aggregate_spending(
        refund.net_consumption, transactions_by_id, enrichments_by_transaction_id
    )
    coverage = build_month_coverage(
        tuple(item.month for item in statistics.months), statement_dates
    )
    payload = serialize_spending_statistics(statistics, coverage)
    shown_names = {item.month for item in coverage if item.show}
    shown = tuple(item for item in statistics.months if item.month in shown_names)
    summary = SpendingProjectionSummary(
        zero_amount_transactions=refund.zero_amount_transactions,
        refund_transactions=refund.refund_transactions,
        same_merchant_refund_matches=refund.same_merchant_refund_matches,
        same_merchant_matched_amount=refund.same_merchant_matched_amount,
        net_consumption_transactions=len(refund.net_consumption),
        fully_refunded_transactions=refund.fully_refunded_transactions,
        partially_refunded_transactions=refund.partially_refunded_transactions,
        unmatched_refund_count=refund.unmatched_refund_count,
        unmatched_refund_amount=refund.unmatched_refund_amount,
        unclassified_net_transactions=sum(
            enrichments_by_transaction_id[item.transaction_id].is_unclassified
            for item in refund.net_consumption
        ),
        months=len(statistics.months),
        total_net_spending=statistics.total_spending,
        shown_months=len(shown),
        shown_net_spending=sum((item.total_spending for item in shown), ZERO),
    )
    return SpendingProjection(summary, statistics, coverage, refund, payload)
