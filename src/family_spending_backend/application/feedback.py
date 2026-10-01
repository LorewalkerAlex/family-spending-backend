"""Feedback lifecycle isolated from financial rebuilding."""

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from family_spending_backend.application.errors import (
    ApplicationNotFoundError,
    ApplicationValidationError,
)
from family_spending_backend.application.models import MutationOutcome, ReadModelChange
from family_spending_backend.application.ports.runtime import (
    FeedbackStateReader,
    MutationExecutor,
)
from family_spending_backend.application.ports.storage import FeedbackStore
from family_spending_backend.application.ports.unit_of_work import UnitOfWork
from family_spending_backend.domain.feedback import (
    FEEDBACK_STATUSES,
    FeedbackContext,
    FeedbackItem,
    FeedbackStatus,
    update_feedback_status,
)


class FeedbackService:
    def __init__(
        self,
        *,
        store: FeedbackStore,
        runtime: FeedbackStateReader,
        coordinator: MutationExecutor,
        open_unit_of_work: Callable[[str], UnitOfWork],
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        new_id: Callable[[], str] = lambda: f"feedback_{uuid4().hex}",
    ) -> None:
        self._store = store
        self._runtime = runtime
        self._coordinator = coordinator
        self._open_unit_of_work = open_unit_of_work
        self._now = now
        self._new_id = new_id

    def list_items(self) -> tuple[FeedbackItem, ...]:
        return tuple(reversed(self._runtime.current_feedback_items()))

    def create(self, *, content: str, context: FeedbackContext) -> FeedbackItem:
        normalized = content.strip() if isinstance(content, str) else ""
        if not normalized:
            raise ApplicationValidationError("Feedback content must be non-empty text")
        item = FeedbackItem(self._new_id(), self._now(), "open", normalized, context)

        def mutation() -> MutationOutcome[FeedbackItem]:
            items = (*self._store.load(), item)
            self._store.replace(items)
            return MutationOutcome(item, ReadModelChange.feedback(items))

        return self._coordinator.execute(
            label="Feedback create",
            unit_of_work=self._open_unit_of_work("Feedback create"),
            mutation=mutation,
        )

    def update_status(self, feedback_id: str, status: FeedbackStatus) -> FeedbackItem:
        if status not in FEEDBACK_STATUSES:
            raise ApplicationValidationError("Feedback status must be 'open' or 'resolved'")

        def mutation() -> MutationOutcome[FeedbackItem]:
            items = self._store.load()
            current = next((item for item in items if item.id == feedback_id), None)
            if current is None:
                raise ApplicationNotFoundError(f"Feedback {feedback_id!r} does not exist")
            if current.status == status:
                return MutationOutcome(current, ReadModelChange.none())
            updated = update_feedback_status(current, status)
            next_items = tuple(updated if item.id == feedback_id else item for item in items)
            self._store.replace(next_items)
            return MutationOutcome(updated, ReadModelChange.feedback(next_items))

        return self._coordinator.execute(
            label="Feedback status update",
            unit_of_work=self._open_unit_of_work("Feedback status update"),
            mutation=mutation,
        )
