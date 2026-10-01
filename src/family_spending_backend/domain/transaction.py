"""Stable transactions and their durable links to source facts."""

import hashlib
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

from family_spending_backend.domain.errors import DomainInvariantError
from family_spending_backend.domain.source import SourceRecord, TransactionType

TRANSACTION_ID_DIGEST_LENGTH = 24
SourceLinkRole = Literal["authoritative", "supporting"]


def _validate_identifier(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise DomainInvariantError(f"{label} must be a non-empty string")
    if value != value.strip():
        raise DomainInvariantError(f"{label} must not contain surrounding whitespace")
    if "\0" in value:
        raise DomainInvariantError(f"{label} must not contain NUL characters")


@dataclass(frozen=True, slots=True)
class Transaction:
    """System-level financial fact rebuilt from its authoritative SourceRecord."""

    id: str
    transaction_type: TransactionType
    transaction_date: date
    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        _validate_identifier(self.id, "transaction id")
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


@dataclass(frozen=True, slots=True)
class SourceLink:
    """Durable identity decision connecting one SourceRecord to one Transaction."""

    transaction_id: str
    source_record_id: str
    role: SourceLinkRole

    def __post_init__(self) -> None:
        _validate_identifier(self.transaction_id, "SourceLink transaction_id")
        _validate_identifier(self.source_record_id, "SourceLink source_record_id")
        if self.role not in ("authoritative", "supporting"):
            raise DomainInvariantError("SourceLink role must be authoritative or supporting")


def build_transaction_id(source_record: SourceRecord) -> str:
    """Derive initial Transaction identity from canonical SourceRecord identity."""

    payload = f"transaction\0{source_record.id}".encode()
    digest = hashlib.sha256(payload).hexdigest()[:TRANSACTION_ID_DIGEST_LENGTH]
    return f"txn_{digest}"


def build_reconsidered_transaction_id(
    source_record: SourceRecord,
    previous_transaction_id: str,
) -> str:
    """Derive split identity after an explicit source correction leaves its old Transaction."""

    _validate_identifier(previous_transaction_id, "previous_transaction_id")
    payload = (
        f"transaction-reconsideration\0{source_record.id}\0{previous_transaction_id}"
    ).encode()
    digest = hashlib.sha256(payload).hexdigest()[:TRANSACTION_ID_DIGEST_LENGTH]
    return f"txn_{digest}"


def transaction_from_source_record(
    source_record: SourceRecord,
    *,
    transaction_id: str | None = None,
) -> Transaction:
    """Rebuild core facts while preserving an existing durable Transaction identity."""

    resolved_id = build_transaction_id(source_record) if transaction_id is None else transaction_id
    return Transaction(
        id=resolved_id,
        transaction_type=source_record.transaction_type,
        transaction_date=source_record.transaction_date,
        amount=source_record.amount,
        currency=source_record.currency,
    )


def validate_source_link_structure(links: tuple[SourceLink, ...]) -> tuple[str, ...]:
    """Validate durable identity structure and return first-seen Transaction order."""

    seen_sources: set[str] = set()
    ordered_transaction_ids: list[str] = []
    seen_transactions: set[str] = set()
    authoritative_counts: dict[str, int] = {}

    for link in links:
        if link.source_record_id in seen_sources:
            raise DomainInvariantError(
                f"SourceRecord {link.source_record_id!r} is linked more than once"
            )
        seen_sources.add(link.source_record_id)

        if link.transaction_id not in seen_transactions:
            seen_transactions.add(link.transaction_id)
            ordered_transaction_ids.append(link.transaction_id)

        if link.role == "authoritative":
            count = authoritative_counts.get(link.transaction_id, 0) + 1
            authoritative_counts[link.transaction_id] = count
            if count > 1:
                raise DomainInvariantError(
                    f"Transaction {link.transaction_id!r} has multiple authoritative SourceLinks"
                )

    missing_authority = [
        transaction_id
        for transaction_id in ordered_transaction_ids
        if authoritative_counts.get(transaction_id, 0) == 0
    ]
    if missing_authority:
        raise DomainInvariantError(
            f"Transactions have no authoritative SourceLink: {missing_authority!r}"
        )

    return tuple(ordered_transaction_ids)


def rebuild_transactions_from_source_links(
    source_records: tuple[SourceRecord, ...],
    links: tuple[SourceLink, ...],
) -> tuple[Transaction, ...]:
    """Rebuild Transactions from durable identity and authoritative source facts."""

    records_by_id: dict[str, SourceRecord] = {}
    for record in source_records:
        if record.id in records_by_id:
            raise DomainInvariantError(f"Duplicate SourceRecord id {record.id!r}")
        records_by_id[record.id] = record

    ordered_transaction_ids = validate_source_link_structure(links)
    authoritative_by_transaction: dict[str, SourceLink] = {}
    for link in links:
        if link.source_record_id not in records_by_id:
            raise DomainInvariantError(
                f"SourceLink references missing SourceRecord {link.source_record_id!r}"
            )
        if link.role == "authoritative":
            authoritative_by_transaction[link.transaction_id] = link

    return tuple(
        transaction_from_source_record(
            records_by_id[authoritative_by_transaction[transaction_id].source_record_id],
            transaction_id=transaction_id,
        )
        for transaction_id in ordered_transaction_ids
    )
