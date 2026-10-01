"""Manual Evidence lifecycle and coordinated identity consequences."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from family_spending_backend.application.errors import (
    ApplicationConflictError,
    ApplicationNotFoundError,
)
from family_spending_backend.application.models import (
    FinanceState,
    MutationOutcome,
    ReadModelChange,
)
from family_spending_backend.application.mutation import MutationImpact
from family_spending_backend.application.ports.runtime import FinanceStateReader, MutationExecutor
from family_spending_backend.application.ports.storage import (
    EnrichmentDecisionStore,
    IdentityStore,
    MappingStore,
)
from family_spending_backend.application.ports.unit_of_work import UnitOfWork
from family_spending_backend.domain.manual import (
    ManualEvidence,
    manual_evidence_to_source_record,
)
from family_spending_backend.domain.reconciliation import (
    ReconciliationAction,
    ReconciliationEngine,
    ReconciliationResult,
)
from family_spending_backend.domain.source import SourceRecord
from family_spending_backend.domain.transaction import SourceLinkRole, Transaction


class ManualEvidenceRepository(Protocol):
    def load_all(self) -> tuple[ManualEvidence, ...]: ...

    def replace_all(self, records: tuple[ManualEvidence, ...]) -> None: ...


@dataclass(frozen=True, slots=True)
class ManualInputResult:
    evidence: ManualEvidence
    source_record_id: str
    transaction: Transaction
    source_role: SourceLinkRole
    action: ReconciliationAction
    impact: MutationImpact


@dataclass(frozen=True, slots=True)
class ManualInputDeletionResult:
    evidence_id: str
    source_record_id: str
    transaction_id: str
    transaction_removed: bool
    impact: MutationImpact


class ManualInputService:
    def __init__(
        self,
        *,
        evidence_store: ManualEvidenceRepository,
        identity_store: IdentityStore,
        mapping_store: MappingStore,
        enrichment_store: EnrichmentDecisionStore,
        load_statement_dates: Callable[[], frozenset[date]],
        runtime: FinanceStateReader,
        load_source_records: Callable[[], tuple[SourceRecord, ...]],
        reconciliation: ReconciliationEngine,
        coordinator: MutationExecutor,
        open_unit_of_work: Callable[[str], UnitOfWork],
    ) -> None:
        self._evidence = evidence_store
        self._identity = identity_store
        self._mappings = mapping_store
        self._enrichments = enrichment_store
        self._load_statement_dates = load_statement_dates
        self._runtime = runtime
        self._load_source_records = load_source_records
        self._reconciliation = reconciliation
        self._coordinator = coordinator
        self._open_unit_of_work = open_unit_of_work

    @staticmethod
    def _result_for_source(
        evidence: ManualEvidence,
        reconciliation: ReconciliationResult,
    ) -> ManualInputResult:
        source_record = manual_evidence_to_source_record(evidence)
        decision = next(
            item for item in reconciliation.decisions if item.source_record_id == source_record.id
        )
        transaction = next(
            item for item in reconciliation.transactions if item.id == decision.transaction_id
        )
        source_role = next(
            item.role
            for item in reconciliation.source_links
            if item.source_record_id == source_record.id
        )
        return ManualInputResult(
            evidence=evidence,
            source_record_id=source_record.id,
            transaction=transaction,
            source_role=source_role,
            action=decision.action,
            impact=MutationImpact.TRANSACTIONS_AND_DOWNSTREAM,
        )

    def _outcome[ValueT](
        self,
        value: ValueT,
        records: tuple[SourceRecord, ...],
        reconciliation: ReconciliationResult,
    ) -> MutationOutcome[ValueT]:
        transaction_ids = {transaction.id for transaction in reconciliation.transactions}
        decisions = tuple(
            decision
            for decision in self._enrichments.load()
            if decision.transaction_id in transaction_ids
        )
        self._enrichments.replace(decisions)
        return MutationOutcome(
            value=value,
            change=ReadModelChange.finance_changed(
                FinanceState(
                    records,
                    reconciliation.transactions,
                    reconciliation.source_links,
                    mappings=self._mappings.load(),
                    enrichment_decisions=decisions,
                    statement_dates=self._load_statement_dates(),
                ),
                MutationImpact.TRANSACTIONS_AND_DOWNSTREAM,
            ),
        )

    def create(self, evidence: ManualEvidence) -> ManualInputResult:
        def mutation() -> MutationOutcome[ManualInputResult]:
            current = self._evidence.load_all()
            if any(item.evidence_id == evidence.evidence_id for item in current):
                raise ApplicationConflictError(
                    f"Manual evidence {evidence.evidence_id!r} already exists"
                )
            self._evidence.replace_all((*current, evidence))
            records = self._load_source_records()
            reconciliation = self._reconciliation.reconcile(
                records,
                existing_links=self._identity.load(),
            )
            self._identity.replace(reconciliation.source_links)
            value = self._result_for_source(evidence, reconciliation)
            return self._outcome(value, records, reconciliation)

        return self._coordinator.execute(
            label="Manual Input create",
            unit_of_work=self._open_unit_of_work("Manual Input create"),
            mutation=mutation,
        )

    def correct(self, evidence_id: str, replacement: ManualEvidence) -> ManualInputResult:
        if replacement.evidence_id != evidence_id:
            raise ApplicationConflictError(
                "Manual correction must preserve the permanent evidence id"
            )

        def mutation() -> MutationOutcome[ManualInputResult]:
            current = list(self._evidence.load_all())
            position = next(
                (index for index, item in enumerate(current) if item.evidence_id == evidence_id),
                None,
            )
            if position is None:
                raise ApplicationNotFoundError(f"Manual evidence {evidence_id!r} does not exist")
            source_record = manual_evidence_to_source_record(replacement)
            existing_links = self._identity.load()
            if not any(link.source_record_id == source_record.id for link in existing_links):
                raise ApplicationConflictError(
                    f"Manual evidence {evidence_id!r} has no durable SourceLink"
                )
            current[position] = replacement
            self._evidence.replace_all(tuple(current))
            records = self._load_source_records()
            reconciliation = self._reconciliation.reconcile_reconsidered_source(
                records,
                existing_links=existing_links,
                source_record_id=source_record.id,
            )
            self._identity.replace(reconciliation.source_links)
            value = self._result_for_source(replacement, reconciliation)
            return self._outcome(value, records, reconciliation)

        return self._coordinator.execute(
            label="Manual Input correction",
            unit_of_work=self._open_unit_of_work("Manual Input correction"),
            mutation=mutation,
        )

    def delete(self, evidence_id: str) -> ManualInputDeletionResult:
        def mutation() -> MutationOutcome[ManualInputDeletionResult]:
            current = self._evidence.load_all()
            evidence = next(
                (item for item in current if item.evidence_id == evidence_id),
                None,
            )
            if evidence is None:
                raise ApplicationNotFoundError(f"Manual evidence {evidence_id!r} does not exist")
            source_record = manual_evidence_to_source_record(evidence)
            existing_links = self._identity.load()
            previous_link = next(
                (link for link in existing_links if link.source_record_id == source_record.id),
                None,
            )
            if previous_link is None:
                raise ApplicationConflictError(
                    f"Manual evidence {evidence_id!r} has no durable SourceLink"
                )
            self._evidence.replace_all(
                tuple(item for item in current if item.evidence_id != evidence_id)
            )
            records = self._load_source_records()
            retained = tuple(
                link for link in existing_links if link.source_record_id != source_record.id
            )
            repaired = self._reconciliation.recover_authority_after_source_removal(
                records,
                retained,
            )
            reconciliation = self._reconciliation.reconcile(
                records,
                existing_links=repaired,
            )
            self._identity.replace(reconciliation.source_links)
            value = ManualInputDeletionResult(
                evidence_id=evidence_id,
                source_record_id=source_record.id,
                transaction_id=previous_link.transaction_id,
                transaction_removed=not any(
                    item.id == previous_link.transaction_id for item in reconciliation.transactions
                ),
                impact=MutationImpact.TRANSACTIONS_AND_DOWNSTREAM,
            )
            return self._outcome(value, records, reconciliation)

        return self._coordinator.execute(
            label="Manual Input deletion",
            unit_of_work=self._open_unit_of_work("Manual Input deletion"),
            mutation=mutation,
        )
