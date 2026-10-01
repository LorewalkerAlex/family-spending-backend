"""Runtime capabilities consumed by application use cases."""

from collections.abc import Callable
from typing import Protocol

from family_spending_backend.application.models import (
    AutomationState,
    FinanceState,
    MutationOutcome,
)
from family_spending_backend.application.ports.unit_of_work import UnitOfWork
from family_spending_backend.domain.feedback import FeedbackItem


class MutationExecutor(Protocol):
    def execute[ValueT](
        self,
        *,
        label: str,
        unit_of_work: UnitOfWork,
        mutation: Callable[[], MutationOutcome[ValueT]],
    ) -> ValueT: ...


class FinanceStateReader(Protocol):
    def current_finance_state(self) -> FinanceState: ...


class AutomationStateReader(Protocol):
    def current_automation_state(self) -> AutomationState: ...


class FeedbackStateReader(Protocol):
    def current_feedback_items(self) -> tuple[FeedbackItem, ...]: ...


class ScheduledStateReader(FinanceStateReader, AutomationStateReader, Protocol):
    pass


class ParserCacheStatsReader(Protocol):
    def parser_cache_counts(self) -> tuple[int, int]: ...
