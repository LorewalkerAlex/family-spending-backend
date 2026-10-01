from datetime import date
from decimal import Decimal

import pytest

from family_spending_backend.application.models import (
    FinanceState,
    statement_dates_for_reconciled_evidence,
)
from family_spending_backend.domain.enrichment import resolve_enrichment
from family_spending_backend.domain.mapping import MappingCatalog
from family_spending_backend.domain.refund import reconcile_refunds
from family_spending_backend.domain.source import SourceIdentity, SourceRecord
from family_spending_backend.domain.transaction import (
    SourceLink,
    transaction_from_source_record,
)
from family_spending_backend.projections.financial import (
    FinancialProjectionError,
    build_financial_projection,
)
from family_spending_backend.projections.month_coverage import build_month_coverage
from family_spending_backend.projections.spending import build_spending_projection
from family_spending_backend.read_model import HouseholdReadModel


def source(
    key: str,
    when: str,
    amount: str,
    description: str,
    *,
    transaction_type: str = "expense",
) -> SourceRecord:
    return SourceRecord(
        SourceIdentity("manual", key, "record"),
        transaction_type,
        date.fromisoformat(when),
        Decimal(amount),
        "CNY",
        description,
    )


def state(sources: tuple[SourceRecord, ...], mappings: MappingCatalog):
    transactions = tuple(transaction_from_source_record(item) for item in sources)
    source_by_transaction = dict(zip((item.id for item in transactions), sources, strict=True))
    enrichments = {
        item.id: resolve_enrichment(item, source_by_transaction[item.id], mappings)
        for item in transactions
    }
    return transactions, source_by_transaction, enrichments


def test_refund_netting_preserves_purchase_identity_and_reports_unmatched() -> None:
    mappings = MappingCatalog({"shop": "Shop"}, {"Shop": "daily"}, frozenset({"daily"}))
    sources = (
        source("purchase", "2026-01-02", "300", "shop"),
        source("partial", "2026-01-10", "-100", "shop"),
        source("unmatched", "2026-01-11", "-250", "shop"),
    )
    transactions, sources_by_id, enrichments = state(sources, mappings)
    result = reconcile_refunds(transactions, sources_by_id, enrichments)
    assert result.net_consumption == ()
    assert result.fully_refunded_transactions == 1
    assert result.unmatched_refund_count == 1
    assert result.unmatched_refund_amount == Decimal("50")


def test_spending_and_financial_projection_match_stable_minor_unit_schema() -> None:
    mappings = MappingCatalog(
        {"appliance": "Appliance", "food": "Food"},
        {"Appliance": "Home", "Food": "Dining"},
        frozenset({"Home", "Dining"}),
    )
    sources = (
        source("purchase", "2025-12-01", "3000", "appliance"),
        source("refund", "2026-01-01", "-1000", "appliance"),
        source("food", "2026-01-02", "20", "food"),
        source("unknown", "2026-01-03", "30", "unmapped"),
        source("income", "2026-01-05", "1000", "salary", transaction_type="income"),
    )
    transactions, sources_by_id, enrichments = state(sources, mappings)
    statement_dates = frozenset({date(2025, 12, 10), date(2026, 1, 10), date(2026, 2, 10)})
    spending = build_spending_projection(transactions, sources_by_id, enrichments, statement_dates)
    financial = build_financial_projection(transactions, spending.statistics, statement_dates)
    assert spending.summary.total_net_spending == Decimal("2050")
    assert spending.summary.partially_refunded_transactions == 1
    assert spending.summary.unclassified_net_transactions == 1
    assert spending.payload["summary"]["all_data"]["total_spending_minor"] == 205000
    assert financial.payload["summary"]["all_data"] == {
        "total_income_minor": 100000,
        "total_spending_minor": 205000,
        "net_cash_flow_minor": -105000,
        "income_transaction_count": 1,
        "spending_transaction_count": 3,
        "month_count": 2,
    }


def test_month_coverage_and_positive_income_invariant() -> None:
    coverage = build_month_coverage(
        ("2026-01", "2026-02"),
        frozenset({date(2026, 1, 10), date(2026, 2, 10)}),
    )
    assert tuple(item.show for item in coverage) == (True, False)
    bad_source = source("bad", "2026-01-01", "0", "salary", transaction_type="income")
    bad = (transaction_from_source_record(bad_source),)
    empty = build_spending_projection(
        bad,
        {bad[0].id: bad_source},
        {bad[0].id: resolve_enrichment(bad[0], bad_source, MappingCatalog.empty())},
        frozenset(),
    )
    with pytest.raises(FinancialProjectionError, match="positive amount"):
        build_financial_projection(bad, empty.statistics, frozenset())


def test_statement_date_is_visible_only_after_all_evidence_records_are_reconciled() -> None:
    first = source("shared", "2026-01-01", "10", "shop")
    second = SourceRecord(
        SourceIdentity("manual", "shared", "second"),
        "expense",
        date(2026, 1, 2),
        Decimal("20"),
        "CNY",
        "shop",
    )
    statement_dates = {"shared": date(2026, 1, 10)}
    first_link = SourceLink(transaction_from_source_record(first).id, first.id, "authoritative")
    second_link = SourceLink(
        transaction_from_source_record(second).id,
        second.id,
        "authoritative",
    )

    assert not statement_dates_for_reconciled_evidence(
        (first, second),
        (first_link,),
        statement_dates,
    )
    assert statement_dates_for_reconciled_evidence(
        (first, second),
        (first_link, second_link),
        statement_dates,
    ) == frozenset({date(2026, 1, 10)})


def test_read_model_publishes_immutable_projection_payloads_and_query_indexes() -> None:
    record = source("indexed", "2026-01-01", "10", "shop")
    transaction = transaction_from_source_record(record)
    link = SourceLink(transaction.id, record.id, "authoritative")
    model = HouseholdReadModel.from_states(FinanceState((record,), (transaction,), (link,)))

    assert model.indexes.transaction_by_id[transaction.id] == transaction
    assert model.indexes.transaction_ids_by_month["2026-01"] == (transaction.id,)
    assert model.indexes.unclassified_transaction_ids == (transaction.id,)
    with pytest.raises(TypeError):
        model.indexes.transaction_by_id["other"] = transaction  # type: ignore[index]
    with pytest.raises(TypeError):
        model.spending_projection.payload["schema_version"] = 99  # type: ignore[index]
