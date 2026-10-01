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
    assert spending.json()["data"]["currency"] == "CNY"
    assert spending.json()["data"]["schema_version"] == 2
    assert spending.json()["data"]["summary"]["all_data"]["total_spending_minor"] == 1234
    assert spending.json()["data"]["reconciliation"] == {
        "zero_amount_transactions": 0,
        "refund_transactions": 0,
        "same_merchant_refund_matches": 0,
        "same_merchant_matched_amount_minor": 0,
        "net_consumption_transactions": 1,
        "fully_refunded_transactions": 0,
        "partially_refunded_transactions": 0,
        "unmatched_refund_count": 0,
        "unmatched_refund_amount_minor": 0,
        "unclassified_net_transactions": 1,
    }
    assert financial.json()["data"]["schema_version"] == 1
    assert financial.json()["data"]["currency"] == "CNY"
    assert financial.json()["data"]["summary"]["all_data"]["net_cash_flow_minor"] == -1234

    openapi = (await client.get("/api/v1/openapi.json")).json()
    spending_schema = openapi["paths"]["/api/v1/analytics/spending"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]["$ref"]
    financial_schema = openapi["paths"]["/api/v1/analytics/financial"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]["$ref"]
    assert "SpendingAnalyticsData" in spending_schema
    assert "FinancialAnalyticsData" in financial_schema
