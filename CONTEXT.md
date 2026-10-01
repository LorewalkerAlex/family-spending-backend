# Family Spending

This context turns durable household financial evidence into stable financial facts that can be enriched, reconciled, and projected without losing identity history.

## Language

**Source Evidence**:
An immutable or explicitly lifecycle-managed financial input received from an external source or directly from the household.
_Avoid_: Raw data, import row

**Manual Evidence**:
Source Evidence authored directly by the household with a permanent evidence identity across explicit corrections.
_Avoid_: Manual transaction, form submission

**CMB Email Evidence**:
Immutable raw CMB statement EML bytes identified by their SHA-256 content digest.
_Avoid_: Mail filename, parsed statement

**Parsed Evidence Result**:
A version-specific derived result containing statement metadata, normalized SourceRecords, and parse diagnostics from one Evidence item.
_Avoid_: Imported transactions, durable decision

**SourceRecord**:
A normalized financial fact located within one Source Evidence item. Its identity is anchored to the source type, evidence identity, and a stable record locator.
_Avoid_: Parsed transaction, source transaction

**Transaction**:
A system-level financial fact with stable identity, backed by one or more SourceRecords that represent the same real-world fact.
_Avoid_: Record, ledger row

**SourceLink**:
A durable identity decision associating one SourceRecord with one Transaction and assigning it an authoritative or supporting role.
_Avoid_: Match cache, transaction mapping

**Authoritative SourceLink**:
The single SourceLink whose SourceRecord supplies the current core facts of a Transaction.
_Avoid_: Primary link

**Supporting SourceLink**:
A SourceLink providing additional evidence for a Transaction without supplying its current core facts.
_Avoid_: Secondary link

**Reconciliation**:
The process that preserves existing SourceLinks and assigns previously unlinked SourceRecords to stable Transaction identities.
_Avoid_: Deduplication, matching

**Source Correction**:
An explicit change to the financial facts of lifecycle-managed Source Evidence while retaining its SourceRecord identity for reconsideration.
_Avoid_: Transaction edit

**Merchant**:
A reviewed household-facing name for the counterparty represented by an expense description.
_Avoid_: Vendor ID, raw description

**Category**:
A reviewed household spending classification used as a Merchant default or Transaction-specific override. `待分类` is runtime state, not a formal Category.
_Avoid_: Tag, label

**Mapping**:
Reviewed household knowledge connecting SourceRecord descriptions to Merchants and Merchants to default Categories.
_Avoid_: Suggestion cache, enrichment output

**Mapping Recommendation**:
A disposable, non-authoritative suggestion for pre-filling a Merchant and optional Category from reviewed Mapping knowledge; it never changes household decisions without explicit review.
_Avoid_: Automatic Mapping, predicted decision

**Enrichment Decision**:
A sparse durable household decision overriding one Transaction's Merchant, Category, or Note.
_Avoid_: Materialized enrichment, mapping copy

**Resolved Enrichment**:
The current derived interpretation of a Transaction from its authoritative SourceRecord, Mapping, and optional Enrichment Decision.
_Avoid_: Saved enrichment

**Refund Reconciliation**:
The derived matching of negative expense Transactions against earlier positive purchases without mutating either Transaction.
_Avoid_: Refund deletion, transaction merge

**Net Consumption**:
The positive spending that survives Refund Reconciliation while retaining the original purchase Transaction identity.
_Avoid_: Adjusted transaction

**Statement Coverage**:
The rebuildable set of statement dates whose Evidence has all SourceRecords reconciled; unreconciled Evidence cannot make a projection month complete.
_Avoid_: Imported month, filename month

**Spending Projection**:
A rebuildable aggregation of Net Consumption by natural month, Category, and Merchant.
_Avoid_: Spending ledger

**Financial Projection**:
A rebuildable monthly view combining income Transactions with the Spending Projection to derive cash flow.
_Avoid_: Account balance

**Feedback**:
A durable local product observation with optional client and entity context, kept independent from financial facts.
_Avoid_: Support ticket, financial note

**Scheduled Rule**:
A durable monthly configuration that materializes due occurrences as Manual Evidence.
_Avoid_: Recurring transaction

**Schedule Execution State**:
An operational cursor recording the latest materialized occurrence separately from its Scheduled Rule.
_Avoid_: Rule history, transaction state
