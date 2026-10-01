"""Derived expense refund reconciliation and net consumption."""

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from family_spending_backend.domain.enrichment import ResolvedEnrichment
from family_spending_backend.domain.source import SourceRecord
from family_spending_backend.domain.transaction import Transaction

ZERO = Decimal("0")
MERCHANT_REFUND_LOOKBACK_DAYS = 30


class RefundReconciliationError(RuntimeError):
    pass


@dataclass(slots=True)
class _ConsumptionBalance:
    original_index: int
    transaction: Transaction
    merchant_name: str | None
    original_spending: Decimal
    remaining_spending: Decimal


@dataclass(frozen=True, slots=True)
class NetConsumption:
    transaction_id: str
    spending: Decimal


@dataclass(frozen=True, slots=True)
class RefundReconciliationResult:
    net_consumption: tuple[NetConsumption, ...]
    zero_amount_transactions: int
    refund_transactions: int
    same_merchant_refund_matches: int
    same_merchant_matched_amount: Decimal
    fully_refunded_transactions: int
    partially_refunded_transactions: int
    unmatched_refund_count: int
    unmatched_refund_amount: Decimal


def _find_exact_balance(
    balances: list[_ConsumptionBalance], refund_amount: Decimal
) -> _ConsumptionBalance | None:
    return next(
        (
            balance
            for balance in reversed(balances)
            if balance.remaining_spending == refund_amount and balance.remaining_spending > ZERO
        ),
        None,
    )


def _find_same_merchant_balance(
    balances: list[_ConsumptionBalance], refund: Transaction, refund_amount: Decimal
) -> _ConsumptionBalance | None:
    for balance in reversed(balances):
        age_days = (refund.transaction_date - balance.transaction.transaction_date).days
        if age_days > MERCHANT_REFUND_LOOKBACK_DAYS:
            break
        if age_days >= 0 and balance.remaining_spending == refund_amount:
            return balance
    return None


def reconcile_refunds(
    transactions: tuple[Transaction, ...],
    authoritative_sources_by_transaction_id: Mapping[str, SourceRecord],
    enrichments_by_transaction_id: Mapping[str, ResolvedEnrichment],
) -> RefundReconciliationResult:
    balances_by_description: dict[str, list[_ConsumptionBalance]] = {}
    balances_by_merchant: dict[str, list[_ConsumptionBalance]] = {}
    all_balances: list[_ConsumptionBalance] = []
    zero_count = refund_count = merchant_matches = unmatched_count = 0
    merchant_amount = unmatched_amount = ZERO

    ordered = sorted(enumerate(transactions), key=lambda item: (item[1].transaction_date, item[0]))
    for original_index, transaction in ordered:
        if transaction.transaction_type == "income":
            continue
        try:
            source = authoritative_sources_by_transaction_id[transaction.id]
            enrichment = enrichments_by_transaction_id[transaction.id]
        except KeyError as exc:
            raise RefundReconciliationError(
                f"Transaction {transaction.id!r} lacks authoritative projection state"
            ) from exc
        if enrichment.transaction_id != transaction.id:
            raise RefundReconciliationError(
                f"Enrichment identity mismatch for Transaction {transaction.id!r}"
            )
        amount = transaction.amount
        if amount == ZERO:
            zero_count += 1
            continue
        description_key = source.description or f"source:{source.id}"
        description_balances = balances_by_description.setdefault(description_key, [])
        merchant = enrichment.merchant_name
        if amount > ZERO:
            balance = _ConsumptionBalance(original_index, transaction, merchant, amount, amount)
            description_balances.append(balance)
            if merchant is not None:
                balances_by_merchant.setdefault(merchant, []).append(balance)
            all_balances.append(balance)
            continue

        refund_count += 1
        remaining = -amount
        exact = _find_exact_balance(description_balances, remaining)
        if exact is not None:
            exact.remaining_spending = ZERO
            remaining = ZERO
        else:
            merchant_balance = (
                _find_same_merchant_balance(
                    balances_by_merchant.get(merchant, []), transaction, remaining
                )
                if merchant is not None
                else None
            )
            if merchant_balance is not None:
                merchant_balance.remaining_spending = ZERO
                merchant_matches += 1
                merchant_amount += remaining
                remaining = ZERO
            else:
                for balance in reversed(description_balances):
                    if balance.remaining_spending <= ZERO:
                        continue
                    refunded = min(balance.remaining_spending, remaining)
                    balance.remaining_spending -= refunded
                    remaining -= refunded
                    if remaining == ZERO:
                        break
        if remaining > ZERO:
            unmatched_count += 1
            unmatched_amount += remaining

    return RefundReconciliationResult(
        net_consumption=tuple(
            NetConsumption(balance.transaction.id, balance.remaining_spending)
            for balance in sorted(all_balances, key=lambda item: item.original_index)
            if balance.remaining_spending > ZERO
        ),
        zero_amount_transactions=zero_count,
        refund_transactions=refund_count,
        same_merchant_refund_matches=merchant_matches,
        same_merchant_matched_amount=merchant_amount,
        fully_refunded_transactions=sum(
            balance.remaining_spending == ZERO for balance in all_balances
        ),
        partially_refunded_transactions=sum(
            ZERO < balance.remaining_spending < balance.original_spending
            for balance in all_balances
        ),
        unmatched_refund_count=unmatched_count,
        unmatched_refund_amount=unmatched_amount,
    )
