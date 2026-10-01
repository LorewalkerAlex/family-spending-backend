"""JSON Lines persistence for durable SourceLink identity history."""

import json
from dataclasses import dataclass
from pathlib import Path

from family_spending_backend.domain.errors import DomainInvariantError
from family_spending_backend.domain.transaction import (
    SourceLink,
    validate_source_link_structure,
)
from family_spending_backend.persistence.filesystem.atomic import atomic_write_text
from family_spending_backend.persistence.filesystem.layout import FilesystemLayout


class IdentityStoreError(RuntimeError):
    """Durable SourceLink state is malformed or cannot be persisted."""


@dataclass(frozen=True, slots=True)
class FilesystemIdentityStore:
    layout: FilesystemLayout

    @property
    def path(self) -> Path:
        return self.layout.source_links

    def load(self) -> tuple[SourceLink, ...]:
        if not self.path.exists():
            return ()
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError as error:
            raise IdentityStoreError(
                f"Unable to read identity state {self.path}: {error}"
            ) from error

        links: list[SourceLink] = []
        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as error:
                raise IdentityStoreError(
                    f"Unable to parse identity state {self.path} at line {line_number}: {error.msg}"
                ) from error
            if not isinstance(raw, dict) or set(raw) != {
                "transaction_id",
                "source_record_id",
                "role",
            }:
                raise IdentityStoreError(
                    f"Invalid SourceLink in {self.path} at line {line_number}: {raw!r}"
                )
            try:
                links.append(
                    SourceLink(
                        transaction_id=raw["transaction_id"],
                        source_record_id=raw["source_record_id"],
                        role=raw["role"],
                    )
                )
            except (DomainInvariantError, TypeError, AttributeError) as error:
                raise IdentityStoreError(
                    f"Invalid SourceLink in {self.path} at line {line_number}: {error}"
                ) from error

        result = tuple(links)
        try:
            validate_source_link_structure(result)
        except DomainInvariantError as error:
            raise IdentityStoreError(f"Invalid identity state {self.path}: {error}") from error
        return result

    def replace(self, links: tuple[SourceLink, ...]) -> None:
        try:
            validate_source_link_structure(links)
        except DomainInvariantError as error:
            raise IdentityStoreError(f"Invalid identity state: {error}") from error

        if not links:
            try:
                self.path.unlink(missing_ok=True)
            except OSError as error:
                raise IdentityStoreError(
                    f"Unable to remove empty identity state {self.path}: {error}"
                ) from error
            return

        text = "".join(
            json.dumps(
                {
                    "transaction_id": link.transaction_id,
                    "source_record_id": link.source_record_id,
                    "role": link.role,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n"
            for link in links
        )
        try:
            atomic_write_text(self.path, text)
        except OSError as error:
            raise IdentityStoreError(
                f"Unable to persist identity state {self.path}: {error}"
            ) from error
