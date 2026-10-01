from pathlib import Path

import httpx2
import pytest

pytestmark = pytest.mark.anyio
ApiClient = tuple[httpx2.AsyncClient, Path]


async def test_analytics_are_published_from_same_read_model_generation(
    api_client: ApiClient,
) -> None:
    client, _ = api_client
    await client.post(
        "/api/v1/manual-inputs",
        json={
            "transaction_type": "expense",
            "transaction_date": "2026-09-01",
            "amount": "12.34",
            "currency": "CNY",
            "description": "market",
        },
    )
    spending = await client.get("/api/v1/analytics/spending")
    financial = await client.get("/api/v1/analytics/financial")
    assert spending.status_code == 200
    assert spending.json()["data"]["schema_version"] == 2
    assert spending.json()["data"]["summary"]["all_data"]["total_spending_minor"] == 1234
    assert financial.json()["data"]["schema_version"] == 1
    assert financial.json()["data"]["summary"]["all_data"]["net_cash_flow_minor"] == -1234
