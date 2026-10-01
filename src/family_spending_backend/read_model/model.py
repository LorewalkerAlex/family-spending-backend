"""In-memory household read model."""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import date
from types import MappingProxyType

from family_spending_backend.application.models import AutomationState, FinanceState
from family_spending_backend.domain.enrichment import (
    EnrichmentDecision,
    ResolvedEnrichment,
    consumption_review_signals,
    resolve_enrichments,
)
from family_spending_backend.domain.feedback import FeedbackItem
from family_spending_backend.domain.mapping import MappingCatalog
from family_spending_backend.domain.scheduling import ScheduledRule, ScheduleExecutionState
from family_spending_backend.domain.source import SourceRecord
from family_spending_backend.domain.transaction import SourceLink, Transaction
from family_spending_backend.projections import (
    FinancialProjection,
    SpendingProjection,
    build_financial_projection,
    build_spending_projection,
)


@dataclass(frozen=True, slots=True)
class ReadModelCounts:
    source_records: int = 0
    transactions: int = 0
    enrichments: int = 0
    mapping_reviews: int = 0
    feedback: int = 0


@dataclass(frozen=True, slots=True)
class QueryIndexes:
    """Read-optimized indexes derived with each immutable model generation."""

    transaction_by_id: Mapping[str, Transaction]
    authoritative_source_by_transaction_id: Mapping[str, SourceRecord]
    enrichment_by_transaction_id: Mapping[str, ResolvedEnrichment]
    transaction_ids_by_month: Mapping[str, tuple[str, ...]]
    transaction_ids_by_description: Mapping[str, tuple[str, ...]]
    transaction_ids_by_merchant: Mapping[str, tuple[str, ...]]
    transaction_ids_by_review_signal: Mapping[str, tuple[str, ...]]
    unclassified_transaction_ids: tuple[str, ...]


