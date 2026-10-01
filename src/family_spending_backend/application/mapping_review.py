"""Deterministic preview and apply workflow for reviewed Mapping changes."""

import hashlib
import json
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from family_spending_backend.application.errors import (
    ApplicationConflictError,
    ApplicationValidationError,
)
from family_spending_backend.application.models import (
    FinanceState,
    MutationOutcome,
    ReadModelChange,
)
from family_spending_backend.application.mutation import MutationImpact
from family_spending_backend.application.ports.runtime import (
    FinanceStateReader,
    MutationExecutor,
)
from family_spending_backend.application.ports.storage import MappingStore
from family_spending_backend.application.ports.unit_of_work import UnitOfWork
from family_spending_backend.application.recommendation import MappingRecommendationService
from family_spending_backend.domain.enrichment import resolve_enrichments
from family_spending_backend.domain.errors import DomainInvariantError
from family_spending_backend.domain.mapping import MappingCatalog
from family_spending_backend.domain.recommendation import MappingRecommendation
from family_spending_backend.domain.source import SourceRecord


@dataclass(frozen=True, slots=True)
class MappingReviewItem:
    description: str
    transaction_count: int
    total_amount: Decimal
    currency: str
    latest_date: date
    source_types: tuple[str, ...]
    transaction_only_exception_count: int
    recommendation: MappingRecommendation


@dataclass(frozen=True, slots=True)
class MerchantMappingOption:
    name: str
    default_category: str


@dataclass(frozen=True, slots=True)
class MappingReviewPreview:
    token: str
    description: str
    merchant: str
    category: str
    is_new_merchant: bool
    previous_default_category: str | None
    description_transaction_count: int
    description_affected_transaction_count: int
    default_category_affected_transaction_count: int
    total_affected_transaction_count: int
    preserved_merchant_exception_count: int
    preserved_category_exception_count: int


@dataclass(frozen=True, slots=True)
class MappingReviewWorkspace:
    items: tuple[MappingReviewItem, ...]
    merchants: tuple[MerchantMappingOption, ...]
    categories: tuple[str, ...]


