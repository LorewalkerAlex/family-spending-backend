"""Sparse JSONL persistence for durable Enrichment decisions."""

import json
from dataclasses import dataclass
from pathlib import Path

from family_spending_backend.domain.enrichment import EnrichmentDecision
from family_spending_backend.domain.errors import DomainInvariantError
from family_spending_backend.persistence.filesystem.atomic import atomic_write_text
from family_spending_backend.persistence.filesystem.layout import FilesystemLayout


class EnrichmentDecisionStoreError(RuntimeError):
    """Sparse Enrichment state is malformed or cannot be persisted."""


_ALLOWED_FIELDS = {"transaction_id", "merchant_override", "category_override", "note"}


def _parse_decision(raw: object, *, path: Path, line_number: int) -> EnrichmentDecision:
    if not isinstance(raw, dict):
        raise EnrichmentDecisionStoreError(
            f"Invalid EnrichmentDecision in {path} at line {line_number}: expected object"
        )
    fields = set(raw)
    if "transaction_id" not in fields or not fields <= _ALLOWED_FIELDS:
        raise EnrichmentDecisionStoreError(
            f"Invalid EnrichmentDecision fields in {path} at line {line_number}: {sorted(fields)!r}"
        )
    transaction_id = raw["transaction_id"]
    if not isinstance(transaction_id, str):
        raise EnrichmentDecisionStoreError(f"Invalid transaction_id at line {line_number}")
    values = {field: raw.get(field) for field in _ALLOWED_FIELDS - {"transaction_id"}}
    if any(value is not None and not isinstance(value, str) for value in values.values()):
        raise EnrichmentDecisionStoreError(f"Invalid decision value at line {line_number}")
    try:
        return EnrichmentDecision(transaction_id=transaction_id, **values)
    except DomainInvariantError as exc:
        raise EnrichmentDecisionStoreError(
            f"Invalid EnrichmentDecision in {path} at line {line_number}: {exc}"
        ) from exc


def _encode(decision: EnrichmentDecision) -> str:
    payload = {"transaction_id": decision.transaction_id}
    for field in ("merchant_override", "category_override", "note"):
        value = getattr(decision, field)
        if value is not None:
            payload[field] = value
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class FilesystemEnrichmentDecisionStore:
    layout: FilesystemLayout

    @property
    def path(self) -> Path:
        return self.layout.enrichment_decisions

    def load(self) -> tuple[EnrichmentDecision, ...]:
        if not self.path.exists():
            return ()
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise EnrichmentDecisionStoreError(f"Unable to read {self.path}: {exc}") from exc
        decisions: list[EnrichmentDecision] = []
        seen: set[str] = set()
        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise EnrichmentDecisionStoreError(
                    f"Unable to parse {self.path} at line {line_number}: {exc.msg}"
                ) from exc
            decision = _parse_decision(raw, path=self.path, line_number=line_number)
            if decision.transaction_id in seen:
                raise EnrichmentDecisionStoreError(
                    f"Duplicate EnrichmentDecision transaction_id {decision.transaction_id!r}"
                )
            seen.add(decision.transaction_id)
            decisions.append(decision)
        return tuple(decisions)

    def replace(self, decisions: tuple[EnrichmentDecision, ...]) -> None:
        ids = [decision.transaction_id for decision in decisions]
        if len(ids) != len(set(ids)):
            raise EnrichmentDecisionStoreError("Duplicate EnrichmentDecision transaction_id")
        if not decisions:
            self.path.unlink(missing_ok=True)
            return
        try:
            atomic_write_text(self.path, "".join(f"{_encode(item)}\n" for item in decisions))
        except OSError as exc:
            raise EnrichmentDecisionStoreError(f"Unable to persist {self.path}: {exc}") from exc
