"""Apply typed application changes to immutable read-model subtrees."""

from dataclasses import replace

from family_spending_backend.application.models import ReadModelChange
from family_spending_backend.application.mutation import MutationImpact
from family_spending_backend.read_model.model import FinanceReadModel, HouseholdReadModel


class ReadModelProjector:
    """Own the mapping from committed change scope to derived memory state."""

    def apply(
        self,
        current: HouseholdReadModel,
        change: ReadModelChange,
    ) -> HouseholdReadModel:
        if change.impact is MutationImpact.NO_CHANGE:
            return current
        if change.impact is MutationImpact.FEEDBACK_ONLY:
            assert change.feedback_items is not None
            return replace(current, feedback_items=change.feedback_items)
        if change.impact is MutationImpact.AUTOMATION_ONLY:
            assert change.automation is not None
            return replace(current, automation=change.automation)

        assert change.finance is not None
        finance = FinanceReadModel.from_state(change.finance)
        return replace(
            current,
            finance=finance,
            automation=change.automation or current.automation,
        )
