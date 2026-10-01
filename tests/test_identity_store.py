import json
from pathlib import Path

import pytest

from family_spending_backend.domain.transaction import SourceLink
from family_spending_backend.persistence.filesystem import (
    FilesystemIdentityStore,
    FilesystemLayout,
    IdentityStoreError,
    atomic,
)


def store(root: Path) -> FilesystemIdentityStore:
    return FilesystemIdentityStore(FilesystemLayout(root))


def test_missing_store_is_empty_and_round_trip_preserves_order(tmp_path: Path) -> None:
    identity_store = store(tmp_path / "data")
    links = (
        SourceLink("txn_a", "src_a", "authoritative"),
        SourceLink("txn_a", "src_b", "supporting"),
        SourceLink("txn_b", "src_c", "authoritative"),
    )

    assert identity_store.load() == ()
    identity_store.replace(links)

    assert identity_store.load() == links
    assert identity_store.path.read_bytes().endswith(b"\n")


def test_replace_rejects_invalid_identity_structure(tmp_path: Path) -> None:
    identity_store = store(tmp_path / "data")
    invalid_sets = (
        (
            SourceLink("txn_a", "src_a", "authoritative"),
            SourceLink("txn_b", "src_a", "authoritative"),
        ),
        (
            SourceLink("txn_a", "src_a", "authoritative"),
            SourceLink("txn_a", "src_b", "authoritative"),
        ),
    )

    for links in invalid_sets:
        with pytest.raises(IdentityStoreError):
            identity_store.replace(links)


def test_load_rejects_unknown_fields_and_supporting_only_state(tmp_path: Path) -> None:
    identity_store = store(tmp_path / "data")
    identity_store.path.parent.mkdir(parents=True)
    identity_store.path.write_text(
        json.dumps(
            {
                "transaction_id": "txn_a",
                "source_record_id": "src_a",
                "role": "authoritative",
                "legacy": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(IdentityStoreError, match="Invalid SourceLink"):
        identity_store.load()

    identity_store.path.write_text(
        json.dumps(
            {
                "transaction_id": "txn_a",
                "source_record_id": "src_a",
                "role": "supporting",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(IdentityStoreError, match="no authoritative"):
        identity_store.load()


def test_load_reports_malformed_line_number(tmp_path: Path) -> None:
    identity_store = store(tmp_path / "data")
    identity_store.path.parent.mkdir(parents=True)
    identity_store.path.write_text("\n{not-json}\n", encoding="utf-8")

    with pytest.raises(IdentityStoreError, match="line 2"):
        identity_store.load()


def test_empty_replace_removes_identity_file(tmp_path: Path) -> None:
    identity_store = store(tmp_path / "data")
    identity_store.replace((SourceLink("txn_a", "src_a", "authoritative"),))

    identity_store.replace(())

    assert not identity_store.path.exists()


def test_failed_atomic_replace_preserves_previous_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity_store = store(tmp_path / "data")
    original = (SourceLink("txn_original", "src_original", "authoritative"),)
    identity_store.replace(original)

    def fail_replace(source: Path, destination: Path) -> None:
        del source, destination
        raise OSError("simulated replace failure")

    monkeypatch.setattr(atomic.os, "replace", fail_replace)

    with pytest.raises(IdentityStoreError, match="simulated replace failure"):
        identity_store.replace((SourceLink("txn_new", "src_new", "authoritative"),))

    assert identity_store.load() == original
    assert not tuple(identity_store.path.parent.glob("*.tmp"))
