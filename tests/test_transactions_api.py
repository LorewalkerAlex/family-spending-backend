from pathlib import Path

import httpx2
import pytest
from fastapi import FastAPI

pytestmark = pytest.mark.anyio
ApiClient = tuple[httpx2.AsyncClient, Path]


def expense() -> dict[str, str]:
    return {
        "transaction_type": "expense",
        "transaction_date": "2026-09-01",
        "amount": "35.00",
        "currency": "CNY",
        "description": "咖啡订单",
    }


async def test_transaction_query_exposes_unclassified_derived_enrichment(
    api_client: ApiClient,
) -> None:
    client, _ = api_client
    created = (await client.post("/api/v1/manual-inputs", json=expense())).json()["data"]
    transaction_id = created["item"]["transaction_id"]

    listed = await client.get("/api/v1/transactions")
    assert listed.status_code == 200
    item = listed.json()["data"][0]
    assert item["transaction"]["id"] == transaction_id
    assert item["description"] == "咖啡订单"
    assert item["enrichment"]["category"] == "待分类"
    assert item["enrichment"]["is_unclassified"] is True
    assert (await client.get(f"/api/v1/transactions/{transaction_id}")).json()["data"] == item


async def test_sparse_enrichment_patch_persists_and_rebuilds_after_restart(
    api_client: ApiClient,
) -> None:
    client, data_root = api_client
    created = (await client.post("/api/v1/manual-inputs", json=expense())).json()["data"]
    transaction_id = created["item"]["transaction_id"]

    changed = await client.patch(
        f"/api/v1/transactions/{transaction_id}/enrichment",
        json={"merchant_override": "街角咖啡", "note": "早餐"},
    )
    assert changed.status_code == 200
    data = changed.json()["data"]
    assert data["mutation_impact"] == "enrichments_and_projections"
    assert data["decision"] == {
        "merchant_override": "街角咖啡",
        "category_override": None,
        "note": "早餐",
    }
    assert data["enrichment"]["display_name"] == "街角咖啡"
    assert data["enrichment"]["category"] == "待分类"
    stored = (data_root / "state" / "enrichment" / "decisions.jsonl").read_text(encoding="utf-8")
    assert "display_name" not in stored

    runtime = (await client.get("/api/v1/runtime/status")).json()["data"]
    assert runtime["generation"] == 2
    assert runtime["counts"]["enrichments"] == 1


async def test_enrichment_update_reuses_published_finance_inputs(
    api_app: tuple[FastAPI, Path],
) -> None:
    app, _ = api_app
    async with app.router.lifespan_context(app):
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
            created = (await client.post("/api/v1/manual-inputs", json=expense())).json()["data"]
            transaction_id = created["item"]["transaction_id"]
            before = app.state.container.runtime_state.read_model()
            changed = await client.patch(
                f"/api/v1/transactions/{transaction_id}/enrichment",
                json={"note": "reuse current finance"},
            )
            assert changed.status_code == 200
            after = app.state.container.runtime_state.read_model()
            assert after.finance is not before.finance
            assert after.source_records is before.source_records
            assert after.transactions is before.transactions
            assert after.source_links is before.source_links
            assert after.statement_dates is before.statement_dates
            assert after.automation is before.automation
            assert after.feedback_items is before.feedback_items


async def test_patch_can_clear_decision_and_rejects_invalid_requests(
    api_client: ApiClient,
) -> None:
    client, data_root = api_client
    created = (await client.post("/api/v1/manual-inputs", json=expense())).json()["data"]
    transaction_id = created["item"]["transaction_id"]
    await client.patch(
        f"/api/v1/transactions/{transaction_id}/enrichment", json={"note": "temporary"}
    )

    cleared = await client.patch(
        f"/api/v1/transactions/{transaction_id}/enrichment", json={"note": None}
    )
    assert cleared.status_code == 200
    assert cleared.json()["data"]["decision"] is None
    assert not (data_root / "state" / "enrichment" / "decisions.jsonl").exists()

    empty = await client.patch(f"/api/v1/transactions/{transaction_id}/enrichment", json={})
    assert empty.status_code == 422
    assert empty.json()["error"]["code"] == "domain.invalid"
    missing = await client.patch("/api/v1/transactions/txn_missing/enrichment", json={"note": "x"})
    assert missing.status_code == 404


async def test_transaction_list_supports_filter_sort_and_pagination_metadata(
    api_client: ApiClient,
) -> None:
    client, _ = api_client
    for transaction_date, amount in (("2026-09-02", "20.00"), ("2026-09-01", "10.00")):
        response = await client.post(
            "/api/v1/manual-inputs",
            json={**expense(), "transaction_date": transaction_date, "amount": amount},
        )
        assert response.status_code == 201

    response = await client.get(
        "/api/v1/transactions",
        params={
            "transaction_type": "expense",
            "is_unclassified": "true",
            "sort": "date_asc",
            "offset": 1,
            "limit": 1,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["meta"] == {
        "request_id": response.headers["X-Request-ID"],
        "offset": 1,
        "limit": 1,
        "total": 2,
        "sort": "date_asc",
    }
    assert [item["transaction"]["transaction_date"] for item in body["data"]] == ["2026-09-02"]
