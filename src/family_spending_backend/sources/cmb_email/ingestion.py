"""Atomic CMB fetch, Evidence persistence, parsing, and Source Sync."""

from collections.abc import Callable
from typing import ClassVar

from family_spending_backend.application.models import MutationOutcome, ReadModelChange
from family_spending_backend.application.ports.runtime import (
    FinanceStateReader,
    MutationExecutor,
)
from family_spending_backend.application.ports.source import SourceAcquisitionResult
from family_spending_backend.application.ports.unit_of_work import UnitOfWork
from family_spending_backend.application.source_sync import SourceSyncService
from family_spending_backend.sources.cmb_email.acquisition import (
    CmbEmailConnector,
    CmbEmailEvidenceWriter,
)
from family_spending_backend.sources.cmb_email.evidence import CmbEmailEvidence
from family_spending_backend.sources.cmb_email.parser import CMB_SOURCE_TYPE


class CmbEmailIngestionService:
    source_type: ClassVar[str] = CMB_SOURCE_TYPE

    def __init__(
        self,
        *,
        connector: CmbEmailConnector,
        evidence_writer: CmbEmailEvidenceWriter,
        source_sync: SourceSyncService,
        runtime: FinanceStateReader,
        coordinator: MutationExecutor,
        open_unit_of_work: Callable[[tuple[CmbEmailEvidence, ...], str], UnitOfWork],
    ) -> None:
        self._connector = connector
        self._evidence_writer = evidence_writer
        self._source_sync = source_sync
        self._runtime = runtime
        self._coordinator = coordinator
        self._open_unit_of_work = open_unit_of_work

    def acquire(self) -> SourceAcquisitionResult:
        raw_messages = self._connector.fetch_raw_messages()
        evidence_items = tuple(CmbEmailEvidence(item) for item in raw_messages)

        def mutation() -> MutationOutcome[SourceAcquisitionResult]:
            added = sum(self._evidence_writer.add(item) for item in evidence_items)
            result = SourceAcquisitionResult(
                self.source_type,
                len(evidence_items),
                added,
                downstream_synchronized=True,
            )
            if added == 0:
                return MutationOutcome(result, ReadModelChange.none())
            synchronized = self._source_sync.sync_inside_mutation()
            return MutationOutcome(result, synchronized.change)

        return self._coordinator.execute(
            label="CMB Email acquisition",
            unit_of_work=self._open_unit_of_work(evidence_items, "CMB Email acquisition"),
            mutation=mutation,
        )
