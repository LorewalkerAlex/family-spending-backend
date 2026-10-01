"""Separate JSON persistence for Scheduled Rules and execution cursors."""

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from family_spending_backend.domain.errors import DomainInvariantError
from family_spending_backend.domain.scheduling import ScheduledRule, ScheduleExecutionState
from family_spending_backend.persistence.filesystem.atomic import atomic_write_text
from family_spending_backend.persistence.filesystem.layout import FilesystemLayout


class ScheduleStoreError(RuntimeError):
    pass


def _read_array(path: Path) -> list[object]:
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScheduleStoreError(f"Unable to read schedule state {path}: {exc}") from exc
    if not isinstance(raw, list):
        raise ScheduleStoreError(f"Schedule state {path} must contain a JSON array")
    return raw


def _rule(raw: object, *, path: Path, index: int) -> ScheduledRule:
    allowed = {
        "id",
        "enabled",
        "type",
        "amount",
        "currency",
        "description",
        "first_occurrence_date",
        "note",
    }
    if not isinstance(raw, dict) or set(raw) != allowed:
        fields = sorted(raw) if isinstance(raw, dict) else type(raw).__name__
        raise ScheduleStoreError(f"Invalid Scheduled Rule fields at index {index}: {fields!r}")
    try:
        if not isinstance(raw["amount"], str):
            raise TypeError("amount must be a decimal string")
        return ScheduledRule(
            id=raw["id"],
            enabled=raw["enabled"],
            transaction_type=raw["type"],
            amount=Decimal(raw["amount"]),
            description=raw["description"],
            first_occurrence_date=date.fromisoformat(raw["first_occurrence_date"]),
            currency=raw["currency"],
            note=raw["note"],
        )
    except (DomainInvariantError, InvalidOperation, TypeError, ValueError) as exc:
        raise ScheduleStoreError(
            f"Invalid Scheduled Rule in {path} at index {index}: {exc}"
        ) from exc


def _execution(raw: object, *, path: Path, index: int) -> ScheduleExecutionState:
    expected = {
        "rule_id",
        "last_processed_occurrence_date",
        "last_source_record_id",
        "last_transaction_id",
        "last_action",
    }
    if not isinstance(raw, dict) or set(raw) != expected:
        fields = sorted(raw) if isinstance(raw, dict) else type(raw).__name__
        raise ScheduleStoreError(f"Invalid Schedule execution fields at index {index}: {fields!r}")
    try:
        raw_date = raw["last_processed_occurrence_date"]
        processed = date.fromisoformat(raw_date) if raw_date is not None else None
        return ScheduleExecutionState(
            raw["rule_id"],
            processed,
            raw["last_source_record_id"],
            raw["last_transaction_id"],
            raw["last_action"],
        )
    except (DomainInvariantError, TypeError, ValueError) as exc:
        raise ScheduleStoreError(f"Invalid Schedule execution in {path}: {exc}") from exc


@dataclass(frozen=True, slots=True)
class FilesystemScheduleStore:
    layout: FilesystemLayout

    def load_rules(self) -> tuple[ScheduledRule, ...]:
        rules = tuple(
            _rule(item, path=self.layout.scheduled_rules, index=index)
            for index, item in enumerate(_read_array(self.layout.scheduled_rules))
        )
        if len({item.id for item in rules}) != len(rules):
            raise ScheduleStoreError("Scheduled Rules contain duplicate ids")
        return rules

    def replace_rules(self, rules: tuple[ScheduledRule, ...]) -> None:
        if len({item.id for item in rules}) != len(rules):
            raise ScheduleStoreError("Scheduled Rules contain duplicate ids")
        if not rules:
            self.layout.scheduled_rules.unlink(missing_ok=True)
            return
        payload = [
            {
                "id": rule.id,
                "enabled": rule.enabled,
                "type": rule.transaction_type,
                "amount": format(rule.amount, "f"),
                "currency": rule.currency,
                "description": rule.description,
                "first_occurrence_date": rule.first_occurrence_date.isoformat(),
                "note": rule.note,
            }
            for rule in rules
        ]
        atomic_write_text(
            self.layout.scheduled_rules, json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        )

    def load_execution(self) -> tuple[ScheduleExecutionState, ...]:
        states = tuple(
            _execution(item, path=self.layout.schedule_execution, index=index)
            for index, item in enumerate(_read_array(self.layout.schedule_execution))
        )
        if len({item.rule_id for item in states}) != len(states):
            raise ScheduleStoreError("Schedule execution contains duplicate rule ids")
        return states

    def replace_execution(self, states: tuple[ScheduleExecutionState, ...]) -> None:
        if len({item.rule_id for item in states}) != len(states):
            raise ScheduleStoreError("Schedule execution contains duplicate rule ids")
        if not states:
            self.layout.schedule_execution.unlink(missing_ok=True)
            return
        payload = [
            {
                "rule_id": state.rule_id,
                "last_processed_occurrence_date": (
                    state.last_processed_occurrence_date.isoformat()
                    if state.last_processed_occurrence_date
                    else None
                ),
                "last_source_record_id": state.last_source_record_id,
                "last_transaction_id": state.last_transaction_id,
                "last_action": state.last_action,
            }
            for state in states
        ]
        atomic_write_text(
            self.layout.schedule_execution, json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        )
