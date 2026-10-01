"""Format-neutral persistence ports owned by the application layer."""

from typing import Protocol

from family_spending_backend.domain.enrichment import EnrichmentDecision
from family_spending_backend.domain.feedback import FeedbackItem
from family_spending_backend.domain.mapping import MappingCatalog
from family_spending_backend.domain.scheduling import ScheduledRule, ScheduleExecutionState
from family_spending_backend.domain.transaction import SourceLink


class IdentityStore(Protocol):
    """Persist durable SourceRecord-to-Transaction identity decisions."""

    def load(self) -> tuple[SourceLink, ...]: ...

    def replace(self, links: tuple[SourceLink, ...]) -> None: ...


class MappingStore(Protocol):
    def load(self) -> MappingCatalog: ...

    def replace(self, mappings: MappingCatalog) -> None: ...


class EnrichmentDecisionStore(Protocol):
    def load(self) -> tuple[EnrichmentDecision, ...]: ...

    def replace(self, decisions: tuple[EnrichmentDecision, ...]) -> None: ...


class FeedbackStore(Protocol):
    def load(self) -> tuple[FeedbackItem, ...]: ...

    def replace(self, items: tuple[FeedbackItem, ...]) -> None: ...


class ScheduleStore(Protocol):
    def load_rules(self) -> tuple[ScheduledRule, ...]: ...

    def replace_rules(self, rules: tuple[ScheduledRule, ...]) -> None: ...

    def load_execution(self) -> tuple[ScheduleExecutionState, ...]: ...

    def replace_execution(self, states: tuple[ScheduleExecutionState, ...]) -> None: ...
