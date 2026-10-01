from pathlib import Path

import httpx2
import pytest
from fastapi import FastAPI

pytestmark = pytest.mark.anyio
ApiClient = tuple[httpx2.AsyncClient, Path]


async def test_feedback_mutation_preserves_financial_read_model_objects(
    api_app: tuple[FastAPI, Path],
) -> None:
    app, data_root = api_app
    async with app.router.lifespan_context(app):
        before = app.state.container.runtime_state.read_model()
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
            created = await client.post(
                "/api/v1/feedback",
                json={
                    "content": "  Overview needs polish  ",
                    "context": {
                        "runtime": "desktop_web",
                        "page": "overview",
                        "entity_type": "transaction",
                        "entity_id": "txn_1",
                    },
                },
            )
            assert created.status_code == 201
            item = created.json()["data"]
            assert item["content"] == "Overview needs polish"
            assert item["status"] == "open"

            after = app.state.container.runtime_state.read_model()
            assert after.spending_projection is before.spending_projection
            assert after.financial_projection is before.financial_projection
            assert after.transactions is before.transactions
            assert after.counts.feedback == 1

            status_before = (await client.get("/api/v1/runtime/status")).json()["data"]
            resolved = await client.patch(
                f"/api/v1/feedback/{item['id']}", json={"status": "resolved"}
            )
            assert resolved.status_code == 200
            generation_after_resolve = (await client.get("/api/v1/runtime/status")).json()["data"][
                "generation"
            ]
            repeated = await client.patch(
                f"/api/v1/feedback/{item['id']}", json={"status": "resolved"}
            )
            assert repeated.status_code == 200
            status_after = (await client.get("/api/v1/runtime/status")).json()["data"]
            assert generation_after_resolve == status_before["generation"] + 1
            assert status_after["generation"] == generation_after_resolve
            assert (data_root / "state" / "feedback" / "feedback.jsonl").exists()


async def test_feedback_list_is_newest_first_and_context_pair_is_validated(
    api_client: ApiClient,
) -> None:
    client, _ = api_client
    first = (await client.post("/api/v1/feedback", json={"content": "first"})).json()["data"]
    second = (await client.post("/api/v1/feedback", json={"content": "second"})).json()["data"]
    listed = (await client.get("/api/v1/feedback")).json()["data"]
    assert [item["id"] for item in listed] == [second["id"], first["id"]]

    invalid = await client.post(
        "/api/v1/feedback",
        json={"content": "bad", "context": {"entity_type": "transaction"}},
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "domain.invalid"
