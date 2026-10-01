"""Immutable content-addressed CMB email evidence."""

import hashlib
from dataclasses import dataclass


class CmbEmailEvidenceError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CmbEmailEvidence:
    raw_bytes: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.raw_bytes, bytes) or not self.raw_bytes:
            raise CmbEmailEvidenceError("CMB email evidence must contain non-empty raw bytes")

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.raw_bytes).hexdigest()

    @property
    def identity(self) -> str:
        return f"sha256:{self.digest}"

    @property
    def filename(self) -> str:
        return f"{self.digest}.eml"
