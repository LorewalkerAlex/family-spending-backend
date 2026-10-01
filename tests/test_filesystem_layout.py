from pathlib import Path

import pytest

from family_spending_backend.persistence.filesystem import (
    FilesystemLayout,
    StorageManifestError,
    read_manifest,
)
from family_spending_backend.read_model import ReadModelBootstrap


def test_initialize_creates_only_the_declared_directories(tmp_path: Path) -> None:
    layout = FilesystemLayout(tmp_path / "data")

    layout.initialize()

    relative_directories = {
        path.relative_to(layout.root).as_posix() for path in layout.required_directories
    }
    assert relative_directories == {
        "evidence/cmb-email",
        "evidence/manual",
        "state/identity",
        "state/enrichment",
        "state/mappings",
        "state/schedules",
        "state/feedback",
        "derived",
    }
    assert all(path.is_dir() for path in layout.required_directories)
    assert read_manifest(layout).storage_schema_version == 1
    assert [path.name for path in layout.root.rglob("*") if path.is_file()] == ["manifest.json"]


def test_initialize_is_idempotent(tmp_path: Path) -> None:
    layout = FilesystemLayout(tmp_path / "data")

    layout.initialize()
    layout.initialize()

    assert all(path.is_dir() for path in layout.required_directories)


def test_initialize_rejects_nonempty_unversioned_root(tmp_path: Path) -> None:
    layout = FilesystemLayout(tmp_path / "data")
    existing_directory = layout.root / "state" / "mappings"
    existing_directory.mkdir(parents=True)
    existing_file = existing_directory / "existing.json"
    existing_file.write_text('{"preserved": true}', encoding="utf-8")

    with pytest.raises(StorageManifestError, match="non-empty"):
        layout.initialize()
    assert existing_file.read_text(encoding="utf-8") == '{"preserved": true}'


def test_bootstrap_requires_initialized_layout(tmp_path: Path) -> None:
    layout = FilesystemLayout(tmp_path / "missing")

    with pytest.raises(RuntimeError, match="must be initialized"):
        ReadModelBootstrap(layout).build()


def test_bootstrap_starts_with_truthful_empty_counts(tmp_path: Path) -> None:
    layout = FilesystemLayout(tmp_path / "data")
    layout.initialize()

    read_model = ReadModelBootstrap(layout).build()

    assert read_model.counts.transactions == 0
    assert read_model.counts.enrichments == 0
    assert read_model.counts.mapping_reviews == 0
    assert read_model.counts.feedback == 0
