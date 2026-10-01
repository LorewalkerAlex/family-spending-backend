"""Generic reconciliation engine for durable SourceLink identity decisions."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, Protocol

from family_spending_backend.domain.errors import DomainInvariantError
from family_spending_backend.domain.source import SourceRecord
from family_spending_backend.domain.transaction import (
    SourceLink,
    SourceLinkRole,
    Transaction,
    build_reconsidered_transaction_id,
    build_transaction_id,
    rebuild_transactions_from_source_links,
    validate_source_link_structure,
)

ReconciliationAction = Literal["created", "reused", "matched"]
CROSS_SOURCE_MATCH_WINDOW_DAYS = 3
_EMPTY_MAPPING: Mapping[str, str | None] = MappingProxyType({})


class ReconciliationError(RuntimeError):
    """Source facts cannot be reconciled without violating identity history."""


@dataclass(frozen=True, slots=True)
class ReconciliationEvidence:
    """Independent evidence signals retained for inspection."""

    source_identity_match: bool = False
    amount_match: bool | None = None
    date_distance_days: int | None = None
    merchant_match: bool | None = None


@dataclass(frozen=True, slots=True)
class ReconciliationDecision:
    """Explanation of one SourceRecord identity assignment."""

    source_record_id: str
    transaction_id: str
    action: ReconciliationAction
    evidence: ReconciliationEvidence


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    """Derived Transactions and their durable identity decisions."""

    transactions: tuple[Transaction, ...]
    source_links: tuple[SourceLink, ...]
    decisions: tuple[ReconciliationDecision, ...]


@dataclass(frozen=True, slots=True)
class ReconciliationHints:
    """Optional reviewed evidence that informs but never owns identity."""

    merchant_by_transaction_id: Mapping[str, str | None] = _EMPTY_MAPPING
    merchant_by_source_record_id: Mapping[str, str | None] = _EMPTY_MAPPING


@dataclass(frozen=True, slots=True)
class ReconciliationState:
    """Read-only current state exposed to source-specific policy."""

    source_records_by_id: Mapping[str, SourceRecord]
    transactions: tuple[Transaction, ...]
    source_links: tuple[SourceLink, ...]
    authoritative_source_by_transaction_id: Mapping[str, SourceRecord]
    hints: ReconciliationHints


@dataclass(frozen=True, slots=True)
class ReconciliationProposal:
    """A source policy proposal for a SourceRecord with no SourceLink."""

    transaction_id: str | None
    role: SourceLinkRole
    evidence: ReconciliationEvidence = field(default_factory=ReconciliationEvidence)


class ReconciliationPolicy(Protocol):
    """Source-specific authority and candidate policy."""

    source_type: str
    processing_order: int

    def role_for_existing_link(
        self,
        record: SourceRecord,
        link: SourceLink,
        state: ReconciliationState,
    ) -> SourceLinkRole: ...

    def resolve_unlinked(
        self,
        record: SourceRecord,
        state: ReconciliationState,
    ) -> ReconciliationProposal: ...


def transaction_merchant_hint(
    state: ReconciliationState,
    transaction_id: str,
) -> str | None:
    merchant = state.hints.merchant_by_transaction_id.get(transaction_id)
    if merchant is not None:
        return merchant
    source = state.authoritative_source_by_transaction_id.get(transaction_id)
    if source is None:
        return None
    return state.hints.merchant_by_source_record_id.get(source.id)


@dataclass(frozen=True, slots=True)
class Candidate:
    transaction: Transaction
    evidence: ReconciliationEvidence


def build_candidate(
    record: SourceRecord,
    transaction: Transaction,
    *,
    record_merchant: str | None,
    transaction_merchant: str | None,
) -> Candidate | None:
    """Build a conservative cross-source candidate from independent evidence."""

    if record.transaction_type != transaction.transaction_type:
        return None
    if record.currency != transaction.currency:
        return None
    if record.amount != transaction.amount:
        return None

    date_distance_days = abs((record.transaction_date - transaction.transaction_date).days)
    if date_distance_days > CROSS_SOURCE_MATCH_WINDOW_DAYS:
        return None

    merchant_match: bool | None = None
    if record_merchant is not None and transaction_merchant is not None:
        merchant_match = record_merchant == transaction_merchant
        if not merchant_match:
            return None

    return Candidate(
        transaction=transaction,
        evidence=ReconciliationEvidence(
            amount_match=True,
            date_distance_days=date_distance_days,
            merchant_match=merchant_match,
        ),
    )


def select_unambiguous_candidate(
    candidates: tuple[Candidate, ...],
) -> tuple[Candidate | None, bool]:
    """Select only when current evidence distinguishes one candidate."""

    if not candidates:
        return None, False
    if len(candidates) == 1:
        return candidates[0], False

    merchant_matches = tuple(
        candidate for candidate in candidates if candidate.evidence.merchant_match is True
    )
    if len(merchant_matches) == 1:
        return merchant_matches[0], False
    return None, True


def _state(
    records: tuple[SourceRecord, ...],
    links: tuple[SourceLink, ...],
    hints: ReconciliationHints,
) -> ReconciliationState:
    try:
        transactions = rebuild_transactions_from_source_links(records, links)
    except DomainInvariantError as error:
        raise ReconciliationError(str(error)) from error

    records_by_id = MappingProxyType({record.id: record for record in records})
    authoritative = {
        link.transaction_id: records_by_id[link.source_record_id]
        for link in links
        if link.role == "authoritative"
    }
    return ReconciliationState(
        source_records_by_id=records_by_id,
        transactions=transactions,
        source_links=links,
        authoritative_source_by_transaction_id=MappingProxyType(authoritative),
        hints=hints,
    )


def _replace_link_role(
    links: list[SourceLink],
    source_record_id: str,
    role: SourceLinkRole,
) -> None:
    for index, link in enumerate(links):
        if link.source_record_id == source_record_id:
            links[index] = SourceLink(link.transaction_id, link.source_record_id, role)
            return
    raise ReconciliationError(f"Missing SourceLink for {source_record_id!r}")


def _set_authoritative_source(
    links: list[SourceLink],
    transaction_id: str,
    source_record_id: str,
) -> None:
    found_target = False
    for index, link in enumerate(links):
        if link.transaction_id != transaction_id:
            continue
        if link.source_record_id == source_record_id:
            links[index] = SourceLink(transaction_id, source_record_id, "authoritative")
            found_target = True
        elif link.role == "authoritative":
            links[index] = SourceLink(
                link.transaction_id,
                link.source_record_id,
                "supporting",
            )
    if not found_target:
        links.append(SourceLink(transaction_id, source_record_id, "authoritative"))


class ReconciliationEngine:
    """Reuse durable identity before applying source-specific matching policy."""

    def __init__(self, policies: tuple[ReconciliationPolicy, ...]) -> None:
        policies_by_type: dict[str, ReconciliationPolicy] = {}
        for policy in policies:
            if not isinstance(policy.source_type, str) or not policy.source_type.strip():
                raise ReconciliationError("Reconciliation policy source_type must be non-empty")
            if policy.source_type in policies_by_type:
                raise ReconciliationError(
                    f"Duplicate Reconciliation policy for {policy.source_type!r}"
                )
            policies_by_type[policy.source_type] = policy
        self._policies_by_type = MappingProxyType(policies_by_type)

    def _records_by_id(
        self,
        records: tuple[SourceRecord, ...],
    ) -> dict[str, SourceRecord]:
        records_by_id: dict[str, SourceRecord] = {}
        for record in records:
            if record.id in records_by_id:
                raise ReconciliationError(f"Duplicate SourceRecord id {record.id!r}")
            if record.source_type not in self._policies_by_type:
                raise ReconciliationError(
                    f"No Reconciliation policy registered for source type {record.source_type!r}"
                )
            records_by_id[record.id] = record
        return records_by_id

    def recover_authority_after_source_removal(
        self,
        records: tuple[SourceRecord, ...],
        links: tuple[SourceLink, ...],
    ) -> tuple[SourceLink, ...]:
        """Promote surviving evidence without changing Transaction identity."""

        if not links:
            return ()
        records_by_id = self._records_by_id(records)
        seen_sources: set[str] = set()
        grouped_indices: dict[str, list[int]] = {}
        for index, link in enumerate(links):
            if link.source_record_id in seen_sources:
                raise ReconciliationError(
                    f"SourceRecord {link.source_record_id!r} is linked more than once"
                )
            seen_sources.add(link.source_record_id)
            if link.source_record_id not in records_by_id:
                raise ReconciliationError(
                    f"SourceLink references missing SourceRecord {link.source_record_id!r}"
                )
            grouped_indices.setdefault(link.transaction_id, []).append(index)

        repaired = list(links)
        for transaction_id, indices in grouped_indices.items():
            authority_indices = [
                index for index in indices if repaired[index].role == "authoritative"
            ]
            if len(authority_indices) > 1:
                raise ReconciliationError(
                    f"Transaction {transaction_id!r} has multiple authoritative SourceLinks"
                )
            if authority_indices:
                continue
            promoted_index = min(
                indices,
                key=lambda index: (
                    self._policies_by_type[
                        records_by_id[repaired[index].source_record_id].source_type
                    ].processing_order,
                    index,
                ),
            )
            promoted = repaired[promoted_index]
            repaired[promoted_index] = SourceLink(
                promoted.transaction_id,
                promoted.source_record_id,
                "authoritative",
            )

        repaired_links = tuple(repaired)
        try:
            validate_source_link_structure(repaired_links)
        except DomainInvariantError as error:
            raise ReconciliationError(str(error)) from error
        return repaired_links

    def _reconcile_records(
        self,
        records: tuple[SourceRecord, ...],
        *,
        existing_links: tuple[SourceLink, ...],
        hints: ReconciliationHints,
        creation_overrides: Mapping[str, tuple[str, ReconciliationAction]] | None = None,
    ) -> ReconciliationResult:
        records_by_id = self._records_by_id(records)
        try:
            validate_source_link_structure(existing_links)
        except DomainInvariantError as error:
            raise ReconciliationError(str(error)) from error

        link_by_source: dict[str, SourceLink] = {}
        for link in existing_links:
            if link.source_record_id not in records_by_id:
                raise ReconciliationError(
                    f"Durable SourceLink references missing SourceRecord {link.source_record_id!r}"
                )
            link_by_source[link.source_record_id] = link

        overrides = creation_overrides or {}
        unknown_override_ids = sorted(set(overrides) - set(records_by_id))
        if unknown_override_ids:
            raise ReconciliationError(
                "Creation identity overrides reference missing SourceRecords: "
                f"{unknown_override_ids!r}"
            )

        links = list(existing_links)
        decisions: list[ReconciliationDecision] = []
        ordered_records = sorted(
            enumerate(records),
            key=lambda item: (
                self._policies_by_type[item[1].source_type].processing_order,
                item[1].source_type,
                item[0],
            ),
        )

        for _, record in ordered_records:
            policy = self._policies_by_type[record.source_type]
            current_state = _state(records, tuple(links), hints)
            existing_link = link_by_source.get(record.id)

            if existing_link is not None:
                desired_role = policy.role_for_existing_link(
                    record,
                    existing_link,
                    current_state,
                )
                if desired_role == "authoritative":
                    _set_authoritative_source(links, existing_link.transaction_id, record.id)
                elif desired_role != existing_link.role:
                    _replace_link_role(links, record.id, desired_role)
                link_by_source = {link.source_record_id: link for link in links}
                decisions.append(
                    ReconciliationDecision(
                        source_record_id=record.id,
                        transaction_id=existing_link.transaction_id,
                        action="reused",
                        evidence=ReconciliationEvidence(source_identity_match=True),
                    )
                )
                continue

            proposal = policy.resolve_unlinked(record, current_state)
            transaction_id = proposal.transaction_id
            if transaction_id is None:
                if proposal.role != "authoritative":
                    raise ReconciliationError(
                        "A newly created Transaction must start with an authoritative SourceLink"
                    )
                override = overrides.get(record.id)
                if override is None:
                    transaction_id = build_transaction_id(record)
                    action: ReconciliationAction = "created"
                    evidence = proposal.evidence
                else:
                    transaction_id, action = override
                    evidence = (
                        ReconciliationEvidence(source_identity_match=True)
                        if action == "reused"
                        else proposal.evidence
                    )
                if any(link.transaction_id == transaction_id for link in links):
                    raise ReconciliationError(
                        f"Generated Transaction id {transaction_id!r} already exists"
                    )
                link = SourceLink(transaction_id, record.id, "authoritative")
                links.append(link)
                link_by_source[record.id] = link
                decisions.append(
                    ReconciliationDecision(
                        source_record_id=record.id,
                        transaction_id=transaction_id,
                        action=action,
                        evidence=evidence,
                    )
                )
                continue

            transaction_ids = {item.id for item in current_state.transactions}
            if transaction_id not in transaction_ids:
                raise ReconciliationError(f"Policy selected missing Transaction {transaction_id!r}")

            link = SourceLink(transaction_id, record.id, proposal.role)
            links.append(link)
            if proposal.role == "authoritative":
                _set_authoritative_source(links, transaction_id, record.id)
            link_by_source = {item.source_record_id: item for item in links}
            decisions.append(
                ReconciliationDecision(
                    source_record_id=record.id,
                    transaction_id=transaction_id,
                    action="matched",
                    evidence=proposal.evidence,
                )
            )

        final_links = tuple(links)
        try:
            transactions = rebuild_transactions_from_source_links(records, final_links)
        except DomainInvariantError as error:
            raise ReconciliationError(str(error)) from error
        return ReconciliationResult(
            transactions=transactions,
            source_links=final_links,
            decisions=tuple(decisions),
        )

    def reconcile(
        self,
        records: tuple[SourceRecord, ...],
        *,
        existing_links: tuple[SourceLink, ...] = (),
        hints: ReconciliationHints | None = None,
    ) -> ReconciliationResult:
        """Reuse durable SourceLinks and reconcile only previously unlinked records."""

        return self._reconcile_records(
            records,
            existing_links=existing_links,
            hints=hints or ReconciliationHints(),
        )

    def reconcile_reconsidered_source(
        self,
        records: tuple[SourceRecord, ...],
        *,
        existing_links: tuple[SourceLink, ...],
        source_record_id: str,
        hints: ReconciliationHints | None = None,
    ) -> ReconciliationResult:
        """Re-evaluate one corrected source while preserving unrelated identity history."""

        records_by_id = self._records_by_id(records)
        try:
            validate_source_link_structure(existing_links)
        except DomainInvariantError as error:
            raise ReconciliationError(str(error)) from error
        for link in existing_links:
            if link.source_record_id not in records_by_id:
                raise ReconciliationError(
                    f"Durable SourceLink references missing SourceRecord {link.source_record_id!r}"
                )

        source_record = records_by_id.get(source_record_id)
        if source_record is None:
            raise ReconciliationError(
                f"Reconsidered SourceRecord {source_record_id!r} does not exist"
            )
        old_link = next(
            (link for link in existing_links if link.source_record_id == source_record_id),
            None,
        )
        if old_link is None:
            raise ReconciliationError(
                f"Reconsidered SourceRecord {source_record_id!r} has no durable SourceLink"
            )

        retained_links = tuple(
            link for link in existing_links if link.source_record_id != source_record_id
        )
        old_transaction_survives = any(
            link.transaction_id == old_link.transaction_id for link in retained_links
        )
        retained_links = self.recover_authority_after_source_removal(records, retained_links)
        if old_transaction_survives:
            fallback_transaction_id = build_reconsidered_transaction_id(
                source_record,
                old_link.transaction_id,
            )
            fallback_action: ReconciliationAction = "created"
        else:
            fallback_transaction_id = old_link.transaction_id
            fallback_action = "reused"

        return self._reconcile_records(
            records,
            existing_links=retained_links,
            hints=hints or ReconciliationHints(),
            creation_overrides={source_record_id: (fallback_transaction_id, fallback_action)},
        )
