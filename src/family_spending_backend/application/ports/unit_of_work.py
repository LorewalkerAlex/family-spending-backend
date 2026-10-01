"""Application commit-boundary contract."""

from types import TracebackType
from typing import Protocol


class UnitOfWork(Protocol):
    def __enter__(self) -> UnitOfWork: ...

    def commit(self) -> None: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...
