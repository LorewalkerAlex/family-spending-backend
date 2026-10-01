from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from family_spending_backend.domain.enrichment import EnrichmentDecision
from family_spending_backend.domain.feedback import FeedbackContext, FeedbackItem
from family_spending_backend.domain.manual import (
    create_manual_evidence,
    manual_evidence_to_source_record,
)
from family_spending_backend.domain.mapping import MappingCatalog
from family_spending_backend.domain.scheduling import ScheduledRule
from family_spending_backend.domain.transaction import (
    SourceLink,
    build_transaction_id,
)
from family_spending_backend.migration.importer import LegacyImportError, import_legacy_copy
from family_spending_backend.migration.parity import ParityMismatchError, verify_parity
from family_spending_backend.persistence.filesystem import (
    FilesystemEnrichmentDecisionStore,
    FilesystemFeedbackStore,
    FilesystemIdentityStore,
    FilesystemLayout,
    FilesystemManualEvidenceStore,
    FilesystemMappingStore,
    FilesystemScheduleStore,
)


def source_fixture(root: Path) -> FilesystemLayout:
    layout = FilesystemLayout(root)
    layout.initialize()
    expense = create_manual_evidence(
        evidence_id="manual_expense",
        transaction_type="expense",
        transaction_date=date(2026, 9, 1),
        amount=Decimal("12.34"),
        description="market",
    )
    income = create_manual_evidence(
        evidence_id="manual_income",
        transaction_type="income",
        transaction_date=date(2026, 9, 2),
        amount=Decimal("1000"),
        description="salary",
    )
    FilesystemManualEvidenceStore(layout).replace_all((expense, income))
    records = tuple(map(manual_evidence_to_source_record, (expense, income)))
    links = tuple(
        SourceLink(build_transaction_id(record), record.id, "authoritative") for record in records
    )
    FilesystemIdentityStore(layout).replace(links)
    FilesystemMappingStore(layout).replace(
        MappingCatalog({"market": "Market"}, {"Market": "Daily"}, frozenset({"Daily"}))
    )
    FilesystemEnrichmentDecisionStore(layout).replace(
        (EnrichmentDecision(links[0].transaction_id, note="weekly"),)
    )
    FilesystemScheduleStore(layout).replace_rules(
        (
            ScheduledRule(
                "schedule_future",
                True,
                "expense",
                Decimal("3"),
                "future",
                date(2027, 1, 1),
            ),
        )
    )
    FilesystemFeedbackStore(layout).replace(
        (
            FeedbackItem(
                "feedback_1",
                datetime(2026, 9, 1, tzinfo=UTC),
                "open",
                "hello",
                FeedbackContext(runtime="android"),
            ),
        )
    )
    return layout


def bytes_by_relative_path(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_importer_never_writes_source_and_proves_full_parity(tmp_path: Path) -> None:
    source = source_fixture(tmp_path / "legacy-copy")
    before = bytes_by_relative_path(source.root)
    target = tmp_path / "new-data"

    report = import_legacy_copy(source.root, target, parser_version="test-v1")

    assert bytes_by_relative_path(source.root) == before
    assert report.parity.source_record_count == 2
    assert report.parity.transaction_count == 2
    assert report.parity.spending_total_minor == 1234
    assert report.parity.financial_net_cash_flow_minor == 98766
    assert verify_parity(source.root, target, parser_version="test-v1") == report.parity
    assert not any((target / "derived").glob("*"))


def test_parity_verifier_reports_mapping_drift(tmp_path: Path) -> None:
    source = source_fixture(tmp_path / "source")
    target = tmp_path / "target"
    import_legacy_copy(source.root, target, parser_version="test-v1")
    target_layout = FilesystemLayout(target)
    FilesystemMappingStore(target_layout).replace(
        MappingCatalog({"market": "Store"}, {"Store": "Daily"}, frozenset({"Daily"}))
    )
    with pytest.raises(ParityMismatchError, match="Mapping identity"):
        verify_parity(source.root, target, parser_version="test-v1")


def test_import_target_cannot_be_inside_read_only_source(tmp_path: Path) -> None:
    source = source_fixture(tmp_path / "legacy-copy")
    before = bytes_by_relative_path(source.root)
    with pytest.raises(LegacyImportError, match="outside"):
        import_legacy_copy(
            source.root,
            source.root / "new-data",
            parser_version="test-v1",
        )
    assert bytes_by_relative_path(source.root) == before
