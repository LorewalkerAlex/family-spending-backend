from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from family_spending_backend.domain import DomainInvariantError
from family_spending_backend.domain.manual import (
    create_manual_evidence,
    manual_evidence_to_source_record,
)
from family_spending_backend.persistence.filesystem import (
    FilesystemLayout,
    FilesystemManualEvidenceStore,
    ManualEvidenceStoreError,
)
from family_spending_backend.sources.manual.source import ManualSource


def evidence(evidence_id: str = "manual_a"):
    return create_manual_evidence(
        transaction_type="expense",
        transaction_date=date(2026, 8, 2),
        amount=Decimal("9.00"),
        description=" household adjustment ",
        evidence_id=evidence_id,
    )


def test_creation_normalizes_description_and_preserves_explicit_identity() -> None:
    item = evidence()
    record = manual_evidence_to_source_record(item)

    assert item.description == "household adjustment"
    assert record.identity.evidence_identity == "manual_a"
    assert record.source_type == "manual"
    assert record.amount == Decimal("9.00")


def test_explicit_blank_evidence_id_is_rejected_not_replaced() -> None:
    with pytest.raises(DomainInvariantError, match="evidence_id"):
        evidence("")


def test_manual_store_round_trip_is_decimal_exact(tmp_path: Path) -> None:
    store = FilesystemManualEvidenceStore(FilesystemLayout(tmp_path / "data"))
    records = (evidence("manual_a"), evidence("manual_b"))

    store.replace_all(records)

    assert store.load_all() == records
    assert '"amount":"9.00"' in store.path.read_text(encoding="utf-8")
    assert ManualSource(store).load_records() == tuple(
        manual_evidence_to_source_record(item) for item in records
    )


def test_manual_store_rejects_duplicate_ids(tmp_path: Path) -> None:
    store = FilesystemManualEvidenceStore(FilesystemLayout(tmp_path / "data"))

    with pytest.raises(ManualEvidenceStoreError, match="duplicate ids"):
        store.replace_all((evidence(), evidence()))


def test_manual_store_fails_closed_on_unknown_or_missing_fields(tmp_path: Path) -> None:
    store = FilesystemManualEvidenceStore(FilesystemLayout(tmp_path / "data"))
    store.path.parent.mkdir(parents=True)
    store.path.write_text(
        '{"id":"manual_a","type":"expense","date":"2026-08-02",'
        '"amount":"9.00","currency":"CNY","description":null,"category":"x"}\n',
        encoding="utf-8",
    )
    with pytest.raises(ManualEvidenceStoreError, match="unknown fields"):
        store.load_all()

    store.path.write_text('{"id":"manual_a"}\n', encoding="utf-8")
    with pytest.raises(ManualEvidenceStoreError, match="missing fields"):
        store.load_all()
