from datetime import date
from pathlib import Path

import pytest

from family_spending_backend.application.ports.source import SourceAcquisitionResult
from family_spending_backend.application.source_sync import SourceSyncService
from family_spending_backend.config import Settings
from family_spending_backend.domain.reconciliation import ReconciliationEngine
from family_spending_backend.persistence.filesystem import (
    FilesystemCmbEmailEvidenceStore,
    FilesystemEnrichmentDecisionStore,
    FilesystemIdentityStore,
    FilesystemLayout,
    FilesystemMappingStore,
    FileUnitOfWork,
)
from family_spending_backend.read_model import HouseholdReadModel
from family_spending_backend.runtime import (
    MutationCoordinator,
    RuntimeState,
    SchedulerTrigger,
    SourceSupervisor,
)
from family_spending_backend.sources.cmb_email.acquisition import CmbEmailAcquirer
from family_spending_backend.sources.cmb_email.cache import CmbParserCache
from family_spending_backend.sources.cmb_email.evidence import CmbEmailEvidence
from family_spending_backend.sources.cmb_email.imap_163 import (
    encode_mailbox_name,
    parse_since_date,
)
from family_spending_backend.sources.cmb_email.ingestion import CmbEmailIngestionService
from family_spending_backend.sources.cmb_email.reconciliation import CmbEmailReconciliationPolicy
from family_spending_backend.sources.cmb_email.source import CmbEmailSource
from family_spending_backend.sources.manual.reconciliation import ManualReconciliationPolicy


class Connector:
    def fetch_raw_messages(self) -> tuple[bytes, ...]:
        return b"first", b"first", b"second"


class Writer:
    def __init__(self) -> None:
        self.identities: set[str] = set()

    def add(self, evidence: CmbEmailEvidence) -> bool:
        before = len(self.identities)
        self.identities.add(evidence.identity)
        return len(self.identities) > before


class Acquirer:
    source_type = "cmb_email"

    def __init__(self) -> None:
        self.calls = 0

    def acquire(self) -> SourceAcquisitionResult:
        self.calls += 1
        return SourceAcquisitionResult("cmb_email", 1, 1 if self.calls == 1 else 0)


def runtime() -> RuntimeState:
    state = RuntimeState(Settings(_env_file=None, environment="test"))
    state.publish_initial(HouseholdReadModel.empty())
    return state


def test_acquisition_is_idempotent_and_supervisor_syncs_only_after_addition() -> None:
    writer = Writer()
    acquirer = CmbEmailAcquirer(Connector(), writer)
    assert acquirer.acquire().added_count == 2
    assert acquirer.acquire().added_count == 0

    calls = 0

    def sync() -> None:
        nonlocal calls
        calls += 1

    supervisor = SourceSupervisor(
        (Acquirer(),), source_sync=sync, runtime=runtime(), interval_seconds=60
    )
    first = supervisor.poll_once()
    second = supervisor.poll_once()
    assert first.source_sync_triggered is True
    assert second.source_sync_triggered is False
    assert calls == 1


def test_scheduler_failure_is_contained_and_imap_inputs_are_validated() -> None:
    state = runtime()

    def fail(_: date) -> None:
        raise RuntimeError("tick failure")

    assert SchedulerTrigger(fail, runtime=state).run_once() is False
    assert state.snapshot().last_scheduler_tick is not None
    assert parse_since_date("01-Jan-2026") == date(2026, 1, 1)
    assert encode_mailbox_name("INBOX") == "INBOX"
    assert encode_mailbox_name("信用卡") != "信用卡"


def test_atomic_ingestion_rolls_back_invalid_new_evidence(tmp_path: Path) -> None:
    layout = FilesystemLayout(tmp_path / "data")
    layout.initialize()
    evidence_store = FilesystemCmbEmailEvidenceStore(layout)
    identity_store = FilesystemIdentityStore(layout)
    mapping_store = FilesystemMappingStore(layout)
    enrichment_store = FilesystemEnrichmentDecisionStore(layout)
    source = CmbEmailSource(evidence_store, CmbParserCache("test-v1"))
    state = runtime()
    coordinator = MutationCoordinator(state)
    sync = SourceSyncService(
        load_source_records=source.load_records,
        reconciliation=ReconciliationEngine(
            (CmbEmailReconciliationPolicy(), ManualReconciliationPolicy())
        ),
        identity_store=identity_store,
        mapping_store=mapping_store,
        enrichment_store=enrichment_store,
        load_statement_dates=lambda: frozenset(),
        runtime=state,
        coordinator=coordinator,
        open_unit_of_work=lambda label: FileUnitOfWork(
            (layout.source_links, layout.enrichment_decisions), label=label
        ),
    )
    ingestion = CmbEmailIngestionService(
        connector=Connector(),
        evidence_writer=evidence_store,
        source_sync=sync,
        runtime=state,
        coordinator=coordinator,
        open_unit_of_work=lambda evidence, label: FileUnitOfWork(
            (
                *(layout.cmb_email_evidence / item.filename for item in evidence),
                layout.source_links,
                layout.enrichment_decisions,
            ),
            label=label,
        ),
    )
    with pytest.raises(Exception, match="Date header"):
        ingestion.acquire()
    assert evidence_store.load_all() == ()
    assert state.snapshot().generation == 0
