from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]


def test_compose_defines_one_read_only_backend_writer() -> None:
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    assert set(compose["services"]) == {"backend"}
    backend = compose["services"]["backend"]
    assert backend["container_name"] == "family-spending-backend"
    assert backend["init"] is True
    assert backend["user"] == "${PUID:-10001}:${PGID:-10001}"
    assert backend["read_only"] is True
    assert backend["volumes"] == [{"type": "bind", "source": "./data", "target": "/app/data"}]
    assert backend["cap_drop"] == ["ALL"]
    assert backend["security_opt"] == ["no-new-privileges:true"]
    assert backend["environment"]["FAMILY_SPENDING_DATA_ROOT"] == "/app/data"
    assert backend["environment"]["FAMILY_SPENDING_ENVIRONMENT"] == "production"


def test_image_contract_runs_non_root_single_worker_with_healthcheck() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    entrypoint = (
        ROOT / "src" / "family_spending_backend" / "interfaces" / "http" / "main.py"
    ).read_text(encoding="utf-8")
    assert "FROM python:3.14-slim-trixie" in dockerfile
    assert "COPY pyproject.toml uv.lock README.md ./" in dockerfile
    assert "uv sync --frozen --no-dev" in dockerfile
    assert "USER 10001:10001" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert 'CMD ["family-spending-api"]' in dockerfile
    assert "workers=1" in entrypoint