def _freeze_json(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType({str(key): _freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    return value


def _tuple_index(values: dict[str, list[str]]) -> Mapping[str, tuple[str, ...]]:
    return MappingProxyType({key: tuple(items) for key, items in values.items()})


def _build_query_indexes(
    records: tuple[SourceRecord, ...],
    transactions: tuple[Transaction, ...],
    links: tuple[SourceLink, ...],
    enrichments: tuple[ResolvedEnrichment, ...],
    spending_projection: SpendingProjection,
) -> QueryIndexes:
    records_by_id = {record.id: record for record in records}
    transaction_by_id = {transaction.id: transaction for transaction in transactions}
    authoritative = {
        link.transaction_id: records_by_id[link.source_record_id]
        for link in links
        if link.role == "authoritative"
    }
    enrichment_by_id = {item.transaction_id: item for item in enrichments}
    if set(authoritative) != set(transaction_by_id) or set(enrichment_by_id) != set(
        transaction_by_id
    ):
        raise ValueError("Read Model indexes do not cover the complete Transaction set")

    net_by_id = {item.transaction_id: item for item in spending_projection.refund.net_consumption}
    by_month: dict[str, list[str]] = {}
    by_description: dict[str, list[str]] = {}
    by_merchant: dict[str, list[str]] = {}
    by_review: dict[str, list[str]] = {}
    unclassified: list[str] = []
    for transaction in transactions:
        source = authoritative[transaction.id]
        enrichment = enrichment_by_id[transaction.id]
        by_month.setdefault(transaction.transaction_date.strftime("%Y-%m"), []).append(
            transaction.id
        )
        if source.description is not None:
            by_description.setdefault(source.description, []).append(transaction.id)
        if enrichment.merchant_name is not None:
            by_merchant.setdefault(enrichment.merchant_name, []).append(transaction.id)
        if enrichment.is_unclassified:
            unclassified.append(transaction.id)
        signals = enrichment.review_signals
        net = net_by_id.get(transaction.id)
        if net is not None:
            signals = consumption_review_signals(enrichment, net.spending)
        for signal in signals:
            by_review.setdefault(signal, []).append(transaction.id)

    return QueryIndexes(
        transaction_by_id=MappingProxyType(transaction_by_id),
        authoritative_source_by_transaction_id=MappingProxyType(authoritative),
        enrichment_by_transaction_id=MappingProxyType(enrichment_by_id),
        transaction_ids_by_month=_tuple_index(by_month),
        transaction_ids_by_description=_tuple_index(by_description),
        transaction_ids_by_merchant=_tuple_index(by_merchant),
        transaction_ids_by_review_signal=_tuple_index(by_review),
        unclassified_transaction_ids=tuple(unclassified),
    )


@dataclass(frozen=True, slots=True)
class FinanceReadModel:
    """Derived financial subtree of one published generation."""

    source_records: tuple[SourceRecord, ...]
    transactions: tuple[Transaction, ...]
    source_links: tuple[SourceLink, ...]
    mappings: MappingCatalog
    enrichment_decisions: tuple[EnrichmentDecision, ...]
    resolved_enrichments: tuple[ResolvedEnrichment, ...]
    statement_dates: frozenset[date]
    spending_projection: SpendingProjection
    financial_projection: FinancialProjection
    unreconciled_source_record_ids: tuple[str, ...]
    indexes: QueryIndexes
    counts: ReadModelCounts

    @classmethod
    def from_state(cls, state: FinanceState) -> FinanceReadModel:
        linked_ids = {link.source_record_id for link in state.source_links}
        records_by_id = {record.id: record for record in state.source_records}
        authoritative_sources = {
            link.transaction_id: records_by_id[link.source_record_id]
            for link in state.source_links
            if link.role == "authoritative"
        }
        resolved_enrichments = resolve_enrichments(
            state.transactions,
            authoritative_sources,
            state.mappings,
            state.enrichment_decisions,
        )
        mapping_review_descriptions = {
            records_by_id[link.source_record_id].description
            for link in state.source_links
            if link.role == "authoritative"
            and records_by_id[link.source_record_id].transaction_type == "expense"
            and records_by_id[link.source_record_id].description is not None
            and records_by_id[link.source_record_id].description
            not in state.mappings.description_to_merchant
        }
        enrichments_by_id = {
            enrichment.transaction_id: enrichment for enrichment in resolved_enrichments
        }
        spending_projection = build_spending_projection(
            state.transactions,
            authoritative_sources,
            enrichments_by_id,
            state.statement_dates,
        )
        financial_projection = build_financial_projection(
            state.transactions,
            spending_projection.statistics,
            state.statement_dates,
        )
        spending_projection = replace(
            spending_projection,
            payload=_freeze_json(spending_projection.payload),
        )
        financial_projection = replace(
            financial_projection,
            payload=_freeze_json(financial_projection.payload),
        )
        indexes = _build_query_indexes(
            state.source_records,
            state.transactions,
            state.source_links,
            resolved_enrichments,
            spending_projection,
        )
        return cls(
            source_records=state.source_records,
            transactions=state.transactions,
            source_links=state.source_links,
            mappings=state.mappings,
            enrichment_decisions=state.enrichment_decisions,
            resolved_enrichments=resolved_enrichments,
            statement_dates=state.statement_dates,
            spending_projection=spending_projection,
            financial_projection=financial_projection,
            unreconciled_source_record_ids=tuple(
                record.id for record in state.source_records if record.id not in linked_ids
            ),
            indexes=indexes,
            counts=ReadModelCounts(
                source_records=len(state.source_records),
                transactions=len(state.transactions),
                enrichments=len(resolved_enrichments),
                mapping_reviews=len(mapping_review_descriptions),
            ),
        )

    def state(self) -> FinanceState:
        return FinanceState(
            self.source_records,
            self.transactions,
            self.source_links,
            mappings=self.mappings,
            enrichment_decisions=self.enrichment_decisions,
            statement_dates=self.statement_dates,
        )


@dataclass(frozen=True, slots=True)
class HouseholdReadModel:
    """Immutable root whose independent subtrees are atomically published."""

    finance: FinanceReadModel
    automation: AutomationState = field(default_factory=AutomationState)
    feedback_items: tuple[FeedbackItem, ...] = ()

    @classmethod
    def empty(cls) -> HouseholdReadModel:
        return cls(FinanceReadModel.from_state(FinanceState((), (), ())))

    @classmethod
    def from_states(
        cls,
        finance: FinanceState,
        *,
        automation: AutomationState | None = None,
        feedback_items: tuple[FeedbackItem, ...] = (),
    ) -> HouseholdReadModel:
        return cls(
            FinanceReadModel.from_state(finance),
            automation or AutomationState(),
            feedback_items,
        )

    @property
    def source_records(self) -> tuple[SourceRecord, ...]:
        return self.finance.source_records

    @property
    def transactions(self) -> tuple[Transaction, ...]:
        return self.finance.transactions

    @property
    def source_links(self) -> tuple[SourceLink, ...]:
        return self.finance.source_links

    @property
    def mappings(self) -> MappingCatalog:
        return self.finance.mappings

    @property
    def enrichment_decisions(self) -> tuple[EnrichmentDecision, ...]:
        return self.finance.enrichment_decisions

    @property
    def resolved_enrichments(self) -> tuple[ResolvedEnrichment, ...]:
        return self.finance.resolved_enrichments

    @property
    def statement_dates(self) -> frozenset[date]:
        return self.finance.statement_dates

    @property
    def spending_projection(self) -> SpendingProjection:
        return self.finance.spending_projection

    @property
    def financial_projection(self) -> FinancialProjection:
        return self.finance.financial_projection

    @property
    def scheduled_rules(self) -> tuple[ScheduledRule, ...]:
        return self.automation.scheduled_rules

    @property
    def schedule_execution(self) -> tuple[ScheduleExecutionState, ...]:
        return self.automation.schedule_execution

    @property
    def unreconciled_source_record_ids(self) -> tuple[str, ...]:
        return self.finance.unreconciled_source_record_ids

    @property
    def indexes(self) -> QueryIndexes:
        return self.finance.indexes

    @property
    def counts(self) -> ReadModelCounts:
        return replace(self.finance.counts, feedback=len(self.feedback_items))
