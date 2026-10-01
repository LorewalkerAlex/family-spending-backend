"""Rollback-capable commit boundary spanning a small set of files."""

import os
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType


class FileUnitOfWorkError(RuntimeError):
    """A filesystem commit boundary failed."""


class FileUnitOfWorkRollbackError(FileUnitOfWorkError):
    """Rollback could not restore every captured file."""


@dataclass(frozen=True, slots=True)
class _FileSnapshot:
    path: Path
    existed: bool
    contents: bytes | None


def _snapshot_file(path: Path) -> _FileSnapshot:
    if not path.exists():
        return _FileSnapshot(path, False, None)
    return _FileSnapshot(path, True, path.read_bytes())


def _restore_file(snapshot: _FileSnapshot) -> None:
    if not snapshot.existed:
        snapshot.path.unlink(missing_ok=True)
        return
    assert snapshot.contents is not None
    snapshot.path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{snapshot.path.name}.",
        suffix=".rollback",
        dir=snapshot.path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(snapshot.contents)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, snapshot.path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


class FileUnitOfWork:
    """Restore exact pre-mutation bytes unless commit is explicit."""

    def __init__(self, paths: Iterable[Path], *, label: str) -> None:
        self._paths = tuple(dict.fromkeys(Path(path) for path in paths))
        if not self._paths:
            raise ValueError("FileUnitOfWork requires at least one path")
        if not label.strip():
            raise ValueError("FileUnitOfWork label must not be empty")
        self._label = label
        self._snapshots: tuple[_FileSnapshot, ...] | None = None
        self._committed = False

    def __enter__(self) -> FileUnitOfWork:
        if self._snapshots is not None:
            raise FileUnitOfWorkError(f"{self._label} unit of work cannot be entered twice")
        self._snapshots = tuple(_snapshot_file(path) for path in self._paths)
        return self

    def commit(self) -> None:
        if self._snapshots is None:
            raise FileUnitOfWorkError(f"{self._label} unit of work has not been entered")
        self._committed = True

    def _rollback(self, original_error: BaseException) -> None:
        assert self._snapshots is not None
        failures: list[str] = []
        for snapshot in reversed(self._snapshots):
            try:
                _restore_file(snapshot)
            except Exception as error:  # pragma: no cover - secondary storage failure
                failures.append(f"{snapshot.path}: {error}")
        if failures:
            raise FileUnitOfWorkRollbackError(
                f"{self._label} rollback could not fully restore state: " + "; ".join(failures)
            ) from original_error

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        del exc_type, traceback
        assert self._snapshots is not None
        if exc is not None:
            self._rollback(exc)
            return False
        if self._committed:
            return False
        error = FileUnitOfWorkError(f"{self._label} left its unit of work without commit()")
        self._rollback(error)
        raise error
