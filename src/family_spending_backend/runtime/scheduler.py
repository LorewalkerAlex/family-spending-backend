"""Long-lived Scheduled Input trigger and supervisor."""

from collections.abc import Callable
from datetime import date
from threading import Event, Lock, Thread

from family_spending_backend.runtime.state import RuntimeState


class SchedulerTrigger:
    def __init__(
        self,
        run_due: Callable[[date], object],
        *,
        runtime: RuntimeState,
        today: Callable[[], date] = date.today,
    ) -> None:
        self._run_due = run_due
        self._runtime = runtime
        self._today = today

    def run_once(self) -> bool:
        try:
            self._run_due(self._today())
        except Exception as exc:
            self._runtime.record_scheduler_tick(exc)
            return False
        self._runtime.record_scheduler_tick()
        return True


class SchedulerSupervisor:
    def __init__(self, trigger: SchedulerTrigger, *, interval_seconds: float) -> None:
        if interval_seconds <= 0:
            raise ValueError("SchedulerSupervisor interval_seconds must be positive")
        self._trigger = trigger
        self._interval_seconds = interval_seconds
        self._stop = Event()
        self._thread: Thread | None = None
        self._lock = Lock()

    def _run(self) -> None:
        while not self._stop.wait(self._interval_seconds):
            self._trigger.run_once()

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise RuntimeError("SchedulerSupervisor is already running")
            self._stop.clear()
            self._thread = Thread(
                target=self._run,
                name="family-spending-scheduler-supervisor",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            thread = self._thread
            self._stop.set()
        if thread is not None:
            thread.join(timeout=max(self._interval_seconds * 2, 1.0))
        with self._lock:
            self._thread = None