class MappingReviewService:
    def __init__(
        self,
        *,
        mapping_store: MappingStore,
        runtime: FinanceStateReader,
        coordinator: MutationExecutor,
        open_unit_of_work: Callable[[str], UnitOfWork],
        recommendations: MappingRecommendationService | None = None,
    ) -> None:
        self._mapping_store = mapping_store
        self._runtime = runtime
        self._coordinator = coordinator
        self._open_unit_of_work = open_unit_of_work
        self._recommendations = recommendations or MappingRecommendationService()

    @staticmethod
    def _authoritative_sources(state: FinanceState) -> dict[str, SourceRecord]:
        records = {record.id: record for record in state.source_records}
        return {
            link.transaction_id: records[link.source_record_id]
            for link in state.source_links
            if link.role == "authoritative"
        }

    def workspace(self) -> MappingReviewWorkspace:
        state = self._runtime.current_finance_state()
        authoritative = self._authoritative_sources(state)
        grouped: dict[str, list[str]] = defaultdict(list)
        for transaction in state.transactions:
            if transaction.transaction_type != "expense":
                continue
            description = authoritative[transaction.id].description
            if description is None or description in state.mappings.description_to_merchant:
                continue
            grouped[description].append(transaction.id)

        transactions = {transaction.id: transaction for transaction in state.transactions}
        decisions = {decision.transaction_id: decision for decision in state.enrichment_decisions}
        descriptions = tuple(grouped)
        recommendations = {
            item.description: item
            for item in self._recommendations.recommend_many(state.mappings, descriptions)
        }
        items: list[MappingReviewItem] = []
        for description, transaction_ids in grouped.items():
            matching = [transactions[item] for item in transaction_ids]
            currencies = {transaction.currency for transaction in matching}
            if len(currencies) != 1:
                raise ApplicationConflictError(
                    f"Unmapped description {description!r} spans multiple currencies"
                )
            items.append(
                MappingReviewItem(
                    description=description,
                    transaction_count=len(matching),
                    total_amount=sum(
                        (transaction.amount for transaction in matching), Decimal("0")
                    ),
                    currency=next(iter(currencies)),
                    latest_date=max(transaction.transaction_date for transaction in matching),
                    source_types=tuple(
                        sorted({authoritative[item].source_type for item in transaction_ids})
                    ),
                    transaction_only_exception_count=sum(
                        decisions.get(item) is not None
                        and decisions[item].merchant_override is not None
                        for item in transaction_ids
                    ),
                    recommendation=recommendations[description],
                )
            )
        return MappingReviewWorkspace(
            items=tuple(
                sorted(items, key=lambda item: (item.latest_date, item.description), reverse=True)
            ),
            merchants=tuple(
                MerchantMappingOption(name, state.mappings.merchant_to_category[name])
                for name in sorted(state.mappings.merchant_to_category)
            ),
            categories=tuple(sorted(state.mappings.categories)),
        )

    def recommend(self, description: str) -> MappingRecommendation:
        description = self._text(description, "description")
        state = self._runtime.current_finance_state()
        authoritative = self._authoritative_sources(state)
        is_pending = any(
            transaction.transaction_type == "expense"
            and authoritative[transaction.id].description == description
            and description not in state.mappings.description_to_merchant
            for transaction in state.transactions
        )
        if not is_pending:
            raise ApplicationValidationError(
                f"Unclassified expense description {description!r} does not exist"
            )
        return self._recommendations.recommend(state.mappings, description)

    def preview(self, *, description: str, merchant: str, category: str) -> MappingReviewPreview:
        return self._plan(self._runtime.current_finance_state(), description, merchant, category)[0]

    def apply(
        self,
        *,
        description: str,
        merchant: str,
        category: str,
        preview_token: str,
        confirm_new_merchant: bool = False,
    ) -> MappingReviewPreview:
        def mutation() -> MutationOutcome[MappingReviewPreview]:
            state = self._runtime.current_finance_state()
            preview, next_catalog = self._plan(state, description, merchant, category)
            if preview.token != preview_token:
                raise ApplicationConflictError(
                    "Mapping Review state changed after preview; refresh before applying"
                )
            if preview.is_new_merchant and not confirm_new_merchant:
                raise ApplicationValidationError(
                    "Creating a new Merchant requires explicit confirmation"
                )
            self._mapping_store.replace(next_catalog)
            return MutationOutcome(
                value=preview,
                change=ReadModelChange.finance_changed(
                    FinanceState(
                        state.source_records,
                        state.transactions,
                        state.source_links,
                        mappings=next_catalog,
                        enrichment_decisions=state.enrichment_decisions,
                        statement_dates=state.statement_dates,
                    ),
                    MutationImpact.ENRICHMENTS_AND_PROJECTIONS,
                ),
            )

        return self._coordinator.execute(
            label="Mapping Review apply",
            unit_of_work=self._open_unit_of_work("Mapping Review apply"),
            mutation=mutation,
        )

    def _plan(
        self, state: FinanceState, description: str, merchant: str, category: str
    ) -> tuple[MappingReviewPreview, MappingCatalog]:
        description = self._text(description, "description")
        merchant = self._text(merchant, "merchant")
        category = self._text(category, "category")
        mappings = state.mappings
        if description in mappings.description_to_merchant:
            raise ApplicationConflictError(
                f"Description {description!r} is already mapped; refresh Mapping Review"
            )
        if category not in mappings.categories:
            raise ApplicationValidationError(f"Unknown category {category!r}")

        authoritative = self._authoritative_sources(state)
        matching = {
            transaction.id
            for transaction in state.transactions
            if transaction.transaction_type == "expense"
            and authoritative[transaction.id].description == description
        }
        if not matching:
            raise ApplicationValidationError(
                f"Expense description {description!r} does not exist in the current state"
            )

        previous_category = mappings.merchant_to_category.get(merchant)
        is_new = previous_category is None
        if not is_new and previous_category != category:
            remaining = sum(
                mapped_category == previous_category
                for mapped_merchant, mapped_category in mappings.merchant_to_category.items()
                if mapped_merchant != merchant
            )
            if remaining == 0:
                raise ApplicationValidationError(
                    f"Cannot move the last Merchant out of Category {previous_category!r}"
                )

        descriptions = dict(mappings.description_to_merchant)
        merchants = dict(mappings.merchant_to_category)
        descriptions[description] = merchant
        merchants[merchant] = category
        try:
            next_catalog = MappingCatalog(descriptions, merchants, frozenset(merchants.values()))
        except DomainInvariantError as exc:
            raise ApplicationValidationError(str(exc)) from exc

        before = {
            item.transaction_id: item
            for item in resolve_enrichments(
                state.transactions, authoritative, mappings, state.enrichment_decisions
            )
        }
        after = {
            item.transaction_id: item
            for item in resolve_enrichments(
                state.transactions, authoritative, next_catalog, state.enrichment_decisions
            )
        }
        changed = {item for item in before if before[item] != after[item]}
        decisions = {decision.transaction_id: decision for decision in state.enrichment_decisions}
        return (
            MappingReviewPreview(
                token=self._token(state, description, merchant, category, matching, authoritative),
                description=description,
                merchant=merchant,
                category=category,
                is_new_merchant=is_new,
                previous_default_category=previous_category,
                description_transaction_count=len(matching),
                description_affected_transaction_count=len(changed & matching),
                default_category_affected_transaction_count=len(changed - matching),
                total_affected_transaction_count=len(changed),
                preserved_merchant_exception_count=sum(
                    decisions.get(item) is not None
                    and decisions[item].merchant_override is not None
                    for item in matching
                ),
                preserved_category_exception_count=sum(
                    decisions.get(item) is not None
                    and decisions[item].category_override is not None
                    and before[item].category == after[item].category
                    for item in changed
                ),
            ),
            next_catalog,
        )

    @staticmethod
    def _token(
        state: FinanceState,
        description: str,
        merchant: str,
        category: str,
        matching: set[str],
        authoritative: dict[str, SourceRecord],
    ) -> str:
        payload = {
            "description": description,
            "merchant": merchant,
            "category": category,
            "description_to_merchant": sorted(state.mappings.description_to_merchant.items()),
            "merchant_to_category": sorted(state.mappings.merchant_to_category.items()),
            "transactions": [
                {
                    "id": transaction.id,
                    "type": transaction.transaction_type,
                    "description": authoritative[transaction.id].description,
                }
                for transaction in state.transactions
            ],
            "matching": sorted(matching),
            "decisions": [
                {
                    "transaction_id": decision.transaction_id,
                    "merchant_override": decision.merchant_override,
                    "category_override": decision.category_override,
                    "note": decision.note,
                }
                for decision in state.enrichment_decisions
            ],
        }
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _text(value: str, field: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ApplicationValidationError(f"{field} must be non-empty text")
        return value.strip()
