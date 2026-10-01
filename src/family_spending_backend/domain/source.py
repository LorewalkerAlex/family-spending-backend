"""Normalized source facts and evidence-anchored identity."""

import hashlib
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from family_spending_backend.domain.errors import DomainInvariantError

TransactionType = Literal["income", "expense"]
SOURCE_ID_DIGEST_LENGTH = 24


def _validate_identity_component(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise DomainInvariantError(f"{label} must be a non-empty string")
    if value != value.strip():
        raise DomainInvariantError(f"{label} must not contain surrounding whitespace")
    if "\0" in value:
        raise DomainInvariantError(f"{label} must not contain NUL characters")


@dataclass(frozen=True, slots=True)
class SourceIdentity:
    """Identity anchored to evidence rather than parser output order."""

    source_type: str
    evidence_identity: str
    record_locator: str

    def __post_init__(self) -> None:
        _validate_identity_component(self.source_type, "source_type")
        _validate_identity_component(self.evidence_identity, "evidence_identity")
        _validate_identity_component(self.record_locator, "record_locator")

    @property
    def id(self) -> str:
        payload = (
            f"source-record\0{self.source_type}\0{self.evidence_identity}\0{self.record_locator}"
        ).encode()
        digest = hashlib.sha256(payload).hexdigest()[:SOURCE_ID_DIGEST_LENGTH]
        return f"src_{digest}"


@dataclass(frozen=True, slots=True)
class SourceRecord:
    """Normalized financial fact located within one Source Evidence item."""

    identity: SourceIdentity
    transaction_type: TransactionType
    transaction_date: date
    amount: Decimal
    currency: str
    description: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.identity, SourceIdentity):
            raise DomainInvariantError("identity must be a SourceIdentity")
        if self.transaction_type not in ("income", "expense"):
            raise DomainInvariantError("transaction_type must be 'income' or 'expense'")
        if not isinstance(self.transaction_date, date):
            raise DomainInvariantError("transaction_date must be a date")
        if not isinstance(self.amount, Decimal) or not self.amount.is_finite():
            raise DomainInvariantError("amount must be a finite Decimal")
        if not isinstance(self.currency, str) or not self.currency.strip():
            raise DomainInvariantError("currency must be a non-empty string")
        if self.currency != self.currency.strip().upper():
            raise DomainInvariantError("currency must be normalized uppercase text")
        if self.description is not None and not isinstance(self.description, str):
            raise DomainInvariantError("description must be a string or None")

    @property
    def id(self) -> str:
        return self.identity.id

    @property
    def source_type(self) -> str:
        return self.identity.source_type
