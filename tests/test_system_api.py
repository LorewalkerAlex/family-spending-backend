from pathlib import Path

import httpx2
import pytest

pytestmark = pytest.mark.anyio


ApiClient = tuple[httpx2.AsyncClient, Path]


async def test_health_uses_v1_success_contract_and_request_id(
    api_client: ApiClient,
) -> None:
    client, _ = api_client
    response = await client.get(
        "/api/v1/health",
        headers={"X-Request-ID": "test-request-1"},
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "test-request-1"
    assert response.json() == {
        "data": {
            "status": "ok",
            "service": "family-spending-backend",
            "version": "0.1.0",
        },
        "meta": {"request_id": "test-request-1"},
    }


async def test_runtime_status_reports_bootstrapped_empty_model(
    api_client: ApiClient,
) -> None:
    client, data_root = api_client
    response = await client.get("/api/v1/runtime/status")

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["phase"] == "ready"
    assert body["data"]["generation"] == 0
    assert body["data"]["queued_mutations"] == 0
    assert body["data"]["counts"] == {
        "source_records": 0,
        "transactions": 0,
        "enrichments": 0,
        "mapping_reviews": 0,
        "feedback": 0,
    }
    assert body["data"]["schema_version"] == "1"
    assert body["data"]["parser_version"] == "cmb-v1"
    assert body["meta"]["request_id"] == response.headers["X-Request-ID"]
    assert data_root.is_dir()


async def test_unknown_route_uses_v1_error_contract(
    api_client: ApiClient,
) -> None:
    client, _ = api_client
    response = await client.get(
        "/api/v1/does-not-exist",
        headers={"X-Request-ID": "missing-route"},
    )

    assert response.status_code == 404
    assert response.headers["X-Request-ID"] == "missing-route"
    assert response.json() == {
        "error": {
            "code": "http.not_found",
            "message": "The requested resource was not found.",
            "request_id": "missing-route",
            "details": None,
        }
    }


async def test_openapi_contract_is_versioned_and_contains_system_routes(
    api_client: ApiClient,
) -> None:
    client, _ = api_client
    response = await client.get("/api/v1/openapi.json")

    assert response.status_code == 200
    contract = response.json()
    assert contract["info"]["version"] == "0.1.0"
    assert {
        "/api/v1/health",
        "/api/v1/runtime/status",
        "/api/v1/transactions",
        "/api/v1/transactions/{transaction_id}",
        "/api/v1/transactions/{transaction_id}/enrichment",
        "/api/v1/analytics/spending",
        "/api/v1/analytics/financial",
        "/api/v1/mapping-reviews",
        "/api/v1/mapping-reviews/recommend",
        "/api/v1/mapping-reviews/preview",
        "/api/v1/mapping-reviews/apply",
        "/api/v1/manual-inputs",
        "/api/v1/manual-inputs/{evidence_id}",
        "/api/v1/scheduled-inputs",
        "/api/v1/scheduled-inputs/{rule_id}",
        "/api/v1/scheduled-inputs/run-due",
        "/api/v1/feedback",
        "/api/v1/feedback/{feedback_id}",
    } <= set(contract["paths"])
    assert "ErrorResponse" in contract["components"]["schemas"]
