"""Stable financial domain concepts and invariants."""

from family_spending_backend.domain.enrichment import (
    EnrichmentDecision,
    ResolvedEnrichment,
    resolve_enrichment,
    resolve_enrichments,
)
from family_spending_backend.domain.errors import DomainInvariantError
from family_spending_backend.domain.manual import (
    ManualEvidence,
    create_manual_evidence,
    manual_evidence_to_source_record,
)
from family_spending_backend.domain.mapping import MappingCatalog
from family_spending_backend.domain.reconciliation import (
    ReconciliationDecision,
    ReconciliationEngine,
    ReconciliationError,
    ReconciliationEvidence,
    ReconciliationHints,
    ReconciliationResult,
)
from family_spending_backend.domain.source import SourceIdentity, SourceRecord, TransactionType
from family_spending_backend.domain.transaction import (
    SourceLink,
    SourceLinkRole,
    Transaction,
    build_reconsidered_transaction_id,
    build_transaction_id,
    rebuild_transactions_from_source_links,
    transaction_from_source_record,
    validate_source_link_structure,
)

__all__ = [
    "DomainInvariantError",
    "EnrichmentDecision",
    "ManualEvidence",
    "MappingCatalog",
    "ReconciliationDecision",
    "ReconciliationEngine",
    "ReconciliationError",
    "ReconciliationEvidence",
    "ReconciliationHints",
    "ReconciliationResult",
    "ResolvedEnrichment",
    "SourceIdentity",
    "SourceLink",
    "SourceLinkRole",
    "SourceRecord",
    "Transaction",
    "TransactionType",
    "build_reconsidered_transaction_id",
    "build_transaction_id",
    "create_manual_evidence",
    "manual_evidence_to_source_record",
    "rebuild_transactions_from_source_links",
    "resolve_enrichment",
    "resolve_enrichments",
    "transaction_from_source_record",
    "validate_source_link_structure",
]
