from dataclasses import FrozenInstanceError
from datetime import date
from decimal import Decimal

import pytest

from family_spending_backend.domain import (
    DomainInvariantError,
    SourceIdentity,
    SourceLink,
    SourceRecord,
    build_reconsidered_transaction_id,
    build_transaction_id,
    rebuild_transactions_from_source_links,
    transaction_from_source_record,
    validate_source_link_structure,
)


def source_record(
    locator: str = "fingerprint:entry-a",
    *,
    amount: str = "12.34",
    description: str | None = "merchant text",
) -> SourceRecord:
    return SourceRecord(
        identity=SourceIdentity(
            source_type="cmb_email",
            evidence_identity="sha256:statement",
            record_locator=locator,
        ),
        transaction_type="expense",
        transaction_date=date(2026, 8, 1),
        amount=Decimal(amount),
        currency="CNY",
        description=description,
    )


def test_identity_hashes_match_legacy_baseline_959d29b() -> None:
    record = source_record()

    assert record.id == "src_169ea8b4e83ed2db4bf09648"
    assert build_transaction_id(record) == "txn_b390f22c7b795ea03faf4e2d"
    assert (
        build_reconsidered_transaction_id(record, "txn_historical")
        == "txn_d76254e28927d60c17fee12e"
    )


def test_source_identity_depends_on_stable_evidence_locator_not_financial_fields() -> None:
    original = source_record(amount="12.34", description="before correction")
    corrected = source_record(amount="99.00", description="after correction")
    another_locator = source_record("fingerprint:entry-b")

    assert original.id == corrected.id
    assert original.id != another_locator.id


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_type", ""),
        ("evidence_identity", " surrounded "),
        ("record_locator", "record\0locator"),
    ],
)
def test_source_identity_rejects_ambiguous_components(field: str, value: str) -> None:
    values = {
        "source_type": "cmb_email",
        "evidence_identity": "sha256:statement",
        "record_locator": "fingerprint:entry-a",
    }
    values[field] = value

    with pytest.raises(DomainInvariantError, match=field):
        SourceIdentity(**values)


@pytest.mark.parametrize("amount", [Decimal("NaN"), Decimal("Infinity"), 12.34])
def test_source_record_requires_finite_decimal_amount(amount: object) -> None:
    with pytest.raises(DomainInvariantError, match="finite Decimal"):
        SourceRecord(
            identity=SourceIdentity("manual", "manual-1", "record"),
            transaction_type="expense",
            transaction_date=date(2026, 8, 1),
            amount=amount,  # type: ignore[arg-type]
            currency="CNY",
            description=None,
        )


@pytest.mark.parametrize("currency", ["", " cny", "cny", "CNY "])
def test_source_record_requires_normalized_currency(currency: str) -> None:
    with pytest.raises(DomainInvariantError, match="currency"):
        SourceRecord(
            identity=SourceIdentity("manual", "manual-1", "record"),
            transaction_type="expense",
            transaction_date=date(2026, 8, 1),
            amount=Decimal("1.00"),
            currency=currency,
            description=None,
        )


def test_source_record_is_immutable() -> None:
    record = source_record()

    with pytest.raises(FrozenInstanceError):
        record.amount = Decimal("99.00")  # type: ignore[misc]


def test_transaction_rebuild_preserves_explicit_durable_identity() -> None:
    record = source_record()

    created = transaction_from_source_record(record)
    rebuilt = transaction_from_source_record(record, transaction_id="txn_historical")

    assert created.id == build_transaction_id(record)
    assert rebuilt.id == "txn_historical"
    assert rebuilt.amount == record.amount
    assert rebuilt.transaction_date == record.transaction_date


def test_explicit_blank_transaction_id_is_rejected_instead_of_replaced() -> None:
    with pytest.raises(DomainInvariantError, match="transaction id"):
        transaction_from_source_record(source_record(), transaction_id="")


@pytest.mark.parametrize(
    "link",
    [
        SourceLink("txn_1", "src_1", "authoritative"),
        SourceLink("txn_1", "src_2", "supporting"),
    ],
)
def test_source_link_accepts_only_canonical_roles(link: SourceLink) -> None:
    assert link.role in ("authoritative", "supporting")


def test_source_link_rejects_unknown_role() -> None:
    with pytest.raises(DomainInvariantError, match="role"):
        SourceLink("txn_1", "src_1", "primary")  # type: ignore[arg-type]


def test_source_link_structure_requires_one_authority_and_one_link_per_source() -> None:
    valid = (
        SourceLink("txn_b", "src_b_support", "supporting"),
        SourceLink("txn_b", "src_b_authority", "authoritative"),
        SourceLink("txn_a", "src_a", "authoritative"),
    )

    assert validate_source_link_structure(valid) == ("txn_b", "txn_a")

    with pytest.raises(DomainInvariantError, match="linked more than once"):
        validate_source_link_structure(
            (
                SourceLink("txn_a", "src_duplicate", "authoritative"),
                SourceLink("txn_b", "src_duplicate", "authoritative"),
            )
        )
    with pytest.raises(DomainInvariantError, match="multiple authoritative"):
        validate_source_link_structure(
            (
                SourceLink("txn_a", "src_a", "authoritative"),
                SourceLink("txn_a", "src_b", "authoritative"),
            )
        )
    with pytest.raises(DomainInvariantError, match="no authoritative"):
        validate_source_link_structure((SourceLink("txn_a", "src_a", "supporting"),))


def test_rebuild_uses_only_authoritative_source_facts() -> None:
    authority = source_record("authority", amount="20.00")
    support = source_record("support", amount="999.00")
    links = (
        SourceLink("txn_preserved", support.id, "supporting"),
        SourceLink("txn_preserved", authority.id, "authoritative"),
    )

    transactions = rebuild_transactions_from_source_links((support, authority), links)

    assert len(transactions) == 1
    assert transactions[0].id == "txn_preserved"
    assert transactions[0].amount == Decimal("20.00")


def test_rebuild_rejects_missing_or_duplicate_source_records() -> None:
    record = source_record()
    link = SourceLink("txn_1", record.id, "authoritative")

    with pytest.raises(DomainInvariantError, match="Duplicate SourceRecord"):
        rebuild_transactions_from_source_links((record, record), (link,))
    with pytest.raises(DomainInvariantError, match="missing SourceRecord"):
        rebuild_transactions_from_source_links((), (link,))
