"""Source acquisition capabilities consumed by runtime supervisors."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class SourceAcquisitionResult:
    source_type: str
    fetched_count: int
    added_count: int
    downstream_synchronized: bool = False

    def __post_init__(self) -> None:
        if (
            not isinstance(self.source_type, str)
            or not self.source_type.strip()
            or self.source_type != self.source_type.strip()
        ):
            raise ValueError("source_type must be normalized non-empty text")
        if any(isinstance(value, bool) or not isinstance(value, int) for value in self.counts):
            raise ValueError("Source acquisition counts must be integers")
        if self.fetched_count < 0 or self.added_count < 0:
            raise ValueError("Source acquisition counts must be non-negative")
        if self.added_count > self.fetched_count:
            raise ValueError("added_count cannot exceed fetched_count")
        if not isinstance(self.downstream_synchronized, bool):
            raise ValueError("downstream_synchronized must be a boolean")

    @property
    def counts(self) -> tuple[int, int]:
        return self.fetched_count, self.added_count


class SourceAcquirer(Protocol):
    @property
    def source_type(self) -> str: ...

    def acquire(self) -> SourceAcquisitionResult: ...
