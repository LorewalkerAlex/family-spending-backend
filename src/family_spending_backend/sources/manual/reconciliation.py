"""Manual-source reconciliation candidate policy."""

from family_spending_backend.domain.reconciliation import (
    ReconciliationError,
    ReconciliationProposal,
    ReconciliationState,
    build_candidate,
    select_unambiguous_candidate,
    transaction_merchant_hint,
)
from family_spending_backend.domain.source import SourceRecord
from family_spending_backend.domain.transaction import SourceLink, SourceLinkRole

MANUAL_SOURCE_TYPE = "manual"


class ManualReconciliationPolicy:
    """Manual evidence matches conservatively and never displaces authority."""

    source_type = MANUAL_SOURCE_TYPE
    processing_order = 200

    def role_for_existing_link(
        self,
        record: SourceRecord,
        link: SourceLink,
        state: ReconciliationState,
    ) -> SourceLinkRole:
        del record, state
        return link.role

    def resolve_unlinked(
        self,
        record: SourceRecord,
        state: ReconciliationState,
    ) -> ReconciliationProposal:
        if record.source_type != self.source_type:
            raise ReconciliationError(
                f"Manual policy cannot process source type {record.source_type!r}"
            )

        record_merchant = state.hints.merchant_by_source_record_id.get(record.id)
        candidates = tuple(
            candidate
            for transaction in state.transactions
            if (
                candidate := build_candidate(
                    record,
                    transaction,
                    record_merchant=record_merchant,
                    transaction_merchant=transaction_merchant_hint(state, transaction.id),
                )
            )
            is not None
        )
        selected, ambiguous = select_unambiguous_candidate(candidates)
        if ambiguous:
            candidate_ids = sorted(candidate.transaction.id for candidate in candidates)
            raise ReconciliationError(
                f"Manual SourceRecord {record.id!r} matches multiple Transactions: "
                f"{candidate_ids!r}"
            )
        if selected is None:
            return ReconciliationProposal(None, "authoritative")
        return ReconciliationProposal(
            selected.transaction.id,
            "supporting",
            selected.evidence,
        )
