"""Income, net-spending, and cash-flow projection."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from family_spending_backend.domain.transaction import Transaction
from family_spending_backend.projections.month_coverage import build_month_coverage
from family_spending_backend.projections.spending import SpendingStatistics

FINANCIAL_SUMMARY_SCHEMA_VERSION = 1
MINOR_UNIT_SCALE = Decimal("100")
ZERO = Decimal("0")


class FinancialProjectionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class FinancialProjection:
    payload: Mapping[str, object]


def _minor(value: Decimal, label: str) -> int:
    if not value.is_finite():
        raise FinancialProjectionError(f"{label} must be finite")
    minor = value * MINOR_UNIT_SCALE
    if minor != minor.to_integral_value():
        raise FinancialProjectionError(f"{label} has more than two decimal places")
    return int(minor)


def _non_negative_minor(value: Decimal, label: str) -> int:
    if value < ZERO:
        raise FinancialProjectionError(f"{label} must be non-negative")
    return _minor(value, label)


def _summary(rows: list[dict[str, object]]) -> dict[str, int]:
    income = sum(int(row["total_income_minor"]) for row in rows)
    spending = sum(int(row["total_spending_minor"]) for row in rows)
    return {
        "total_income_minor": income,
        "total_spending_minor": spending,
        "net_cash_flow_minor": income - spending,
        "income_transaction_count": sum(int(row["income_transaction_count"]) for row in rows),
        "spending_transaction_count": sum(int(row["spending_transaction_count"]) for row in rows),
        "month_count": len(rows),
    }


def build_financial_projection(
    transactions: tuple[Transaction, ...],
    spending_statistics: SpendingStatistics,
    statement_dates: frozenset[date],
) -> FinancialProjection:
    spending_by_month = {item.month: item for item in spending_statistics.months}
    income_by_month: dict[str, Decimal] = {}
    income_count: dict[str, int] = {}
    for transaction in transactions:
        if transaction.transaction_type != "income":
            continue
        if transaction.amount <= ZERO:
            raise FinancialProjectionError(
                f"Income Transaction {transaction.id!r} must have positive amount"
            )
        month = transaction.transaction_date.strftime("%Y-%m")
        income_by_month[month] = income_by_month.get(month, ZERO) + transaction.amount
        income_count[month] = income_count.get(month, 0) + 1
    months = tuple(sorted(set(spending_by_month) | set(income_by_month), reverse=True))
    coverage = {item.month: item for item in build_month_coverage(months, statement_dates)}
    rows: list[dict[str, object]] = []
    for month in months:
        spending = spending_by_month.get(month)
        total_spending = spending.total_spending if spending is not None else ZERO
        spending_count = spending.transaction_count if spending is not None else 0
        total_income = income_by_month.get(month, ZERO)
        rows.append(
            {
                "month": month,
                "spending_data_complete": coverage[month].is_complete,
                "show": coverage[month].show,
                "total_income_minor": _non_negative_minor(total_income, f"income {month}"),
                "income_transaction_count": income_count.get(month, 0),
                "total_spending_minor": _non_negative_minor(total_spending, f"spending {month}"),
                "spending_transaction_count": spending_count,
                "net_cash_flow_minor": _minor(total_income - total_spending, f"cash flow {month}"),
            }
        )
    all_summary = _summary(rows)
    expected_income = sum(income_by_month.values(), ZERO)
    expected = {
        "total_income_minor": _non_negative_minor(expected_income, "total income"),
        "total_spending_minor": _non_negative_minor(
            spending_statistics.total_spending, "total spending"
        ),
        "net_cash_flow_minor": _minor(
            expected_income - spending_statistics.total_spending, "net cash flow"
        ),
        "income_transaction_count": sum(income_count.values()),
        "spending_transaction_count": spending_statistics.transaction_count,
        "month_count": len(rows),
    }
    if all_summary != expected:
        raise FinancialProjectionError("Financial all-data summary does not reconcile")
    return FinancialProjection(
        {
            "schema_version": FINANCIAL_SUMMARY_SCHEMA_VERSION,
            "summary": {
                "all_data": all_summary,
                "shown_data": _summary([row for row in rows if bool(row["show"])]),
            },
            "months": rows,
        }
    )
