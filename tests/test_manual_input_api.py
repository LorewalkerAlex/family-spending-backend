from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx2
import pytest
from fastapi import FastAPI

from family_spending_backend.config import Settings
from family_spending_backend.domain.manual import create_manual_evidence
from family_spending_backend.interfaces.http.app import create_app
from family_spending_backend.persistence.filesystem import FilesystemIdentityStore

pytestmark = pytest.mark.anyio
ApiClient = tuple[httpx2.AsyncClient, Path]


def payload(*, amount: str = "12.34", when: str = "2026-09-01") -> dict[str, str]:
    return {
        "transaction_type": "expense",
        "transaction_date": when,
        "amount": amount,
        "currency": "CNY",
        "description": "market",
    }


async def test_create_list_and_runtime_status_use_published_read_model(
    api_client: ApiClient,
) -> None:
    client, data_root = api_client

    created = await client.post("/api/v1/manual-inputs", json=payload())

    assert created.status_code == 201
    created_data = created.json()["data"]
    assert created_data["action"] == "created"
    assert created_data["mutation_impact"] == "transactions_and_downstream"
    assert created_data["item"]["source_role"] == "authoritative"
    assert created_data["item"]["transaction"]["amount"] == "12.34"

    listed = await client.get("/api/v1/manual-inputs")
    assert listed.status_code == 200
    assert listed.json()["data"] == [created_data["item"]]

    runtime = (await client.get("/api/v1/runtime/status")).json()["data"]
    assert runtime["generation"] == 1
    assert runtime["last_successful_mutation"] == "Manual Input create"
    assert runtime["counts"]["source_records"] == 1
    assert runtime["counts"]["transactions"] == 1
    assert (data_root / "evidence" / "manual" / "records.jsonl").exists()
    assert (data_root / "state" / "identity" / "source-links.jsonl").exists()


async def test_identical_manual_evidence_matches_as_supporting(
    api_client: ApiClient,
) -> None:
    client, _ = api_client
    first = (await client.post("/api/v1/manual-inputs", json=payload())).json()["data"]
    second = (await client.post("/api/v1/manual-inputs", json=payload())).json()["data"]

    assert second["action"] == "matched"
    assert second["item"]["source_role"] == "supporting"
    assert second["item"]["transaction_id"] == first["item"]["transaction_id"]

    runtime = (await client.get("/api/v1/runtime/status")).json()["data"]
    assert runtime["generation"] == 2
    assert runtime["counts"]["source_records"] == 2
    assert runtime["counts"]["transactions"] == 1


async def test_correction_preserves_standalone_transaction_identity(
    api_client: ApiClient,
) -> None:
    client, _ = api_client
    created = (await client.post("/api/v1/manual-inputs", json=payload())).json()["data"]
    evidence_id = created["item"]["evidence_id"]
    transaction_id = created["item"]["transaction_id"]

    corrected_response = await client.put(
        f"/api/v1/manual-inputs/{evidence_id}",
        json=payload(amount="99.00", when="2026-09-02"),
    )

    assert corrected_response.status_code == 200
    corrected = corrected_response.json()["data"]
    assert corrected["action"] == "reused"
    assert corrected["item"]["transaction_id"] == transaction_id
    assert corrected["item"]["transaction"]["amount"] == "99.00"


async def test_delete_removes_standalone_transaction_and_missing_is_404(
    api_client: ApiClient,
) -> None:
    client, _ = api_client
    created = (await client.post("/api/v1/manual-inputs", json=payload())).json()["data"]
    evidence_id = created["item"]["evidence_id"]

    deleted = await client.delete(f"/api/v1/manual-inputs/{evidence_id}")

    assert deleted.status_code == 200
    assert deleted.json()["data"]["transaction_removed"] is True
    assert (await client.get("/api/v1/manual-inputs")).json()["data"] == []
    runtime = (await client.get("/api/v1/runtime/status")).json()["data"]
    assert runtime["generation"] == 2
    assert runtime["counts"]["transactions"] == 0

    missing = await client.delete("/api/v1/manual-inputs/missing")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "resource.not_found"


async def test_invalid_manual_input_uses_unified_validation_error(
    api_client: ApiClient,
) -> None:
    client, _ = api_client

    response = await client.post(
        "/api/v1/manual-inputs",
        json=payload(amount="not-money"),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request.validation_failed"


async def test_restart_rebuilds_read_model_from_durable_manual_state(tmp_path: Path) -> None:
    data_root = tmp_path / "restart-data"
    settings = Settings(_env_file=None, environment="test", data_root=data_root)
    first_app = create_app(settings)
    async with first_app.router.lifespan_context(first_app):
        transport = httpx2.ASGITransport(app=first_app)
        async with httpx2.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            created = (await client.post("/api/v1/manual-inputs", json=payload())).json()

    restarted_app = create_app(settings)
    async with restarted_app.router.lifespan_context(restarted_app):
        transport = httpx2.ASGITransport(app=restarted_app)
        async with httpx2.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            listed = (await client.get("/api/v1/manual-inputs")).json()
            runtime = (await client.get("/api/v1/runtime/status")).json()["data"]

    assert listed["data"] == [created["data"]["item"]]
    assert runtime["generation"] == 0
    assert runtime["counts"]["source_records"] == 1
    assert runtime["counts"]["transactions"] == 1


async def test_identity_failure_rolls_back_evidence_and_runtime(
    api_app: tuple[FastAPI, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, _ = api_app
    async with app.router.lifespan_context(app):

        def fail_replace(
            identity_store: FilesystemIdentityStore,
            links: object,
        ) -> None:
            del identity_store, links
            raise OSError("simulated identity failure")

        monkeypatch.setattr(FilesystemIdentityStore, "replace", fail_replace)
        evidence = create_manual_evidence(
            transaction_type="expense",
            transaction_date=date(2026, 9, 1),
            amount=Decimal("12.34"),
            description="market",
        )

        with pytest.raises(OSError, match="simulated identity failure"):
            app.state.container.manual_input_service.create(evidence)

        assert app.state.container.manual_evidence_store.load_all() == ()
        assert app.state.container.identity_store.load() == ()
        runtime = app.state.container.runtime_state.snapshot()
        assert runtime.generation == 0
        assert runtime.queued_mutations == 0
        assert runtime.last_failed_mutation == "Manual Input create"
