"""Cross-platform advisory lock enforcing one writer process per data root."""

import os
from pathlib import Path
from typing import BinaryIO


class InstanceLockError(RuntimeError):
    pass


class InstanceLock:
    def __init__(self, data_root: Path) -> None:
        self.path = data_root / ".backend.lock"
        self._handle: BinaryIO | None = None

    def acquire(self) -> None:
        if self._handle is not None:
            raise InstanceLockError("Backend instance lock is already acquired")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        # ``a+b`` forces writes to EOF on Windows and can leave the CRT byte
        # range cursor somewhere other than the position reported by the
        # buffered Python object.  An unbuffered read/write handle keeps the
        # byte-range lock and unlock anchored to the same offset.
        handle = self.path.open("r+b", buffering=0)
        try:
            handle.seek(0)
            if handle.read(1) == b"":
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Byte zero is the permanent lock region.  Do not truncate it while
            # it is locked: on Windows that invalidates the region for a later
            # ``LK_UNLCK`` call.  The remaining fixed-width field is only a
            # human-readable owner hint and is never used for lock ownership.
            handle.seek(1)
            handle.write(str(os.getpid()).encode().ljust(31, b" ")[:31])
            handle.flush()
        except (OSError, BlockingIOError) as exc:
            handle.close()
            raise InstanceLockError(
                f"Another Backend instance already owns data root {self.path.parent}"
            ) from exc
        self._handle = handle

    def release(self) -> None:
        handle = self._handle
        if handle is None:
            return
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
            self._handle = None

    def __enter__(self) -> InstanceLock:
        self.acquire()
        return self

    def __exit__(self, *_: object) -> None:
        self.release()
