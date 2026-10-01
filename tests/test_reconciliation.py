from datetime import date
from decimal import Decimal

import pytest

from family_spending_backend.domain.reconciliation import (
    ReconciliationEngine,
    ReconciliationError,
    ReconciliationHints,
    ReconciliationProposal,
    ReconciliationState,
)
from family_spending_backend.domain.source import SourceIdentity, SourceRecord
from family_spending_backend.domain.transaction import (
    SourceLink,
    SourceLinkRole,
    build_reconsidered_transaction_id,
    build_transaction_id,
)
from family_spending_backend.sources.cmb_email.reconciliation import (
    CmbEmailReconciliationPolicy,
)
from family_spending_backend.sources.manual.reconciliation import ManualReconciliationPolicy


def record(
    source_type: str,
    evidence: str,
    *,
    when: str = "2026-01-02",
    amount: str = "20",
    currency: str = "CNY",
) -> SourceRecord:
    return SourceRecord(
        identity=SourceIdentity(source_type, evidence, "record"),
        transaction_type="expense",
        transaction_date=date.fromisoformat(when),
        amount=Decimal(amount),
        currency=currency,
        description=None,
    )


class FakePolicy:
    source_type = "fake"
    processing_order = 300

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
        del record, state
        return ReconciliationProposal(None, "authoritative")


@pytest.fixture
def engine() -> ReconciliationEngine:
    return ReconciliationEngine((CmbEmailReconciliationPolicy(), ManualReconciliationPolicy()))


def test_cmb_first_run_creates_authoritative_transaction(
    engine: ReconciliationEngine,
) -> None:
    cmb = record("cmb_email", "cmb-a")

    result = engine.reconcile((cmb,))

    assert result.transactions[0].id == build_transaction_id(cmb)
    assert result.source_links == (SourceLink(result.transactions[0].id, cmb.id, "authoritative"),)
    assert result.decisions[0].action == "created"


def test_existing_source_link_is_reused_without_rematching(
    engine: ReconciliationEngine,
) -> None:
    manual = record("manual", "manual-a")
    existing = (SourceLink("txn_historical", manual.id, "authoritative"),)

    result = engine.reconcile((manual,), existing_links=existing)

    assert result.transactions[0].id == "txn_historical"
    assert result.decisions[0].action == "reused"
    assert result.decisions[0].evidence.source_identity_match is True


def test_source_policy_is_extensible_without_engine_branching() -> None:
    fake = record("fake", "fake-a")

    result = ReconciliationEngine((FakePolicy(),)).reconcile((fake,))

    assert result.source_links[0].source_record_id == fake.id


def test_engine_rejects_duplicate_policy_and_unknown_source() -> None:
    with pytest.raises(ReconciliationError, match="Duplicate"):
        ReconciliationEngine((FakePolicy(), FakePolicy()))

    with pytest.raises(ReconciliationError, match="No Reconciliation policy"):
        ReconciliationEngine((FakePolicy(),)).reconcile((record("unknown", "a"),))


def test_manual_matches_one_existing_cmb_as_supporting(
    engine: ReconciliationEngine,
) -> None:
    cmb = record("cmb_email", "cmb-a")
    initial = engine.reconcile((cmb,))
    manual = record("manual", "manual-a")

    result = engine.reconcile((cmb, manual), existing_links=initial.source_links)

    transaction_id = initial.transactions[0].id
    assert SourceLink(transaction_id, cmb.id, "authoritative") in result.source_links
    assert SourceLink(transaction_id, manual.id, "supporting") in result.source_links
    assert result.decisions[-1].action == "matched"


def test_manual_candidate_requires_matching_core_facts(
    engine: ReconciliationEngine,
) -> None:
    cmb = record("cmb_email", "cmb-a")
    initial = engine.reconcile((cmb,))

    for manual in (
        record("manual", "different-amount", amount="21"),
        record("manual", "different-date", when="2026-01-06"),
        record("manual", "different-currency", currency="USD"),
    ):
        result = engine.reconcile((cmb, manual), existing_links=initial.source_links)
        assert len(result.transactions) == 2
        assert (
            next(link for link in result.source_links if link.source_record_id == manual.id).role
            == "authoritative"
        )


def test_manual_ambiguous_candidates_fail_instead_of_guessing(
    engine: ReconciliationEngine,
) -> None:
    cmb_a = record("cmb_email", "cmb-a")
    cmb_b = record("cmb_email", "cmb-b")
    manual = record("manual", "manual-a")
    existing = (
        SourceLink("txn_a", cmb_a.id, "authoritative"),
        SourceLink("txn_b", cmb_b.id, "authoritative"),
    )

    with pytest.raises(ReconciliationError, match="matches multiple Transactions"):
        engine.reconcile((cmb_a, cmb_b, manual), existing_links=existing)


def test_unique_merchant_hint_disambiguates_candidate(
    engine: ReconciliationEngine,
) -> None:
    cmb_a = record("cmb_email", "cmb-a")
    cmb_b = record("cmb_email", "cmb-b")
    manual = record("manual", "manual-a")
    existing = (
        SourceLink("txn_a", cmb_a.id, "authoritative"),
        SourceLink("txn_b", cmb_b.id, "authoritative"),
    )
    hints = ReconciliationHints(
        merchant_by_transaction_id={"txn_a": "A", "txn_b": "B"},
        merchant_by_source_record_id={manual.id: "B"},
    )

    result = engine.reconcile(
        (cmb_a, cmb_b, manual),
        existing_links=existing,
        hints=hints,
    )

    link = next(item for item in result.source_links if item.source_record_id == manual.id)
    assert link == SourceLink("txn_b", manual.id, "supporting")


