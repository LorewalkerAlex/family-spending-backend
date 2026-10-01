"""HTTP contracts for Mapping Review and non-authoritative recommendations."""

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel


class MappingRecommendationAlternativeData(BaseModel):
    merchant: str
    category: str | None
    rank_score: float
    matched_description: str


class MappingRecommendationData(BaseModel):
    description: str
    merchant: str
    category: str | None
    rank_score: float
    score_margin: float
    confidence: Literal["strong", "weak", "drafted"]
    origin: Literal["exact", "normalized_history", "history", "draft"]
    is_new_merchant: bool
    category_basis: Literal["reviewed_merchant_default", "keyword", "none"]
    matched_description: str | None
    evidence: list[str]
    signals: dict[str, float]
    alternatives: list[MappingRecommendationAlternativeData]
    model_version: str


class MappingReviewItemData(BaseModel):
    description: str
    transaction_count: int
    total_amount: Decimal
    currency: str
    latest_date: date
    source_types: list[str]
    transaction_only_exception_count: int
    recommendation: MappingRecommendationData


class MerchantMappingOptionData(BaseModel):
    name: str
    default_category: str


class MappingReviewWorkspaceData(BaseModel):
    items: list[MappingReviewItemData]
    merchants: list[MerchantMappingOptionData]
    categories: list[str]


class MappingReviewRequest(BaseModel):
    description: str
    merchant: str
    category: str


class MappingRecommendationRequest(BaseModel):
    description: str


class MappingReviewApplyRequest(MappingReviewRequest):
    preview_token: str
    confirm_new_merchant: bool = False


class MappingReviewPreviewData(BaseModel):
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


class MappingReviewApplyData(BaseModel):
    preview: MappingReviewPreviewData
    mutation_impact: Literal["enrichments_and_projections"]
