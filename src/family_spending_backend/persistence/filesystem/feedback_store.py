"""Strict JSONL persistence for product Feedback."""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from family_spending_backend.domain.errors import DomainInvariantError
from family_spending_backend.domain.feedback import FeedbackContext, FeedbackItem
from family_spending_backend.persistence.filesystem.atomic import atomic_write_text
from family_spending_backend.persistence.filesystem.layout import FilesystemLayout


class FeedbackStoreError(RuntimeError):
    pass


def _parse(raw: object, *, path: Path, line: int) -> FeedbackItem:
    if not isinstance(raw, dict) or set(raw) != {
        "id",
        "created_at",
        "status",
        "content",
        "context",
    }:
        fields = sorted(raw) if isinstance(raw, dict) else type(raw).__name__
        raise FeedbackStoreError(f"Invalid Feedback fields at line {line}: {fields!r}")
    context = raw["context"]
    allowed_context = {"runtime", "page", "workspace", "entity_type", "entity_id"}
    if not isinstance(context, dict) or not set(context) <= allowed_context:
        raise FeedbackStoreError(f"Invalid Feedback context fields at line {line}")
    try:
        timestamp = raw["created_at"]
        if not isinstance(timestamp, str):
            raise TypeError("created_at must be text")
        created_at = datetime.fromisoformat(
            timestamp[:-1] + "+00:00" if timestamp.endswith("Z") else timestamp
        )
        return FeedbackItem(
            id=raw["id"],
            created_at=created_at,
            status=raw["status"],
            content=raw["content"],
            context=FeedbackContext(**context),
        )
    except (DomainInvariantError, TypeError, ValueError) as exc:
        raise FeedbackStoreError(
            f"Invalid Feedback record in {path} at line {line}: {exc}"
        ) from exc


def _encode(item: FeedbackItem) -> str:
    context = {
        key: value
        for key, value in {
            "runtime": item.context.runtime,
            "page": item.context.page,
            "workspace": item.context.workspace,
            "entity_type": item.context.entity_type,
            "entity_id": item.context.entity_id,
        }.items()
        if value is not None
    }
    return json.dumps(
        {
            "id": item.id,
            "created_at": item.created_at.isoformat(timespec="microseconds").replace("+00:00", "Z"),
            "status": item.status,
            "content": item.content,
            "context": context,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


@dataclass(frozen=True, slots=True)
class FilesystemFeedbackStore:
    layout: FilesystemLayout

    @property
    def path(self) -> Path:
        return self.layout.feedback

    def load(self) -> tuple[FeedbackItem, ...]:
        if not self.path.exists():
            return ()
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise FeedbackStoreError(f"Unable to read Feedback {self.path}: {exc}") from exc
        items: list[FeedbackItem] = []
        seen: set[str] = set()
        for number, line in enumerate(lines, 1):
            if not line.strip():
                raise FeedbackStoreError(f"Blank Feedback line at line {number}")
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise FeedbackStoreError(f"Invalid Feedback JSON at line {number}") from exc
            item = _parse(raw, path=self.path, line=number)
            if item.id in seen:
                raise FeedbackStoreError(f"Duplicate Feedback id {item.id!r}")
            seen.add(item.id)
            items.append(item)
        return tuple(items)

    def replace(self, items: tuple[FeedbackItem, ...]) -> None:
        ids = [item.id for item in items]
        if len(ids) != len(set(ids)):
            raise FeedbackStoreError("Feedback items contain duplicate ids")
        if not items:
            self.path.unlink(missing_ok=True)
            return
        try:
            atomic_write_text(self.path, "".join(f"{_encode(item)}\n" for item in items))
        except OSError as exc:
            raise FeedbackStoreError(f"Unable to persist Feedback {self.path}: {exc}") from exc
