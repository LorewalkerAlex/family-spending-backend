import json
import logging
from pathlib import Path
from threading import Event, Thread

import httpx2
import pytest

from family_spending_backend.application.models import MutationOutcome, ReadModelChange
from family_spending_backend.application.mutation import MutationImpact
from family_spending_backend.config import Settings
from family_spending_backend.interfaces.http.app import create_app
from family_spending_backend.persistence.filesystem import FileUnitOfWork
from family_spending_backend.read_model import HouseholdReadModel
from family_spending_backend.runtime import MutationCoordinator, RuntimeState
from family_spending_backend.runtime.instance_lock import InstanceLock, InstanceLockError

pytestmark = pytest.mark.anyio
ApiClient = tuple[httpx2.AsyncClient, Path]


class NoopUnitOfWork:
    def __enter__(self):
        return self

    def commit(self) -> None:
        return None

    def __exit__(self, *_: object) -> bool:
        return False


def test_instance_lock_allows_only_one_writer_and_cleans_up(tmp_path: Path) -> None:
    first = InstanceLock(tmp_path)
    second = InstanceLock(tmp_path)
    first.acquire()
    with pytest.raises(InstanceLockError, match="Another Backend"):
        second.acquire()
    first.release()
    second.acquire()
    second.release()
    assert (tmp_path / ".backend.lock").exists()


async def test_second_app_is_rejected_before_it_can_change_storage(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        environment="test",
        data_root=tmp_path / "shared-data",
        scheduler_enabled=False,
    )
    first = create_app(settings)
    second = create_app(settings)
    async with first.router.lifespan_context(first):
        before = {
            path.relative_to(settings.data_root).as_posix()
            for path in settings.data_root.rglob("*")
        }
        with pytest.raises(InstanceLockError, match="Another Backend"):
            async with second.router.lifespan_context(second):
                pass
        after = {
            path.relative_to(settings.data_root).as_posix()
            for path in settings.data_root.rglob("*")
        }
        assert after == before


def test_mutation_publication_remains_inside_single_writer_boundary() -> None:
    publish_started = Event()
    allow_publish = Event()
    second_mutation_started = Event()

    class BlockingRuntimeState(RuntimeState):
        def publish_mutation(self, read_model, impact, *, label):
            if not publish_started.is_set():
                publish_started.set()
                assert allow_publish.wait(timeout=2)
            super().publish_mutation(read_model, impact, label=label)

    runtime = BlockingRuntimeState(Settings(_env_file=None, environment="test"))
    runtime.publish_initial(HouseholdReadModel.empty())
    coordinator = MutationCoordinator(runtime)
    failures: list[BaseException] = []

    def execute(label: str, started: Event | None = None) -> None:
        def mutation() -> MutationOutcome[None]:
            if started is not None:
                started.set()
            return MutationOutcome(
                None,
                ReadModelChange.finance_changed(
                    runtime.current_finance_state(),
                    MutationImpact.PROJECTIONS,
                ),
            )

        try:
            coordinator.execute(
                label=label,
                unit_of_work=NoopUnitOfWork(),
                mutation=mutation,
            )
        except BaseException as exc:  # surfaced on the main test thread below
            failures.append(exc)

    first = Thread(target=execute, args=("first",))
    second = Thread(target=execute, args=("second", second_mutation_started))
    first.start()
    assert publish_started.wait(timeout=2)
    second.start()
    assert not second_mutation_started.wait(timeout=0.1)
    allow_publish.set()
    first.join(timeout=2)
    second.join(timeout=2)
    assert not first.is_alive()
    assert not second.is_alive()
    assert not failures
    assert second_mutation_started.is_set()


def test_publication_failure_rolls_back_persisted_files(tmp_path: Path) -> None:
    target = tmp_path / "state.json"
    target.write_text("before", encoding="utf-8")

    class FailingRuntimeState(RuntimeState):
        def publish_mutation(self, read_model, impact, *, label):
            raise RuntimeError("publication failed")

    runtime = FailingRuntimeState(Settings(_env_file=None, environment="test"))
    runtime.publish_initial(HouseholdReadModel.empty())
    coordinator = MutationCoordinator(runtime)

    def mutation() -> MutationOutcome[None]:
        target.write_text("after", encoding="utf-8")
        return MutationOutcome(
            None,
            ReadModelChange.finance_changed(
                runtime.current_finance_state(),
                MutationImpact.PROJECTIONS,
            ),
        )

    with pytest.raises(RuntimeError, match="publication failed"):
        coordinator.execute(
            label="failing publication",
            unit_of_work=FileUnitOfWork((target,), label="failing publication"),
            mutation=mutation,
        )

    assert target.read_text(encoding="utf-8") == "before"
    assert runtime.snapshot().generation == 0
    assert runtime.snapshot().queued_mutations == 0


async def test_mutation_log_contains_request_and_timing_contract(
    api_client: ApiClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    client, _ = api_client
    caplog.set_level(logging.INFO, logger="family_spending_backend.runtime.coordinator")
    response = await client.post(
        "/api/v1/manual-inputs",
        headers={"X-Request-ID": "observability-test"},
        json={
            "transaction_type": "expense",
            "transaction_date": "2026-09-01",
            "amount": "12.34",
            "currency": "CNY",
            "description": "market",
        },
    )
    assert response.status_code == 201
    payload = next(
        json.loads(record.message)
        for record in caplog.records
        if '"command":"Manual Input create"' in record.message
    )
    assert payload["request_id"] == "observability-test"
    assert payload["result"] == "success"
    assert payload["impact"] == "transactions_and_downstream"
    for field in (
        "lock_wait_ms",
        "mutation_ms",
        "persistence_ms",
        "read_model_update_ms",
        "total_ms",
    ):
        assert payload[field] >= 0
