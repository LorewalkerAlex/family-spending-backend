from dataclasses import replace
from datetime import UTC, datetime

import pytest

from family_spending_backend.application.models import (
    AutomationState,
    ReadModelChange,
)
from family_spending_backend.application.mutation import MutationImpact
from family_spending_backend.domain.feedback import FeedbackContext, FeedbackItem
from family_spending_backend.domain.mapping import MappingCatalog
from family_spending_backend.read_model import HouseholdReadModel, ReadModelProjector


def test_change_contract_rejects_mismatched_scope_and_payload() -> None:
    with pytest.raises(ValueError, match="NO_CHANGE"):
        ReadModelChange(MutationImpact.NO_CHANGE, feedback_items=())
    with pytest.raises(ValueError, match="FEEDBACK_ONLY"):
        ReadModelChange(MutationImpact.FEEDBACK_ONLY)
    with pytest.raises(ValueError, match="must carry finance"):
        ReadModelChange(MutationImpact.FULL_REBUILD)


def test_projector_replaces_only_feedback_or_automation_subtree() -> None:
    current = HouseholdReadModel.empty()
    projector = ReadModelProjector()
    feedback = FeedbackItem(
        "feedback_1",
        datetime(2026, 10, 1, tzinfo=UTC),
        "open",
        "test feedback",
        FeedbackContext(),
    )
    with_feedback = projector.apply(current, ReadModelChange.feedback((feedback,)))
    assert with_feedback.finance is current.finance
    assert with_feedback.automation is current.automation
    assert with_feedback.feedback_items == (feedback,)

    automation = AutomationState()
    with_automation = projector.apply(
        with_feedback,
        ReadModelChange.automation_only(automation),
    )
    assert with_automation.finance is current.finance
    assert with_automation.feedback_items is with_feedback.feedback_items
    assert with_automation.automation is automation


def test_enrichment_change_rebuilds_finance_and_preserves_other_subtrees() -> None:
    current = HouseholdReadModel.empty()
    mappings = MappingCatalog(
        {"known": "merchant"},
        {"merchant": "category"},
        frozenset({"category"}),
    )
    next_finance = replace(current.finance.state(), mappings=mappings)
    changed = ReadModelProjector().apply(
        current,
        ReadModelChange.finance_changed(
            next_finance,
            MutationImpact.ENRICHMENTS_AND_PROJECTIONS,
        ),
    )
    assert changed.finance is not current.finance
    assert changed.transactions is current.transactions
    assert changed.automation is current.automation
    assert changed.feedback_items is current.feedback_items
    assert changed.mappings is mappings
