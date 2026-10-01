"""Transaction-specific Enrichment decision lifecycle."""

from collections.abc import Callable
from dataclasses import dataclass, replace

from family_spending_backend.application.errors import ApplicationNotFoundError
from family_spending_backend.application.models import MutationOutcome, ReadModelChange
from family_spending_backend.application.mutation import MutationImpact
from family_spending_backend.application.ports.runtime import (
    FinanceStateReader,
    MutationExecutor,
)
from family_spending_backend.application.ports.storage import EnrichmentDecisionStore
from family_spending_backend.application.ports.unit_of_work import UnitOfWork
from family_spending_backend.domain.enrichment import (
    EnrichmentDecision,
    ResolvedEnrichment,
    resolve_enrichments,
)
from family_spending_backend.domain.errors import DomainInvariantError


class _Unset:
    pass


UNSET = _Unset()
DecisionValue = str | None | _Unset


@dataclass(frozen=True, slots=True)
class EnrichmentMutationResult:
    transaction_id: str
    decision: EnrichmentDecision | None
    enrichment: ResolvedEnrichment
    impact: MutationImpact


class EnrichmentService:
    def __init__(
        self,
        *,
        enrichment_store: EnrichmentDecisionStore,
        runtime: FinanceStateReader,
        coordinator: MutationExecutor,
        open_unit_of_work: Callable[[str], UnitOfWork],
    ) -> None:
        self._enrichments = enrichment_store
        self._runtime = runtime
        self._coordinator = coordinator
        self._open_unit_of_work = open_unit_of_work

    def update(
        self,
        transaction_id: str,
        *,
        merchant_override: DecisionValue = UNSET,
        category_override: DecisionValue = UNSET,
        note: DecisionValue = UNSET,
    ) -> EnrichmentMutationResult:
        if all(isinstance(value, _Unset) for value in (merchant_override, category_override, note)):
            raise DomainInvariantError("Enrichment update must specify at least one field")

        def mutation() -> MutationOutcome[EnrichmentMutationResult]:
            state = self._runtime.current_finance_state()
            if not any(item.id == transaction_id for item in state.transactions):
                raise ApplicationNotFoundError(f"Transaction {transaction_id!r} does not exist")

            decisions = list(state.enrichment_decisions)
            existing = next(
                (item for item in decisions if item.transaction_id == transaction_id), None
            )

            def resolved_value(value: DecisionValue, field: str) -> str | None:
                if not isinstance(value, _Unset):
                    return value
                return getattr(existing, field) if existing is not None else None

            values = {
                "merchant_override": resolved_value(merchant_override, "merchant_override"),
                "category_override": resolved_value(category_override, "category_override"),
                "note": resolved_value(note, "note"),
            }
            replacement = (
                None
                if all(value is None for value in values.values())
                else EnrichmentDecision(transaction_id=transaction_id, **values)
            )
            decisions = [item for item in decisions if item.transaction_id != transaction_id]
            if replacement is not None:
                decisions.append(replacement)
            durable_decisions = tuple(decisions)

            records_by_id = {record.id: record for record in state.source_records}
            authoritative = {
                link.transaction_id: records_by_id[link.source_record_id]
                for link in state.source_links
                if link.role == "authoritative"
            }
            resolved = resolve_enrichments(
                state.transactions,
                authoritative,
                state.mappings,
                durable_decisions,
            )
            enrichment = next(item for item in resolved if item.transaction_id == transaction_id)
            self._enrichments.replace(durable_decisions)
            impact = MutationImpact.ENRICHMENTS_AND_PROJECTIONS
            return MutationOutcome(
                value=EnrichmentMutationResult(
                    transaction_id=transaction_id,
                    decision=replacement,
                    enrichment=enrichment,
                    impact=impact,
                ),
                change=ReadModelChange.finance_changed(
                    replace(state, enrichment_decisions=durable_decisions),
                    impact,
                ),
            )

        return self._coordinator.execute(
            label="Enrichment decision update",
            unit_of_work=self._open_unit_of_work("Enrichment decision update"),
            mutation=mutation,
        )
