from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx2
import pytest

from family_spending_backend.domain.errors import DomainInvariantError
from family_spending_backend.domain.scheduling import (
    ScheduledRule,
    ScheduleExecutionState,
    next_occurrence_date,
    scheduled_occurrence_identity,
)
from family_spending_backend.persistence.filesystem import (
    FilesystemLayout,
    FilesystemScheduleStore,
)

pytestmark = pytest.mark.anyio
ApiClient = tuple[httpx2.AsyncClient, Path]


def test_schedule_identity_and_cursor_are_stable() -> None:
    rule = ScheduledRule(
        "schedule_salary",
        True,
        "income",
        Decimal("1000"),
        "salary",
        date(2026, 8, 15),
    )
    execution = ScheduleExecutionState(
        rule.id,
        date(2026, 9, 15),
        "src_1",
        "txn_1",
        "created",
    )
    assert next_occurrence_date(rule, execution) == date(2026, 10, 15)
    first = scheduled_occurrence_identity(rule.id, date(2026, 8, 15))
    assert first == scheduled_occurrence_identity(rule.id, date(2026, 8, 15))
    assert first != scheduled_occurrence_identity(rule.id, date(2026, 9, 15))
    with pytest.raises(DomainInvariantError, match="1-28"):
        ScheduledRule("bad", True, "expense", Decimal("1"), "bad", date(2026, 8, 29))


def test_schedule_store_keeps_rules_and_execution_separate(tmp_path: Path) -> None:
    layout = FilesystemLayout(tmp_path)
    store = FilesystemScheduleStore(layout)
    rule = ScheduledRule(
        "schedule_salary",
        True,
        "income",
        Decimal("1000"),
        "salary",
        date(2026, 10, 6),
    )
    execution = ScheduleExecutionState(rule.id, date(2026, 10, 6), "src_1", "txn_1", "created")
    store.replace_rules((rule,))
    store.replace_execution((execution,))
    assert store.load_rules() == (rule,)
    assert store.load_execution() == (execution,)
    store.replace_execution(())
    assert store.load_rules() == (rule,)
    assert not layout.schedule_execution.exists()


async def test_empty_tick_is_no_change_and_due_run_is_idempotent(
    api_client: ApiClient,
) -> None:
    client, _ = api_client
    created = await client.post(
        "/api/v1/scheduled-inputs",
        json={
            "enabled": True,
            "transaction_type": "income",
            "amount": "1000",
            "currency": "CNY",
            "description": "salary",
            "first_occurrence_date": "2099-10-06",
            "note": "monthly",
        },
    )
    assert created.status_code == 201
    rule = created.json()["data"]
    generation = (await client.get("/api/v1/runtime/status")).json()["data"]["generation"]

    empty = await client.post("/api/v1/scheduled-inputs/run-due", json={"as_of": "2099-10-05"})
    assert empty.status_code == 200
    assert empty.json()["data"] == {
        "occurrences": [],
        "mutation_impact": "no_change",
    }
    assert (await client.get("/api/v1/runtime/status")).json()["data"]["generation"] == generation

    due = await client.post("/api/v1/scheduled-inputs/run-due", json={"as_of": "2099-11-06"})
    assert due.status_code == 200
    occurrences = due.json()["data"]["occurrences"]
    assert len(occurrences) == 2
    assert {item["occurrence_date"] for item in occurrences} == {
        "2099-10-06",
        "2099-11-06",
    }
    assert due.json()["data"]["mutation_impact"] == "transactions_and_downstream"
    transactions = (await client.get("/api/v1/transactions")).json()["data"]
    assert len(transactions) == 2
    assert all(item["enrichment"]["note"] == "monthly" for item in transactions)

    generation = (await client.get("/api/v1/runtime/status")).json()["data"]["generation"]
    repeated = await client.post("/api/v1/scheduled-inputs/run-due", json={"as_of": "2099-11-06"})
    assert repeated.json()["data"]["occurrences"] == []
    assert (await client.get("/api/v1/runtime/status")).json()["data"]["generation"] == generation
    listed = (await client.get("/api/v1/scheduled-inputs")).json()["data"]
    assert listed[0]["id"] == rule["id"]
    assert listed[0]["last_occurrence_date"] == "2099-11-06"
    assert listed[0]["next_date"] == "2099-12-06"
