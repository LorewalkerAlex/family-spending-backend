"""Fault-contained periodic Source acquisition supervisor."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from threading import Event, Lock, Thread

from family_spending_backend.application.ports.source import (
    SourceAcquirer,
    SourceAcquisitionResult,
)
from family_spending_backend.runtime.state import RuntimeState

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SourcePollResult:
    acquisitions: tuple[SourceAcquisitionResult, ...]
    source_sync_triggered: bool
    error: str | None = None


class SourceSupervisor:
    def __init__(
        self,
        acquirers: tuple[SourceAcquirer, ...],
        *,
        source_sync: Callable[[], object],
        runtime: RuntimeState,
        interval_seconds: float,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("SourceSupervisor interval_seconds must be positive")
        self._acquirers = acquirers
        self._source_sync = source_sync
        self._runtime = runtime
        self._interval_seconds = interval_seconds
        self._pending_sync = bool(runtime.read_model().unreconciled_source_record_ids)
        self._stop = Event()
        self._thread: Thread | None = None
        self._lifecycle_lock = Lock()

    def poll_once(self) -> SourcePollResult:
        acquisitions: list[SourceAcquisitionResult] = []
        sync_triggered = False
        try:
            for acquirer in self._acquirers:
                result = acquirer.acquire()
                if result.source_type != acquirer.source_type:
                    raise RuntimeError(
                        f"Source acquirer {acquirer.source_type!r} returned "
                        f"result for {result.source_type!r}"
                    )
                acquisitions.append(result)
                if result.added_count > 0 and result.downstream_synchronized:
                    sync_triggered = True
                else:
                    self._pending_sync |= result.added_count > 0
            if self._pending_sync:
                sync_triggered = True
                self._source_sync()
                self._pending_sync = bool(self._runtime.read_model().unreconciled_source_record_ids)
            self._runtime.record_imap_poll()
            return SourcePollResult(tuple(acquisitions), sync_triggered)
        except Exception as exc:
            self._runtime.record_imap_poll()
            return SourcePollResult(tuple(acquisitions), sync_triggered, str(exc))

    def _run(self) -> None:
        while not self._stop.is_set():
            result = self.poll_once()
            if result.error is not None:
                logger.error("Source poll failed: %s", result.error)
            else:
                logger.info(
                    "Source poll completed: fetched=%d added=%d sync=%s",
                    sum(item.fetched_count for item in result.acquisitions),
                    sum(item.added_count for item in result.acquisitions),
                    result.source_sync_triggered,
                )
            self._stop.wait(self._interval_seconds)

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError("SourceSupervisor is already running")
            self._stop.clear()
            self._thread = Thread(
                target=self._run,
                name="family-spending-source-supervisor",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        with self._lifecycle_lock:
            thread = self._thread
            self._stop.set()
        if thread is not None:
            thread.join(timeout=max(self._interval_seconds * 2, 1.0))
        with self._lifecycle_lock:
            self._thread = None
