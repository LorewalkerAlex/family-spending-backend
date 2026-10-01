"""Thread-safe operational status for the single backend process."""

from dataclasses import dataclass
from datetime import UTC, datetime
from threading import RLock

from family_spending_backend.application.models import AutomationState, FinanceState
from family_spending_backend.application.mutation import MutationImpact
from family_spending_backend.application.ports.runtime import ParserCacheStatsReader
from family_spending_backend.config import Settings
from family_spending_backend.domain.feedback import FeedbackItem
from family_spending_backend.read_model import HouseholdReadModel, ReadModelCounts


@dataclass(frozen=True, slots=True)
class RuntimeStatusSnapshot:
    phase: str
    started_at: datetime
    generation: int
    queued_mutations: int
    last_successful_mutation: str | None
    last_failed_mutation: str | None
    last_imap_poll: str | None
    last_scheduler_tick: str | None
    parser_cache_hits: int
    parser_cache_misses: int
    counts: ReadModelCounts
    schema_version: str
    parser_version: str


class RuntimeState:
    """Own the atomically published read model and observable process state."""

    def __init__(
        self,
        settings: Settings,
        *,
        parser_cache_stats: ParserCacheStatsReader | None = None,
    ) -> None:
        self._lock = RLock()
        self._phase = "starting"
        self._started_at = datetime.now(UTC)
        self._generation = 0
        self._read_model = HouseholdReadModel.empty()
        self._settings = settings
        self._parser_cache_stats = parser_cache_stats
        self._queued_mutations = 0
        self._last_successful_mutation: str | None = None
        self._last_failed_mutation: str | None = None
        self._last_imap_poll: str | None = None
        self._last_scheduler_tick: str | None = None
        self._last_scheduler_error: str | None = None

    def publish_initial(self, read_model: HouseholdReadModel) -> None:
        """Publish the startup model without claiming a financial mutation."""

        with self._lock:
            self._read_model = read_model
            self._phase = "ready"

    def read_model(self) -> HouseholdReadModel:
        with self._lock:
            return self._read_model

    def current_finance_state(self) -> FinanceState:
        with self._lock:
            model = self._read_model
            return model.finance.state()

    def current_automation_state(self) -> AutomationState:
        with self._lock:
            return self._read_model.automation

    def current_feedback_items(self) -> tuple[FeedbackItem, ...]:
        with self._lock:
            return self._read_model.feedback_items

    def mutation_queued(self) -> None:
        with self._lock:
            self._queued_mutations += 1

    def record_imap_poll(self) -> None:
        with self._lock:
            self._last_imap_poll = datetime.now(UTC).isoformat()

    def record_scheduler_tick(self, error: BaseException | None = None) -> None:
        with self._lock:
            self._last_scheduler_tick = datetime.now(UTC).isoformat()
            self._last_scheduler_error = str(error) if error is not None else None

    def mutation_failed(self, label: str) -> None:
        with self._lock:
            self._queued_mutations -= 1
            self._last_failed_mutation = label

    def publish_mutation(
        self,
        read_model: HouseholdReadModel,
        impact: MutationImpact,
        *,
        label: str,
    ) -> None:
        with self._lock:
            self._queued_mutations -= 1
            if impact is not MutationImpact.NO_CHANGE:
                self._read_model = read_model
                self._generation += 1
            self._last_successful_mutation = label

    def snapshot(self) -> RuntimeStatusSnapshot:
        with self._lock:
            cache_hits, cache_misses = (
                self._parser_cache_stats.parser_cache_counts()
                if self._parser_cache_stats is not None
                else (0, 0)
            )
            return RuntimeStatusSnapshot(
                phase=self._phase,
                started_at=self._started_at,
                generation=self._generation,
                queued_mutations=self._queued_mutations,
                last_successful_mutation=self._last_successful_mutation,
                last_failed_mutation=self._last_failed_mutation,
                last_imap_poll=self._last_imap_poll,
                last_scheduler_tick=self._last_scheduler_tick,
                parser_cache_hits=cache_hits,
                parser_cache_misses=cache_misses,
                counts=self._read_model.counts,
                schema_version=self._settings.schema_version,
                parser_version=self._settings.parser_version,
            )
