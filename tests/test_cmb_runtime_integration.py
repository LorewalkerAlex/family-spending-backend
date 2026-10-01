from email.message import EmailMessage
from pathlib import Path

import httpx2
import pytest

from family_spending_backend.config import Settings
from family_spending_backend.interfaces.http.app import create_app
from family_spending_backend.persistence.filesystem import (
    FilesystemCmbEmailEvidenceStore,
    FilesystemLayout,
)
from family_spending_backend.sources.cmb_email.evidence import CmbEmailEvidence

pytestmark = pytest.mark.anyio


def raw_statement() -> bytes:
    cells = ["", "0811", "0812", "CMB merchant", "¥ -7.81", "4529", "CN", "-7.81"]
    html = (
        '<table width="643" height="18"><tr>'
        + "".join(f"<td>{cell}</td>" for cell in cells)
        + "</tr></table>"
    )
    message = EmailMessage()
    message["Date"] = "Wed, 10 Sep 2025 08:00:00 +0800"
    message.set_content("fallback")
    message.add_alternative(html, subtype="html", charset="utf-8")
    return message.as_bytes()


async def test_startup_syncs_cmb_once_and_ordinary_commands_hit_parser_cache(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    layout = FilesystemLayout(data_root)
    layout.initialize()
    FilesystemCmbEmailEvidenceStore(layout).add(CmbEmailEvidence(raw_statement()))
    app = create_app(
        Settings(
            _env_file=None,
            environment="test",
            data_root=data_root,
            parser_version="cmb-v1",
        )
    )

    async with app.router.lifespan_context(app):
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(transport=transport, base_url="http://testserver") as client:
            initial = (await client.get("/api/v1/runtime/status")).json()["data"]
            assert initial["counts"]["source_records"] == 1
            assert initial["counts"]["transactions"] == 1
            assert initial["parser_cache_misses"] == 1
            assert initial["parser_cache_hits"] >= 1

            created = await client.post(
                "/api/v1/manual-inputs",
                json={
                    "transaction_type": "expense",
                    "transaction_date": "2026-09-01",
                    "amount": "12.00",
                    "currency": "CNY",
                    "description": "manual",
                },
            )
            assert created.status_code == 201
            after = (await client.get("/api/v1/runtime/status")).json()["data"]
            assert after["parser_cache_misses"] == 1
            assert after["parser_cache_hits"] > initial["parser_cache_hits"]

            generation = after["generation"]
            result = app.state.container.source_sync_service.sync()
            assert result.impact == "no_change"
            final = (await client.get("/api/v1/runtime/status")).json()["data"]
            assert final["generation"] == generation
            assert final["parser_cache_misses"] == 1
