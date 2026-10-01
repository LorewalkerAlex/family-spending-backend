"""Complete rebuild-based integrity check for one canonical data root."""

from dataclasses import dataclass
from pathlib import Path

from family_spending_backend.migration.parity import build_model


@dataclass(frozen=True, slots=True)
class IntegrityReport:
    source_records: int
    transactions: int
    enrichments: int
    feedback: int
    scheduled_rules: int


def check_integrity(root: Path, *, parser_version: str) -> IntegrityReport:
    model = build_model(root, parser_version=parser_version)
    rule_ids = {rule.id for rule in model.scheduled_rules}
    unknown_execution = sorted(
        state.rule_id for state in model.schedule_execution if state.rule_id not in rule_ids
    )
    if unknown_execution:
        raise RuntimeError(f"Schedule execution references missing rules: {unknown_execution!r}")
    return IntegrityReport(
        source_records=len(model.source_records),
        transactions=len(model.transactions),
        enrichments=len(model.resolved_enrichments),
        feedback=len(model.feedback_items),
        scheduled_rules=len(model.scheduled_rules),
    )
