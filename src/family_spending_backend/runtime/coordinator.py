"""Single-writer mutation execution and atomic Read Model publication."""

import json
import logging
from collections.abc import Callable
from threading import Lock
from time import monotonic_ns

from family_spending_backend.application.context import current_request_id
from family_spending_backend.application.models import MutationOutcome
from family_spending_backend.application.ports.unit_of_work import UnitOfWork
from family_spending_backend.read_model import ReadModelProjector
from family_spending_backend.runtime.state import RuntimeState

logger = logging.getLogger(__name__)


def _milliseconds(start: int, end: int) -> float:
    return round((end - start) / 1_000_000, 3)


class MutationCoordinator:
    def __init__(
        self,
        runtime_state: RuntimeState,
        projector: ReadModelProjector | None = None,
    ) -> None:
        self._runtime_state = runtime_state
        self._projector = projector or ReadModelProjector()
        self._writer_lock = Lock()

    def execute[ValueT](
        self,
        *,
        label: str,
        unit_of_work: UnitOfWork,
        mutation: Callable[[], MutationOutcome[ValueT]],
    ) -> ValueT:
        started = monotonic_ns()
        self._runtime_state.mutation_queued()
        try:
            with self._writer_lock:
                acquired = monotonic_ns()
                with unit_of_work:
                    mutation_started = monotonic_ns()
                    outcome = mutation()
                    mutation_finished = monotonic_ns()
                    current = self._runtime_state.read_model()
                    read_model_started = monotonic_ns()
                    candidate = self._projector.apply(current, outcome.change)
                    read_model_finished = monotonic_ns()
                    persistence_started = monotonic_ns()
                    unit_of_work.commit()
                    persistence_finished = monotonic_ns()
                    self._runtime_state.publish_mutation(candidate, outcome.impact, label=label)
                finished = monotonic_ns()
            logger.info(
                json.dumps(
                    {
                        "request_id": current_request_id(),
                        "command": label,
                        "impact": outcome.impact.value,
                        "lock_wait_ms": _milliseconds(started, acquired),
                        "mutation_ms": _milliseconds(mutation_started, mutation_finished),
                        "persistence_ms": _milliseconds(persistence_started, persistence_finished),
                        "read_model_update_ms": _milliseconds(
                            read_model_started, read_model_finished
                        ),
                        "total_ms": _milliseconds(started, finished),
                        "result": "success",
                    },
                    separators=(",", ":"),
                )
            )
            return outcome.value
        except Exception as exc:
            self._runtime_state.mutation_failed(label)
            logger.exception(
                json.dumps(
                    {
                        "request_id": current_request_id(),
                        "command": label,
                        "total_ms": _milliseconds(started, monotonic_ns()),
                        "result": "failure",
                        "error_type": type(exc).__name__,
                    },
                    separators=(",", ":"),
                )
            )
            raise
