"""CMB-specific reconciliation authority and candidate policy."""

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

CMB_SOURCE_TYPE = "cmb_email"
MANUAL_SOURCE_TYPE = "manual"


class CmbEmailReconciliationPolicy:
    """CMB may take authority from one unambiguous Manual-backed Transaction."""

    source_type = CMB_SOURCE_TYPE
    processing_order = 100

    def role_for_existing_link(
        self,
        record: SourceRecord,
        link: SourceLink,
        state: ReconciliationState,
    ) -> SourceLinkRole:
        del record, link, state
        return "authoritative"

    def resolve_unlinked(
        self,
        record: SourceRecord,
        state: ReconciliationState,
    ) -> ReconciliationProposal:
        if record.source_type != self.source_type:
            raise ReconciliationError(
                f"CMB policy cannot process source type {record.source_type!r}"
            )

        record_merchant = state.hints.merchant_by_source_record_id.get(record.id)
        candidates = []
        for transaction in state.transactions:
            authority = state.authoritative_source_by_transaction_id.get(transaction.id)
            if authority is None or authority.source_type != MANUAL_SOURCE_TYPE:
                continue
            candidate = build_candidate(
                record,
                transaction,
                record_merchant=record_merchant,
                transaction_merchant=transaction_merchant_hint(state, transaction.id),
            )
            if candidate is not None:
                candidates.append(candidate)

        selected, ambiguous = select_unambiguous_candidate(tuple(candidates))
        if selected is None or ambiguous:
            return ReconciliationProposal(None, "authoritative")
        return ReconciliationProposal(
            selected.transaction.id,
            "authoritative",
            selected.evidence,
        )
