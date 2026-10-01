"""Stable API V1 response and error contracts."""

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class ApiMeta(BaseModel):
    request_id: str


class ApiResponse[DataT](BaseModel):
    data: DataT
    meta: ApiMeta


class ApiListMeta(ApiMeta):
    offset: int
    limit: int
    total: int
    sort: str


class ApiListResponse[ItemT](BaseModel):
    data: list[ItemT]
    meta: ApiListMeta


class ErrorDetail(BaseModel):
    location: list[str | int] = Field(default_factory=list)
    message: str
    type: str


class ApiErrorBody(BaseModel):
    code: str
    message: str
    request_id: str
    details: list[ErrorDetail] | None = None


class ErrorResponse(BaseModel):
    error: ApiErrorBody


class HealthData(BaseModel):
    status: Literal["ok"]
    service: Literal["family-spending-backend"]
    version: str


class RuntimeCountsData(BaseModel):
    source_records: int
    transactions: int
    enrichments: int
    mapping_reviews: int
    feedback: int


class RuntimeStatusData(BaseModel):
    phase: Literal["starting", "ready"]
    started_at: datetime
    generation: int
    queued_mutations: int
    last_successful_mutation: str | None
    last_failed_mutation: str | None
    last_imap_poll: str | None
    last_scheduler_tick: str | None
    parser_cache_hits: int
    parser_cache_misses: int
    counts: RuntimeCountsData
    schema_version: str
    parser_version: str


class ManualInputWriteRequest(BaseModel):
    transaction_type: Literal["income", "expense"]
    transaction_date: date
    amount: Decimal
    currency: str = "CNY"
    description: str | None = None


class TransactionData(BaseModel):
    id: str
    transaction_type: Literal["income", "expense"]
    transaction_date: date
    amount: Decimal
    currency: str


class EnrichmentDecisionData(BaseModel):
    merchant_override: str | None
    category_override: str | None
    note: str | None


class EnrichmentData(BaseModel):
    merchant_name: str | None
    display_name: str
    default_category: str | None
    category: str
    category_source: Literal[
        "merchant_default", "transaction_override", "income_default", "unclassified"
    ]
    is_unclassified: bool
    review_signals: list[str]
    note: str | None


class TransactionViewData(BaseModel):
    transaction: TransactionData
    authoritative_source_record_id: str
    description: str | None
    enrichment: EnrichmentData


class EnrichmentPatchRequest(BaseModel):
    merchant_override: str | None = None
    category_override: str | None = None
    note: str | None = None


class EnrichmentMutationData(BaseModel):
    transaction_id: str
    decision: EnrichmentDecisionData | None
    enrichment: EnrichmentData
    mutation_impact: Literal["enrichments_and_projections"]


class FeedbackContextData(BaseModel):
    runtime: Literal["desktop_web", "android"] | None = None
    page: str | None = None
    workspace: str | None = None
    entity_type: str | None = None
    entity_id: str | None = None


class FeedbackCreateRequest(BaseModel):
    content: str
    context: FeedbackContextData = Field(default_factory=FeedbackContextData)


class FeedbackStatusRequest(BaseModel):
    status: Literal["open", "resolved"]


class FeedbackData(BaseModel):
    id: str
    created_at: datetime
    status: Literal["open", "resolved"]
    content: str
    context: FeedbackContextData


class ScheduledRuleWriteRequest(BaseModel):
    enabled: bool = True
    transaction_type: Literal["income", "expense"]
    amount: Decimal
    currency: str = "CNY"
    description: str
    first_occurrence_date: date
    note: str | None = None


class ScheduledRuleData(BaseModel):
    id: str
    enabled: bool
    transaction_type: Literal["income", "expense"]
    amount: Decimal
    currency: str
    description: str
    note: str | None
    next_date: date
    last_occurrence_date: date | None
    last_source_record_id: str | None
    last_transaction_id: str | None
    last_action: Literal["created", "matched", "reused", "recovered"] | None


class ScheduledRunRequest(BaseModel):
    as_of: date


class ScheduledOccurrenceData(BaseModel):
    rule_id: str
    occurrence_date: date
    evidence_id: str
    source_record_id: str
    transaction_id: str
    action: Literal["created", "matched", "reused", "recovered"]


class ScheduledRunData(BaseModel):
    occurrences: list[ScheduledOccurrenceData]
    mutation_impact: Literal["no_change", "transactions_and_downstream"]


class ManualInputData(BaseModel):
    evidence_id: str
    source_record_id: str
    transaction_type: Literal["income", "expense"]
    transaction_date: date
    amount: Decimal
    currency: str
    description: str | None
    transaction_id: str | None
    source_role: Literal["authoritative", "supporting"] | None
    transaction: TransactionData | None


class ManualInputMutationData(BaseModel):
    item: ManualInputData
    action: Literal["created", "reused", "matched"]
    mutation_impact: Literal["transactions_and_downstream"]


class ManualInputDeletionData(BaseModel):
    evidence_id: str
    source_record_id: str
    transaction_id: str
    transaction_removed: bool
    mutation_impact: Literal["transactions_and_downstream"]


ERROR_RESPONSES = {
    401: {"model": ErrorResponse, "description": "Authentication failed"},
    404: {"model": ErrorResponse, "description": "Resource not found"},
    409: {"model": ErrorResponse, "description": "State conflict"},
    422: {"model": ErrorResponse, "description": "Request validation failed"},
    500: {"model": ErrorResponse, "description": "Internal server error"},
}
