"""Generic SourceRecord-to-SourceLink synchronization use case."""

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from family_spending_backend.application.errors import ApplicationConflictError
from family_spending_backend.application.models import (
    FinanceState,
    MutationOutcome,
    ReadModelChange,
)
from family_spending_backend.application.mutation import MutationImpact
from family_spending_backend.application.ports.runtime import (
    FinanceStateReader,
    MutationExecutor,
)
from family_spending_backend.application.ports.storage import (
    EnrichmentDecisionStore,
    IdentityStore,
    MappingStore,
)
from family_spending_backend.application.ports.unit_of_work import UnitOfWork
from family_spending_backend.domain.enrichment import resolve_enrichments
from family_spending_backend.domain.reconciliation import (
    ReconciliationDecision,
    ReconciliationEngine,
    ReconciliationError,
    ReconciliationHints,
)
from family_spending_backend.domain.source import SourceRecord


@dataclass(frozen=True, slots=True)
class SourceSyncResult:
    source_record_count: int
    transaction_count: int
    created_count: int
    matched_count: int
    reused_count: int
    decisions: tuple[ReconciliationDecision, ...]
    impact: MutationImpact


class SourceSyncService:
    def __init__(
        self,
        *,
        load_source_records: Callable[[], tuple[SourceRecord, ...]],
        reconciliation: ReconciliationEngine,
        identity_store: IdentityStore,
        mapping_store: MappingStore,
        enrichment_store: EnrichmentDecisionStore,
        load_statement_dates: Callable[[], frozenset[date]],
        runtime: FinanceStateReader,
        coordinator: MutationExecutor,
        open_unit_of_work: Callable[[str], UnitOfWork],
    ) -> None:
        self._load_source_records = load_source_records
        self._reconciliation = reconciliation
        self._identity = identity_store
        self._mappings = mapping_store
        self._enrichments = enrichment_store
        self._load_statement_dates = load_statement_dates
        self._runtime = runtime
        self._coordinator = coordinator
        self._open_unit_of_work = open_unit_of_work

    def sync(self) -> SourceSyncResult:
        return self._coordinator.execute(
            label="Source Sync",
            unit_of_work=self._open_unit_of_work("Source Sync"),
            mutation=self.sync_inside_mutation,
        )

    def sync_inside_mutation(self) -> MutationOutcome[SourceSyncResult]:
        records = self._load_source_records()
        record_ids = {record.id for record in records}
        existing_links = tuple(
            link for link in self._identity.load() if link.source_record_id in record_ids
        )
        try:
            existing_links = self._reconciliation.recover_authority_after_source_removal(
                records, existing_links
            )
        except ReconciliationError as exc:
            raise ApplicationConflictError(str(exc)) from exc

        mappings = self._mappings.load()
        current = self._runtime.current_finance_state()
        current_records = {record.id: record for record in current.source_records}
        current_authoritative = {
            link.transaction_id: current_records[link.source_record_id]
            for link in current.source_links
            if link.role == "authoritative"
        }
        current_enrichments = resolve_enrichments(
            current.transactions,
            current_authoritative,
            current.mappings,
            current.enrichment_decisions,
        )
        hints = ReconciliationHints(
            merchant_by_transaction_id={
                enrichment.transaction_id: enrichment.merchant_name
                for enrichment in current_enrichments
            },
            merchant_by_source_record_id={
                record.id: (
                    mappings.merchant_for_description(record.description)
                    if record.transaction_type == "expense"
                    else None
                )
                for record in records
            },
        )
        try:
            reconciled = self._reconciliation.reconcile(
                records, existing_links=existing_links, hints=hints
            )
        except ReconciliationError as exc:
            raise ApplicationConflictError(str(exc)) from exc

        transaction_ids = {transaction.id for transaction in reconciled.transactions}
        current_decisions = self._enrichments.load()
        retained_decisions = tuple(
            decision for decision in current_decisions if decision.transaction_id in transaction_ids
        )
        if reconciled.source_links != self._identity.load():
            self._identity.replace(reconciled.source_links)
        if retained_decisions != current_decisions:
            self._enrichments.replace(retained_decisions)

        state = FinanceState(
            records,
            reconciled.transactions,
            reconciled.source_links,
            mappings=mappings,
            enrichment_decisions=retained_decisions,
            statement_dates=self._load_statement_dates(),
        )
        changed = state != current
        impact = MutationImpact.TRANSACTIONS_AND_DOWNSTREAM if changed else MutationImpact.NO_CHANGE
        counts = Counter(decision.action for decision in reconciled.decisions)
        value = SourceSyncResult(
            source_record_count=len(records),
            transaction_count=len(reconciled.transactions),
            created_count=counts["created"],
            matched_count=counts["matched"],
            reused_count=counts["reused"],
            decisions=reconciled.decisions,
            impact=impact,
        )
        change = (
            ReadModelChange.none()
            if impact is MutationImpact.NO_CHANGE
            else ReadModelChange.finance_changed(state, impact)
        )
        return MutationOutcome(value=value, change=change)