def test_cmb_takes_authority_from_one_manual_backed_transaction(
    engine: ReconciliationEngine,
) -> None:
    manual = record("manual", "manual-a")
    cmb = record("cmb_email", "cmb-a")
    existing = (SourceLink("txn_manual", manual.id, "authoritative"),)

    result = engine.reconcile((manual, cmb), existing_links=existing)

    assert len(result.transactions) == 1
    assert result.transactions[0].id == "txn_manual"
    assert SourceLink("txn_manual", manual.id, "supporting") in result.source_links
    assert SourceLink("txn_manual", cmb.id, "authoritative") in result.source_links


def test_ambiguous_cmb_match_creates_separate_transaction(
    engine: ReconciliationEngine,
) -> None:
    manual_a = record("manual", "manual-a")
    manual_b = record("manual", "manual-b")
    cmb = record("cmb_email", "cmb-a")
    existing = (
        SourceLink("txn_manual_a", manual_a.id, "authoritative"),
        SourceLink("txn_manual_b", manual_b.id, "authoritative"),
    )

    result = engine.reconcile((manual_a, manual_b, cmb), existing_links=existing)

    cmb_link = next(item for item in result.source_links if item.source_record_id == cmb.id)
    assert cmb_link == SourceLink(build_transaction_id(cmb), cmb.id, "authoritative")
    assert len(result.transactions) == 3


def test_policy_order_is_independent_of_input_order(
    engine: ReconciliationEngine,
) -> None:
    cmb_a = record("cmb_email", "cmb-a")
    cmb_b = record("cmb_email", "cmb-b")
    manual = record("manual", "manual-a")

    with pytest.raises(ReconciliationError):
        engine.reconcile((manual, cmb_a, cmb_b))
    with pytest.raises(ReconciliationError):
        engine.reconcile((cmb_a, cmb_b, manual))


def test_missing_linked_source_fails_fast(engine: ReconciliationEngine) -> None:
    missing = SourceLink("txn_missing", "src_missing", "authoritative")

    with pytest.raises(ReconciliationError, match="missing SourceRecord"):
        engine.reconcile((), existing_links=(missing,))


def test_source_removal_promotes_surviving_support(
    engine: ReconciliationEngine,
) -> None:
    manual = record("manual", "manual-support")

    repaired = engine.recover_authority_after_source_removal(
        (manual,),
        (SourceLink("txn_preserved", manual.id, "supporting"),),
    )

    assert repaired == (SourceLink("txn_preserved", manual.id, "authoritative"),)


def test_source_removal_uses_policy_authority_order(
    engine: ReconciliationEngine,
) -> None:
    cmb = record("cmb_email", "cmb-support")
    manual = record("manual", "manual-support")

    repaired = engine.recover_authority_after_source_removal(
        (manual, cmb),
        (
            SourceLink("txn_preserved", manual.id, "supporting"),
            SourceLink("txn_preserved", cmb.id, "supporting"),
        ),
    )

    assert SourceLink("txn_preserved", cmb.id, "authoritative") in repaired
    assert SourceLink("txn_preserved", manual.id, "supporting") in repaired


def test_corrected_standalone_source_reuses_historical_transaction(
    engine: ReconciliationEngine,
) -> None:
    corrected = record("manual", "manual-corrected", amount="30")

    result = engine.reconcile_reconsidered_source(
        (corrected,),
        existing_links=(SourceLink("txn_historical", corrected.id, "authoritative"),),
        source_record_id=corrected.id,
    )

    assert result.transactions[0].id == "txn_historical"
    assert result.transactions[0].amount == Decimal("30")
    assert result.decisions[0].action == "reused"


def test_corrected_source_splits_without_colliding_with_old_transaction(
    engine: ReconciliationEngine,
) -> None:
    cmb = record("cmb_email", "cmb-old", amount="20")
    corrected = record("manual", "manual-split", amount="30")
    existing = (
        SourceLink("txn_preserved", cmb.id, "authoritative"),
        SourceLink("txn_preserved", corrected.id, "supporting"),
    )

    result = engine.reconcile_reconsidered_source(
        (cmb, corrected),
        existing_links=existing,
        source_record_id=corrected.id,
    )
    split_id = build_reconsidered_transaction_id(corrected, "txn_preserved")

    assert SourceLink("txn_preserved", cmb.id, "authoritative") in result.source_links
    assert SourceLink(split_id, corrected.id, "authoritative") in result.source_links
    assert {item.id for item in result.transactions} == {"txn_preserved", split_id}


def test_corrected_manual_can_converge_to_another_transaction(
    engine: ReconciliationEngine,
) -> None:
    corrected = record("manual", "manual-converge", amount="30")
    cmb = record("cmb_email", "cmb-target", amount="30")
    existing = (
        SourceLink("txn_old", corrected.id, "authoritative"),
        SourceLink("txn_target", cmb.id, "authoritative"),
    )

    result = engine.reconcile_reconsidered_source(
        (corrected, cmb),
        existing_links=existing,
        source_record_id=corrected.id,
    )

    corrected_link = next(
        item for item in result.source_links if item.source_record_id == corrected.id
    )
    assert corrected_link == SourceLink("txn_target", corrected.id, "supporting")
    assert tuple(item.id for item in result.transactions) == ("txn_target",)
