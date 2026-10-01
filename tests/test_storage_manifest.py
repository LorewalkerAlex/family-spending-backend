import json
from datetime import datetime
from pathlib import Path

import pytest

from family_spending_backend.persistence.filesystem import (
    FilesystemLayout,
    StorageManifestError,
    StorageMigrationRequiredError,
    UnsupportedStorageSchemaError,
    initialize_storage,
    read_manifest,
)


def test_manifest_fails_closed_for_older_and_newer_schema(tmp_path: Path) -> None:
    layout = FilesystemLayout(tmp_path / "data")
    layout.initialize()
    payload = json.loads(layout.manifest.read_text(encoding="utf-8"))
    payload["storage_schema_version"] = 2
    layout.manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(UnsupportedStorageSchemaError):
        layout.initialize()

    payload["storage_schema_version"] = 0
    layout.manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(Exception, match="positive integer"):
        read_manifest(layout)


def test_explicit_older_positive_schema_requires_migration(tmp_path: Path, monkeypatch) -> None:
    layout = FilesystemLayout(tmp_path / "data")
    layout.initialize()
    payload = json.loads(layout.manifest.read_text(encoding="utf-8"))
    payload["storage_schema_version"] = 1
    layout.manifest.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(
        "family_spending_backend.persistence.filesystem.manifest.CURRENT_STORAGE_SCHEMA_VERSION",
        2,
    )
    with pytest.raises(StorageMigrationRequiredError):
        layout.initialize()


def test_manifest_initialization_rejects_naive_timestamp(tmp_path: Path) -> None:
    layout = FilesystemLayout(tmp_path / "data")
    with pytest.raises(StorageManifestError, match="timezone-aware"):
        initialize_storage(layout, now=datetime(2026, 9, 30))
