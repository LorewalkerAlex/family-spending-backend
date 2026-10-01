from pathlib import Path

import pytest

from family_spending_backend.persistence.filesystem import (
    FileUnitOfWork,
    FileUnitOfWorkError,
)


def test_commit_keeps_all_file_changes(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"

    with FileUnitOfWork((first, second), label="test") as unit_of_work:
        first.write_bytes(b"new first")
        second.write_bytes(b"new second")
        unit_of_work.commit()

    assert first.read_bytes() == b"new first"
    assert second.read_bytes() == b"new second"


def test_exception_restores_existing_bytes_and_removes_new_file(tmp_path: Path) -> None:
    existing = tmp_path / "existing"
    created = tmp_path / "created"
    existing.write_bytes(b"original")

    with (
        pytest.raises(RuntimeError, match="mutation failed"),
        FileUnitOfWork((existing, created), label="test"),
    ):
        existing.write_bytes(b"changed")
        created.write_bytes(b"temporary")
        raise RuntimeError("mutation failed")

    assert existing.read_bytes() == b"original"
    assert not created.exists()


def test_leaving_without_commit_rolls_back(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_bytes(b"original")

    with (
        pytest.raises(FileUnitOfWorkError, match="without commit"),
        FileUnitOfWork((target,), label="test"),
    ):
        target.write_bytes(b"changed")

    assert target.read_bytes() == b"original"
