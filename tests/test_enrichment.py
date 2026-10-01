from datetime import date
from decimal import Decimal

import pytest

from family_spending_backend.domain.enrichment import (
    INCOME_DEFAULT_CATEGORY,
    OTHER_EXPENSE_REVIEW,
    EnrichmentDecision,
    resolve_enrichment,
    resolve_enrichments,
)
from family_spending_backend.domain.errors import DomainInvariantError
from family_spending_backend.domain.mapping import (
    UNCLASSIFIED_CATEGORY,
    MappingCatalog,
)
from family_spending_backend.domain.source import SourceIdentity, SourceRecord
from family_spending_backend.domain.transaction import transaction_from_source_record


def source(
    description: str | None = "咖啡订单", *, transaction_type: str = "expense"
) -> SourceRecord:
    return SourceRecord(
        identity=SourceIdentity("manual", f"evidence-{description}", "record"),
        transaction_type=transaction_type,
        transaction_date=date(2026, 9, 1),
        amount=Decimal("35.00"),
        currency="CNY",
        description=description,
    )


def catalog(category: str = "餐饮") -> MappingCatalog:
    return MappingCatalog(
        {"咖啡订单": "街角咖啡"},
        {"街角咖啡": category},
        frozenset({category}),
    )


def test_mapping_catalog_requires_exact_merchant_and_category_sets() -> None:
    with pytest.raises(DomainInvariantError, match="merchant sets"):
        MappingCatalog({"coffee": "Cafe"}, {}, frozenset())
    with pytest.raises(DomainInvariantError, match="categories must match"):
        MappingCatalog({"coffee": "Cafe"}, {"Cafe": "Food"}, frozenset({"Food", "Extra"}))
    with pytest.raises(DomainInvariantError, match="runtime state"):
        MappingCatalog({"coffee": "Cafe"}, {"Cafe": "待分类"}, frozenset({"待分类"}))


def test_expense_resolution_is_derived_and_sparse_override_wins() -> None:
    record = source()
    transaction = transaction_from_source_record(record)
    mapped = resolve_enrichment(transaction, record, catalog())
    assert mapped.merchant_name == "街角咖啡"
    assert mapped.category == "餐饮"
    assert mapped.category_source == "merchant_default"

    decision = EnrichmentDecision(
        transaction.id,
        merchant_override="公司食堂",
        category_override="餐饮",
        note="工作餐",
    )
    overridden = resolve_enrichment(transaction, record, catalog(), decision)
    assert overridden.merchant_name == "公司食堂"
    assert overridden.default_category is None
    assert overridden.category_source == "transaction_override"
    assert overridden.note == "工作餐"


def test_unmatched_expense_and_other_expense_remain_visible_for_review() -> None:
    record = source("unknown")
    transaction = transaction_from_source_record(record)
    unresolved = resolve_enrichment(transaction, record, catalog())
    assert unresolved.category == UNCLASSIFIED_CATEGORY
    assert unresolved.is_unclassified is True

    other = resolve_enrichment(
        transaction_from_source_record(source()), source(), catalog("其他支出")
    )
    assert other.review_signals == (OTHER_EXPENSE_REVIEW,)


def test_income_bypasses_mapping_and_supports_note_only() -> None:
    record = source("咖啡订单", transaction_type="income")
    transaction = transaction_from_source_record(record)
    resolved = resolve_enrichment(
        transaction,
        record,
        catalog(),
        EnrichmentDecision(transaction.id, note="退款入账"),
    )
    assert resolved.category == INCOME_DEFAULT_CATEGORY
    assert resolved.merchant_name is None
    with pytest.raises(DomainInvariantError, match="Note decisions only"):
        resolve_enrichment(
            transaction,
            record,
            catalog(),
            EnrichmentDecision(transaction.id, merchant_override="Cafe"),
        )


def test_batch_rejects_orphan_decision_and_missing_authority() -> None:
    record = source()
    transaction = transaction_from_source_record(record)
    with pytest.raises(DomainInvariantError, match="missing Transactions"):
        resolve_enrichments(
            (transaction,),
            {transaction.id: record},
            catalog(),
            (EnrichmentDecision("txn_missing", note="orphan"),),
        )
    with pytest.raises(DomainInvariantError, match="no authoritative"):
        resolve_enrichments((transaction,), {}, catalog())
