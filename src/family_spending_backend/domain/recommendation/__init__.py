"""Non-authoritative Merchant and Category suggestions derived from reviewed Mapping."""

from family_spending_backend.domain.recommendation.engine import (
    RECOMMENDATION_MODEL_VERSION,
    MappingRecommendation,
    MappingRecommendationAlternative,
    MappingRecommendationEngine,
)

__all__ = [
    "RECOMMENDATION_MODEL_VERSION",
    "MappingRecommendation",
    "MappingRecommendationAlternative",
    "MappingRecommendationEngine",
]
