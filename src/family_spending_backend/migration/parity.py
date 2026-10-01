"""Build canonical state and compare identity/projection parity across data roots."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from family_spending_backend.application.models import (
    AutomationState,
    FinanceState,
    statement_dates_for_reconciled_evidence,
)
from family_spending_backend.domain.transaction import rebuild_transactions_from_source_links
from family_spending_backend.persistence.filesystem import (
    FilesystemCmbEmailEvidenceStore,
    FilesystemEnrichmentDecisionStore,
    FilesystemFeedbackStore,
    FilesystemIdentityStore,
    FilesystemLayout,
    FilesystemManualEvidenceStore,
    FilesystemMappingStore,
    FilesystemScheduleStore,
    read_manifest,
)
from family_spending_backend.persistence.filesystem.manifest import require_current_schema
from family_spending_backend.read_model import HouseholdReadModel
from family_spending_backend.sources.cmb_email.cache import CmbParserCache
from family_spending_backend.sources.cmb_email.source import CmbEmailSource
from family_spending_backend.sources.manual.source import ManualSource


class ParityMismatchError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ParityReport:
    source_record_count: int
    transaction_count: int
    mapping_description_count: int
    spending_total_minor: int
    financial_net_cash_flow_minor: int


def build_model(root: Path, *, parser_version: str) -> HouseholdReadModel:
    layout = FilesystemLayout(root.resolve())
    require_current_schema(read_manifest(layout))
    cache = CmbParserCache(parser_version)
    cmb_source = CmbEmailSource(FilesystemCmbEmailEvidenceStore(layout), cache)
    manual_source = ManualSource(FilesystemManualEvidenceStore(layout))
    records = (*cmb_source.load_records(), *manual_source.load_records())
    links = FilesystemIdentityStore(layout).load()
    transactions = rebuild_transactions_from_source_links(records, links)
    schedule_store = FilesystemScheduleStore(layout)
    statement_dates = statement_dates_for_reconciled_evidence(
        records,
        links,
        cmb_source.load_statement_dates_by_evidence(),
    )
    return HouseholdReadModel.from_states(
        FinanceState(
            records,
            transactions,
            links,
            mappings=FilesystemMappingStore(layout).load(),
            enrichment_decisions=FilesystemEnrichmentDecisionStore(layout).load(),
            statement_dates=statement_dates,
        ),
        feedback_items=FilesystemFeedbackStore(layout).load(),
        automation=AutomationState(
            schedule_store.load_rules(),
            schedule_store.load_execution(),
        ),
    )


def _all_summary(model: HouseholdReadModel, projection: str) -> Mapping[str, int]:
    value = getattr(model, projection).payload["summary"]
    assert isinstance(value, Mapping)
    summary = value["all_data"]
    assert isinstance(summary, Mapping)
    return summary


def verify_parity(left_root: Path, right_root: Path, *, parser_version: str) -> ParityReport:
    left = build_model(left_root, parser_version=parser_version)
    right = build_model(right_root, parser_version=parser_version)
    comparisons = {
        "SourceRecord identity/facts": left.source_records == right.source_records,
        "Transaction identity/facts": left.transactions == right.transactions,
        "SourceLink identity": left.source_links == right.source_links,
        "Mapping identity": left.mappings == right.mappings,
        "Enrichment decisions": left.enrichment_decisions == right.enrichment_decisions,
        "Scheduled state": (
            left.scheduled_rules,
            left.schedule_execution,
        )
        == (right.scheduled_rules, right.schedule_execution),
        "Feedback state": left.feedback_items == right.feedback_items,
        "Spending Projection": (
            left.spending_projection.payload == right.spending_projection.payload
        ),
        "Financial Projection": (
            left.financial_projection.payload == right.financial_projection.payload
        ),
    }
    failures = [name for name, matches in comparisons.items() if not matches]
    if failures:
        raise ParityMismatchError("Parity mismatch: " + ", ".join(failures))
    spending = _all_summary(left, "spending_projection")
    financial = _all_summary(left, "financial_projection")
    return ParityReport(
        source_record_count=len(left.source_records),
        transaction_count=len(left.transactions),
        mapping_description_count=len(left.mappings.description_to_merchant),
        spending_total_minor=spending["total_spending_minor"],
        financial_net_cash_flow_minor=financial["net_cash_flow_minor"],
    )
