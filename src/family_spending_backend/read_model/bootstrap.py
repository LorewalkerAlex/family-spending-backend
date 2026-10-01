"""Startup construction of the rebuildable read model."""

from collections.abc import Callable, Mapping
from datetime import date

from family_spending_backend.application.models import (
    AutomationState,
    FinanceState,
    statement_dates_for_reconciled_evidence,
)
from family_spending_backend.application.ports.storage import (
    EnrichmentDecisionStore,
    FeedbackStore,
    IdentityStore,
    MappingStore,
    ScheduleStore,
)
from family_spending_backend.domain.mapping import MappingCatalog
from family_spending_backend.domain.source import SourceRecord
from family_spending_backend.domain.transaction import rebuild_transactions_from_source_links
from family_spending_backend.persistence.filesystem import FilesystemLayout
from family_spending_backend.read_model.model import HouseholdReadModel


class ReadModelBootstrap:
    """Rebuild the complete initial read model from durable stores."""

    def __init__(
        self,
        layout: FilesystemLayout,
        *,
        load_source_records: Callable[[], tuple[SourceRecord, ...]] | None = None,
        identity_store: IdentityStore | None = None,
        mapping_store: MappingStore | None = None,
        enrichment_store: EnrichmentDecisionStore | None = None,
        load_statement_dates: Callable[[], Mapping[str, date]] | None = None,
        feedback_store: FeedbackStore | None = None,
        schedule_store: ScheduleStore | None = None,
    ) -> None:
        self._layout = layout
        self._load_source_records = load_source_records
        self._identity_store = identity_store
        self._mapping_store = mapping_store
        self._enrichment_store = enrichment_store
        self._load_statement_dates = load_statement_dates
        self._feedback_store = feedback_store
        self._schedule_store = schedule_store

    def build(self) -> HouseholdReadModel:
        if not self._layout.root.is_dir():
            raise RuntimeError("filesystem layout must be initialized before bootstrap")
        if self._load_source_records is None or self._identity_store is None:
            return HouseholdReadModel.empty()
        records: tuple[SourceRecord, ...] = self._load_source_records()
        links = self._identity_store.load()
        transactions = rebuild_transactions_from_source_links(records, links)
        mappings = self._mapping_store.load() if self._mapping_store is not None else None
        decisions = self._enrichment_store.load() if self._enrichment_store is not None else ()
        statement_dates = (
            statement_dates_for_reconciled_evidence(
                records,
                links,
                self._load_statement_dates(),
            )
            if self._load_statement_dates is not None
            else frozenset()
        )
        feedback_items = self._feedback_store.load() if self._feedback_store is not None else ()
        scheduled_rules = self._schedule_store.load_rules() if self._schedule_store else ()
        schedule_execution = self._schedule_store.load_execution() if self._schedule_store else ()
        return HouseholdReadModel.from_states(
            FinanceState(
                records,
                transactions,
                links,
                mappings=mappings or MappingCatalog.empty(),
                enrichment_decisions=decisions,
                statement_dates=statement_dates,
            ),
            feedback_items=feedback_items,
            automation=AutomationState(scheduled_rules, schedule_execution),
        )
