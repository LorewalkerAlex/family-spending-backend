"""Strict JSON Lines storage for Manual Evidence."""

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from family_spending_backend.domain.errors import DomainInvariantError
from family_spending_backend.domain.manual import ManualEvidence
from family_spending_backend.persistence.filesystem.atomic import atomic_write_text
from family_spending_backend.persistence.filesystem.layout import FilesystemLayout

_ALLOWED_FIELDS = {"id", "type", "date", "amount", "currency", "description"}


class ManualEvidenceStoreError(RuntimeError):
    """Manual Evidence cannot be loaded or persisted safely."""


def _parse_record(raw: object, *, path: Path, line_number: int) -> ManualEvidence:
    if not isinstance(raw, dict):
        raise ManualEvidenceStoreError(
            f"Invalid Manual evidence in {path} at line {line_number}: expected object"
        )
    unknown = sorted(set(raw) - _ALLOWED_FIELDS)
    missing = sorted(_ALLOWED_FIELDS - set(raw))
    if unknown or missing:
        raise ManualEvidenceStoreError(
            f"Invalid Manual evidence in {path} at line {line_number}: "
            f"unknown fields {unknown!r}, missing fields {missing!r}"
        )

    try:
        raw_date = raw["date"]
        raw_amount = raw["amount"]
        if not isinstance(raw_date, str) or not isinstance(raw_amount, str):
            raise TypeError("date and amount must be strings")
        return ManualEvidence(
            evidence_id=raw["id"],
            transaction_type=raw["type"],
            transaction_date=date.fromisoformat(raw_date),
            amount=Decimal(raw_amount),
            currency=raw["currency"],
            description=raw["description"],
        )
    except (DomainInvariantError, InvalidOperation, TypeError, ValueError) as error:
        raise ManualEvidenceStoreError(
            f"Invalid Manual evidence in {path} at line {line_number}: {error}"
        ) from error


def _encode_record(record: ManualEvidence) -> str:
    return json.dumps(
        {
            "id": record.evidence_id,
            "type": record.transaction_type,
            "date": record.transaction_date.isoformat(),
            "amount": format(record.amount, "f"),
            "currency": record.currency,
            "description": record.description,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


@dataclass(frozen=True, slots=True)
class FilesystemManualEvidenceStore:
    layout: FilesystemLayout

    @property
    def path(self) -> Path:
        return self.layout.manual_evidence

    def load_all(self) -> tuple[ManualEvidence, ...]:
        if not self.path.exists():
            return ()
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError as error:
            raise ManualEvidenceStoreError(
                f"Unable to read Manual evidence {self.path}: {error}"
            ) from error

        records: list[ManualEvidence] = []
        seen_ids: set[str] = set()
        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as error:
                raise ManualEvidenceStoreError(
                    f"Unable to parse Manual evidence {self.path} at line "
                    f"{line_number}: {error.msg}"
                ) from error
            record = _parse_record(raw, path=self.path, line_number=line_number)
            if record.evidence_id in seen_ids:
                raise ManualEvidenceStoreError(
                    f"Duplicate Manual evidence id {record.evidence_id!r} "
                    f"in {self.path} at line {line_number}"
                )
            seen_ids.add(record.evidence_id)
            records.append(record)
        return tuple(records)

    def replace_all(self, records: tuple[ManualEvidence, ...]) -> None:
        ids = [record.evidence_id for record in records]
        if len(ids) != len(set(ids)):
            raise ManualEvidenceStoreError("Manual evidence contains duplicate ids")
        if not records:
            self.path.unlink(missing_ok=True)
            return
        try:
            atomic_write_text(
                self.path,
                "".join(f"{_encode_record(record)}\n" for record in records),
            )
        except OSError as error:
            raise ManualEvidenceStoreError(
                f"Unable to persist Manual evidence {self.path}: {error}"
            ) from error
