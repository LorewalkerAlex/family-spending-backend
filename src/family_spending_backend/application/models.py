"""Typed state and changes crossing the runtime publication boundary."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date

from family_spending_backend.application.mutation import MutationImpact
from family_spending_backend.domain.enrichment import EnrichmentDecision
from family_spending_backend.domain.feedback import FeedbackItem
from family_spending_backend.domain.mapping import MappingCatalog
from family_spending_backend.domain.scheduling import ScheduledRule, ScheduleExecutionState
from family_spending_backend.domain.source import SourceRecord
from family_spending_backend.domain.transaction import SourceLink, Transaction


@dataclass(frozen=True, slots=True)
class FinanceState:
    source_records: tuple[SourceRecord, ...]
    transactions: tuple[Transaction, ...]
    source_links: tuple[SourceLink, ...]
    mappings: MappingCatalog = field(default_factory=MappingCatalog.empty)
    enrichment_decisions: tuple[EnrichmentDecision, ...] = ()
    statement_dates: frozenset[date] = frozenset()


@dataclass(frozen=True, slots=True)
class AutomationState:
    scheduled_rules: tuple[ScheduledRule, ...] = ()
    schedule_execution: tuple[ScheduleExecutionState, ...] = ()


@dataclass(frozen=True, slots=True)
class ReadModelChange:
    """A typed patch for the atomically published household read model.

    ``None`` means that subtree is unchanged. Durable commands remain responsible
    for persistence; this value only describes how to refresh derived memory state.
    """

    impact: MutationImpact
    finance: FinanceState | None = None
    feedback_items: tuple[FeedbackItem, ...] | None = None
    automation: AutomationState | None = None

    def __post_init__(self) -> None:
        changed = (
            self.finance is not None,
            self.feedback_items is not None,
            self.automation is not None,
        )
        if self.impact is MutationImpact.NO_CHANGE and any(changed):
            raise ValueError("NO_CHANGE cannot carry changed read-model state")
        if self.impact is MutationImpact.FEEDBACK_ONLY and changed != (False, True, False):
            raise ValueError("FEEDBACK_ONLY must carry only feedback state")
        if self.impact is MutationImpact.AUTOMATION_ONLY and changed != (False, False, True):
            raise ValueError("AUTOMATION_ONLY must carry only automation state")
        if (
            self.impact
            in {
                MutationImpact.PROJECTIONS,
                MutationImpact.ENRICHMENTS_AND_PROJECTIONS,
                MutationImpact.TRANSACTIONS_AND_DOWNSTREAM,
                MutationImpact.FULL_REBUILD,
            }
            and self.finance is None
        ):
            raise ValueError(f"{self.impact.value} must carry finance state")

    @classmethod
    def none(cls) -> ReadModelChange:
        return cls(MutationImpact.NO_CHANGE)

    @classmethod
    def feedback(cls, items: tuple[FeedbackItem, ...]) -> ReadModelChange:
        return cls(MutationImpact.FEEDBACK_ONLY, feedback_items=items)

    @classmethod
    def automation_only(cls, state: AutomationState) -> ReadModelChange:
        return cls(MutationImpact.AUTOMATION_ONLY, automation=state)

    @classmethod
    def finance_changed(
        cls,
        state: FinanceState,
        impact: MutationImpact,
        *,
        automation: AutomationState | None = None,
    ) -> ReadModelChange:
        return cls(impact, finance=state, automation=automation)


@dataclass(frozen=True, slots=True)
class MutationOutcome[ValueT]:
    value: ValueT
    change: ReadModelChange

    @property
    def impact(self) -> MutationImpact:
        return self.change.impact


def statement_dates_for_reconciled_evidence(
    records: tuple[SourceRecord, ...],
    links: tuple[SourceLink, ...],
    statement_dates_by_evidence: Mapping[str, date],
) -> frozenset[date]:
    """Return coverage dates only for Evidence whose records are all linked."""

    linked_source_ids = {link.source_record_id for link in links}
    record_ids_by_evidence: dict[str, set[str]] = {}
    for record in records:
        record_ids_by_evidence.setdefault(record.identity.evidence_identity, set()).add(record.id)
    reconciled_evidence_ids = {
        evidence_identity
        for evidence_identity, record_ids in record_ids_by_evidence.items()
        if record_ids and record_ids <= linked_source_ids
    }
    return frozenset(
        statement_date
        for evidence_identity, statement_date in statement_dates_by_evidence.items()
        if evidence_identity in reconciled_evidence_ids
    )
