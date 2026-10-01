"""Scheduled Rule lifecycle and idempotent Manual Evidence materialization."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import Protocol
from uuid import uuid4

from family_spending_backend.application.errors import (
    ApplicationConflictError,
    ApplicationNotFoundError,
    ApplicationValidationError,
)
from family_spending_backend.application.models import (
    AutomationState,
    MutationOutcome,
    ReadModelChange,
)
from family_spending_backend.application.mutation import MutationImpact
from family_spending_backend.application.ports.runtime import (
    MutationExecutor,
    ScheduledStateReader,
)
from family_spending_backend.application.ports.storage import (
    EnrichmentDecisionStore,
    IdentityStore,
    ScheduleStore,
)
from family_spending_backend.application.ports.unit_of_work import UnitOfWork
from family_spending_backend.application.source_sync import SourceSyncService
from family_spending_backend.domain.enrichment import EnrichmentDecision
from family_spending_backend.domain.errors import DomainInvariantError
from family_spending_backend.domain.manual import (
    ManualEvidence,
    create_manual_evidence,
    manual_evidence_to_source_record,
)
from family_spending_backend.domain.scheduling import (
    ScheduleAction,
    ScheduledRule,
    ScheduleExecutionState,
    next_monthly_date,
    next_occurrence_date,
    scheduled_occurrence_identity,
)


class ManualEvidenceRepository(Protocol):
    def load_all(self) -> tuple[ManualEvidence, ...]: ...

    def replace_all(self, records: tuple[ManualEvidence, ...]) -> None: ...


@dataclass(frozen=True, slots=True)
class ScheduledInputRuleView:
    id: str
    enabled: bool
    transaction_type: str
    amount: Decimal
    currency: str
    description: str
    note: str | None
    next_date: date
    last_occurrence_date: date | None
    last_source_record_id: str | None
    last_transaction_id: str | None
    last_action: ScheduleAction | None


@dataclass(frozen=True, slots=True)
class ScheduledInputOccurrence:
    rule_id: str
    occurrence_date: date
    evidence_id: str
    source_record_id: str
    transaction_id: str
    action: ScheduleAction


@dataclass(frozen=True, slots=True)
class ScheduledInputRunResult:
    occurrences: tuple[ScheduledInputOccurrence, ...]
    impact: MutationImpact


class ScheduledInputService:
    def __init__(
        self,
        *,
        schedule_store: ScheduleStore,
        manual_store: ManualEvidenceRepository,
        enrichment_store: EnrichmentDecisionStore,
        identity_store: IdentityStore,
        source_sync: SourceSyncService,
        runtime: ScheduledStateReader,
        coordinator: MutationExecutor,
        open_unit_of_work: Callable[[str], UnitOfWork],
        new_id: Callable[[], str] = lambda: f"schedule_{uuid4().hex}",
    ) -> None:
        self._schedule = schedule_store
        self._manual = manual_store
        self._enrichments = enrichment_store
        self._identity = identity_store
        self._source_sync = source_sync
        self._runtime = runtime
        self._coordinator = coordinator
        self._open_unit_of_work = open_unit_of_work
        self._new_id = new_id

    def list_views(self) -> tuple[ScheduledInputRuleView, ...]:
        state = self._runtime.current_automation_state()
        execution = {item.rule_id: item for item in state.schedule_execution}
        return tuple(self._view(rule, execution.get(rule.id)) for rule in state.scheduled_rules)

    @staticmethod
    def _view(
        rule: ScheduledRule, execution: ScheduleExecutionState | None
    ) -> ScheduledInputRuleView:
        return ScheduledInputRuleView(
            id=rule.id,
            enabled=rule.enabled,
            transaction_type=rule.transaction_type,
            amount=rule.amount,
            currency=rule.currency,
            description=rule.description,
            note=rule.note,
            next_date=next_occurrence_date(rule, execution),
            last_occurrence_date=(execution.last_processed_occurrence_date if execution else None),
            last_source_record_id=execution.last_source_record_id if execution else None,
            last_transaction_id=execution.last_transaction_id if execution else None,
            last_action=execution.last_action if execution else None,
        )

    def create_rule(
        self,
        *,
        transaction_type: str,
        amount: Decimal,
        description: str,
        first_occurrence_date: date,
        currency: str = "CNY",
        note: str | None = None,
        enabled: bool = True,
        as_of: date | None = None,
        rule_id: str | None = None,
    ) -> ScheduledInputRuleView:
        try:
            rule = ScheduledRule(
                rule_id or self._new_id(),
                enabled,
                transaction_type,
                amount,
                description.strip(),
                first_occurrence_date,
                currency.strip().upper(),
                note.strip() if isinstance(note, str) and note.strip() else None,
            )
        except (DomainInvariantError, AttributeError) as exc:
            raise ApplicationValidationError(str(exc)) from exc

        def mutation() -> MutationOutcome[ScheduledInputRunResult]:
            rules = self._schedule.load_rules()
            if any(item.id == rule.id for item in rules):
                raise ApplicationConflictError(f"Scheduled Rule {rule.id!r} already exists")
            self._schedule.replace_rules((*rules, rule))
            return self._run_due_inside(as_of or date.today(), configuration_changed=True)

        self._coordinator.execute(
            label="Scheduled Input rule create",
            unit_of_work=self._open_unit_of_work("Scheduled Input rule create"),
            mutation=mutation,
        )
        return next(item for item in self.list_views() if item.id == rule.id)

    def update_rule(
        self,
        rule_id: str,
        *,
        transaction_type: str,
        amount: Decimal,
        description: str,
        first_occurrence_date: date,
        currency: str,
        note: str | None,
        enabled: bool,
        as_of: date | None = None,
    ) -> ScheduledInputRuleView:
        def mutation() -> MutationOutcome[ScheduledInputRunResult]:
            rules = self._schedule.load_rules()
            current = next((item for item in rules if item.id == rule_id), None)
            if current is None:
                raise ApplicationNotFoundError(f"Scheduled Rule {rule_id!r} does not exist")
            execution = next(
                (item for item in self._schedule.load_execution() if item.rule_id == rule_id),
                None,
            )
            if (
                execution is not None
                and execution.last_processed_occurrence_date is not None
                and first_occurrence_date <= execution.last_processed_occurrence_date
            ):
                raise ApplicationValidationError(
                    "Updated next occurrence must be after the last processed occurrence"
                )
            try:
                updated = replace(
                    current,
                    enabled=enabled,
                    transaction_type=transaction_type,
                    amount=amount,
                    description=description.strip(),
                    first_occurrence_date=first_occurrence_date,
                    currency=currency.strip().upper(),
                    note=note.strip() if isinstance(note, str) and note.strip() else None,
                )
            except (DomainInvariantError, AttributeError) as exc:
                raise ApplicationValidationError(str(exc)) from exc
            self._schedule.replace_rules(
                tuple(updated if item.id == rule_id else item for item in rules)
            )
            return self._run_due_inside(as_of or date.today(), configuration_changed=True)

        self._coordinator.execute(
            label="Scheduled Input rule update",
            unit_of_work=self._open_unit_of_work("Scheduled Input rule update"),
            mutation=mutation,
        )
        return next(item for item in self.list_views() if item.id == rule_id)

    def delete_rule(self, rule_id: str) -> ScheduledInputRuleView:
        def mutation() -> MutationOutcome[ScheduledInputRuleView]:
            stored_rules = self._schedule.load_rules()
            rule = next((item for item in stored_rules if item.id == rule_id), None)
            if rule is None:
                raise ApplicationNotFoundError(f"Scheduled Rule {rule_id!r} does not exist")
            stored_execution = self._schedule.load_execution()
            rule_execution = next(
                (item for item in stored_execution if item.rule_id == rule_id),
                None,
            )
            before = self._view(rule, rule_execution)
            rules = tuple(item for item in stored_rules if item.id != rule_id)
            execution = tuple(item for item in stored_execution if item.rule_id != rule_id)
            self._schedule.replace_rules(rules)
            self._schedule.replace_execution(execution)
            state = AutomationState(rules, execution)
            return MutationOutcome(before, ReadModelChange.automation_only(state))

        return self._coordinator.execute(
            label="Scheduled Input rule delete",
            unit_of_work=self._open_unit_of_work("Scheduled Input rule delete"),
            mutation=mutation,
        )

    def run_due(self, as_of: date) -> ScheduledInputRunResult:
        return self._coordinator.execute(
            label="Scheduled Input due run",
            unit_of_work=self._open_unit_of_work("Scheduled Input due run"),
            mutation=lambda: self._run_due_inside(as_of, configuration_changed=False),
        )

    def _run_due_inside(
        self, as_of: date, *, configuration_changed: bool
    ) -> MutationOutcome[ScheduledInputRunResult]:
        rules = self._schedule.load_rules()
        execution_by_rule = {item.rule_id: item for item in self._schedule.load_execution()}
        unknown = sorted(set(execution_by_rule) - {item.id for item in rules})
        if unknown:
            raise ApplicationConflictError(
                f"Schedule execution references missing rules: {unknown!r}"
            )
        manual_records = list(self._manual.load_all())
        evidence_by_id = {item.evidence_id: item for item in manual_records}
        links_before = {
            item.source_record_id: item
            for item in self._runtime.current_finance_state().source_links
        }
        pending: list[tuple[ScheduledRule, date, ManualEvidence, bool, bool]] = []
        needs_sync = False
        for rule in sorted(rules, key=lambda item: (item.first_occurrence_date, item.id)):
            if not rule.enabled:
                continue
            execution = execution_by_rule.get(rule.id)
            cursor = execution.last_processed_occurrence_date if execution else None
            occurrence = rule.first_occurrence_date
            while occurrence <= as_of:
                evidence_id = scheduled_occurrence_identity(rule.id, occurrence)
                evidence = evidence_by_id.get(evidence_id)
                was_new = evidence is None
                if evidence is None:
                    evidence = create_manual_evidence(
                        evidence_id=evidence_id,
                        transaction_type=rule.transaction_type,
                        transaction_date=occurrence,
                        amount=rule.amount,
                        currency=rule.currency,
                        description=rule.description,
                    )
                    evidence_by_id[evidence_id] = evidence
                    manual_records.append(evidence)
                    needs_sync = True
                source = manual_evidence_to_source_record(evidence)
                had_link = source.id in links_before
                unprocessed = cursor is None or occurrence > cursor
                if not had_link:
                    needs_sync = True
                if not had_link or unprocessed:
                    pending.append((rule, occurrence, evidence, had_link, was_new))
                occurrence = next_monthly_date(occurrence)

        current_finance = self._runtime.current_finance_state()
        if not pending:
            automation = AutomationState(rules, tuple(execution_by_rule.values()))
            impact = (
                MutationImpact.AUTOMATION_ONLY
                if configuration_changed
                else MutationImpact.NO_CHANGE
            )
            change = (
                ReadModelChange.automation_only(automation)
                if configuration_changed
                else ReadModelChange.none()
            )
            return MutationOutcome(ScheduledInputRunResult((), impact), change)

        self._manual.replace_all(tuple(manual_records))
        sync_outcome = self._source_sync.sync_inside_mutation() if needs_sync else None
        base_state = sync_outcome.change.finance if sync_outcome is not None else current_finance
        assert base_state is not None
        sync_decisions = (
            {item.source_record_id: item for item in sync_outcome.value.decisions}
            if sync_outcome
            else {}
        )
        links_after = {item.source_record_id: item for item in self._identity.load()}
        decisions = {item.transaction_id: item for item in self._enrichments.load()}
        occurrences: list[ScheduledInputOccurrence] = []
        for rule, occurrence_date, evidence, had_link, was_new in pending:
            source = manual_evidence_to_source_record(evidence)
            link = links_after.get(source.id)
            if link is None:
                raise ApplicationConflictError(
                    f"Scheduled occurrence {evidence.evidence_id!r} has no Transaction link"
                )
            reconciliation_decision = sync_decisions.get(source.id)
            action: ScheduleAction = (
                reconciliation_decision.action
                if reconciliation_decision is not None
                else ("recovered" if had_link else "reused")
            )
            if rule.note is not None and (was_new or not had_link):
                existing = decisions.get(link.transaction_id)
                decisions[link.transaction_id] = EnrichmentDecision(
                    link.transaction_id,
                    merchant_override=existing.merchant_override if existing else None,
                    category_override=existing.category_override if existing else None,
                    note=rule.note,
                )
            occurrence_result = ScheduledInputOccurrence(
                rule.id,
                occurrence_date,
                evidence.evidence_id,
                source.id,
                link.transaction_id,
                action,
            )
            occurrences.append(occurrence_result)
            previous = execution_by_rule.get(rule.id)
            if (
                previous is None
                or previous.last_processed_occurrence_date is None
                or occurrence_date > previous.last_processed_occurrence_date
            ):
                execution_by_rule[rule.id] = ScheduleExecutionState(
                    rule.id,
                    occurrence_date,
                    source.id,
                    link.transaction_id,
                    action,
                )
        durable_decisions = tuple(decisions.values())
        self._enrichments.replace(durable_decisions)
        execution = tuple(
            execution_by_rule[item.id] for item in rules if item.id in execution_by_rule
        )
        self._schedule.replace_execution(execution)
        impact = MutationImpact.TRANSACTIONS_AND_DOWNSTREAM
        state = replace(base_state, enrichment_decisions=durable_decisions)
        change = ReadModelChange.finance_changed(
            state,
            impact,
            automation=AutomationState(rules, execution),
        )
        return MutationOutcome(ScheduledInputRunResult(tuple(occurrences), impact), change)
