"""Owned filesystem layout for durable and derived backend data."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class FilesystemLayout:
    """Paths owned by one backend data root."""

    root: Path

    @property
    def manifest(self) -> Path:
        return self.root / "manifest.json"

    @property
    def source_links(self) -> Path:
        return self.root / "state" / "identity" / "source-links.jsonl"

    @property
    def manual_evidence(self) -> Path:
        return self.root / "evidence" / "manual" / "records.jsonl"

    @property
    def cmb_email_evidence(self) -> Path:
        return self.root / "evidence" / "cmb-email"

    @property
    def merchant_mappings(self) -> Path:
        return self.root / "state" / "mappings" / "merchants.yaml"

    @property
    def category_mappings(self) -> Path:
        return self.root / "state" / "mappings" / "categories.yaml"

    @property
    def enrichment_decisions(self) -> Path:
        return self.root / "state" / "enrichment" / "decisions.jsonl"

    @property
    def feedback(self) -> Path:
        return self.root / "state" / "feedback" / "feedback.jsonl"

    @property
    def scheduled_rules(self) -> Path:
        return self.root / "state" / "schedules" / "rules.json"

    @property
    def schedule_execution(self) -> Path:
        return self.root / "state" / "schedules" / "execution.json"

    @property
    def required_directories(self) -> tuple[Path, ...]:
        return (
            self.root / "evidence" / "cmb-email",
            self.root / "evidence" / "manual",
            self.root / "state" / "identity",
            self.root / "state" / "enrichment",
            self.root / "state" / "mappings",
            self.root / "state" / "schedules",
            self.root / "state" / "feedback",
            self.root / "derived",
        )

    def initialize(self) -> None:
        """Initialize fresh storage or validate an existing canonical root."""

        from family_spending_backend.persistence.filesystem.manifest import (
            initialize_storage,
        )

        initialize_storage(self)
