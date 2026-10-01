from collections.abc import AsyncIterator
from pathlib import Path

import httpx2
import pytest

from family_spending_backend.config import Settings
from family_spending_backend.domain.mapping import MappingCatalog
from family_spending_backend.interfaces.http.app import create_app
from family_spending_backend.persistence.filesystem import FilesystemLayout, FilesystemMappingStore

pytestmark = pytest.mark.anyio


def expense(description: str) -> dict[str, str]:
    return {
        "transaction_type": "expense",
        "transaction_date": "2026-09-01",
        "amount": "35.00",
        "currency": "CNY",
        "description": description,
    }


async def seeded_client(
    data_root: Path,
) -> AsyncIterator[tuple[httpx2.AsyncClient, FilesystemLayout]]:
    layout = FilesystemLayout(data_root)
    layout.initialize()
    FilesystemMappingStore(layout).replace(
        MappingCatalog(
            {
                "已有描述": "已有商户",
                "支付宝-瑞幸咖啡": "瑞幸咖啡",
            },
            {"已有商户": "餐饮", "瑞幸咖啡": "餐饮"},
            frozenset({"餐饮"}),
        )
    )
    app = create_app(Settings(_env_file=None, environment="test", data_root=data_root))
    async with app.router.lifespan_context(app):
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client, layout


async def test_mapping_review_preview_apply_updates_derived_enrichment_not_identity(
    tmp_path: Path,
) -> None:
    async for client, layout in seeded_client(tmp_path / "data"):
        created = (await client.post("/api/v1/manual-inputs", json=expense("新描述"))).json()[
            "data"
        ]
        transaction_id = created["item"]["transaction_id"]
        workspace = (await client.get("/api/v1/mapping-reviews")).json()["data"]
        assert workspace["items"][0]["description"] == "新描述"
        assert workspace["categories"] == ["餐饮"]

        request = {"description": "新描述", "merchant": "已有商户", "category": "餐饮"}
        preview = (await client.post("/api/v1/mapping-reviews/preview", json=request)).json()[
            "data"
        ]
        assert preview["is_new_merchant"] is False
        assert preview["total_affected_transaction_count"] == 1

        applied = await client.post(
            "/api/v1/mapping-reviews/apply",
            json={**request, "preview_token": preview["token"]},
        )
        assert applied.status_code == 200
        assert applied.json()["data"]["mutation_impact"] == "enrichments_and_projections"
        transaction = (await client.get(f"/api/v1/transactions/{transaction_id}")).json()["data"]
        assert transaction["transaction"]["id"] == transaction_id
        assert transaction["enrichment"]["merchant_name"] == "已有商户"
        assert transaction["enrichment"]["category"] == "餐饮"
        assert FilesystemMappingStore(layout).load().description_to_merchant["新描述"] == "已有商户"
        assert (await client.get("/api/v1/mapping-reviews")).json()["data"]["items"] == []


async def test_new_merchant_requires_confirmation(tmp_path: Path) -> None:
    async for client, _ in seeded_client(tmp_path / "data"):
        await client.post("/api/v1/manual-inputs", json=expense("新描述"))
        request = {"description": "新描述", "merchant": "新商户", "category": "餐饮"}
        preview = (await client.post("/api/v1/mapping-reviews/preview", json=request)).json()[
            "data"
        ]
        rejected = await client.post(
            "/api/v1/mapping-reviews/apply",
            json={**request, "preview_token": preview["token"]},
        )
        assert rejected.status_code == 422
        assert rejected.json()["error"]["code"] == "application.invalid"
        accepted = await client.post(
            "/api/v1/mapping-reviews/apply",
            json={
                **request,
                "preview_token": preview["token"],
                "confirm_new_merchant": True,
            },
        )
        assert accepted.status_code == 200


async def test_recommendation_prefills_review_without_writing_mapping(tmp_path: Path) -> None:
    async for client, layout in seeded_client(tmp_path / "data"):
        description = "财付通-瑞幸咖啡"
        await client.post("/api/v1/manual-inputs", json=expense(description))
        mapping_store = FilesystemMappingStore(layout)
        before = mapping_store.load()
        generation = (await client.get("/api/v1/runtime/status")).json()["data"]["generation"]

        workspace = (await client.get("/api/v1/mapping-reviews")).json()["data"]
        item = next(value for value in workspace["items"] if value["description"] == description)
        suggestion = item["recommendation"]
        assert suggestion["merchant"] == "瑞幸咖啡"
        assert suggestion["category"] == "餐饮"
        assert suggestion["origin"] == "normalized_history"
        assert suggestion["confidence"] == "strong"
        assert suggestion["model_version"] == "mapping-ensemble-v2"

        response = await client.post(
            "/api/v1/mapping-reviews/recommend",
            json={"description": description},
        )
        assert response.status_code == 200
        assert response.json()["data"] == suggestion
        assert mapping_store.load() == before
        after_generation = (await client.get("/api/v1/runtime/status")).json()["data"]["generation"]
        assert after_generation == generation


async def test_recommendation_rejects_non_pending_description(tmp_path: Path) -> None:
    async for client, _ in seeded_client(tmp_path / "data"):
        response = await client.post(
            "/api/v1/mapping-reviews/recommend",
            json={"description": "支付宝-瑞幸咖啡"},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "application.invalid"


async def test_preview_token_detects_changed_enrichment_decisions(tmp_path: Path) -> None:
    async for client, _ in seeded_client(tmp_path / "data"):
        created = (await client.post("/api/v1/manual-inputs", json=expense("新描述"))).json()[
            "data"
        ]
        transaction_id = created["item"]["transaction_id"]
        request = {"description": "新描述", "merchant": "已有商户", "category": "餐饮"}
        token = (await client.post("/api/v1/mapping-reviews/preview", json=request)).json()["data"][
            "token"
        ]
        await client.patch(
            f"/api/v1/transactions/{transaction_id}/enrichment", json={"note": "changed"}
        )
        stale = await client.post(
            "/api/v1/mapping-reviews/apply",
            json={**request, "preview_token": token},
        )
        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == "state.conflict"
