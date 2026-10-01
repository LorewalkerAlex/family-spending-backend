"""Process-local cache for Mapping-derived recommendation indexes."""

from threading import RLock

from family_spending_backend.domain.mapping import MappingCatalog
from family_spending_backend.domain.recommendation import (
    MappingRecommendation,
    MappingRecommendationEngine,
)


class MappingRecommendationService:
    """Build once per immutable Mapping instance and expose disposable suggestions."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._catalog: MappingCatalog | None = None
        self._engine: MappingRecommendationEngine | None = None

    def recommend(
        self,
        catalog: MappingCatalog,
        description: str,
    ) -> MappingRecommendation:
        return self._for_catalog(catalog).recommend(description)

    def recommend_many(
        self,
        catalog: MappingCatalog,
        descriptions: tuple[str, ...],
    ) -> tuple[MappingRecommendation, ...]:
        return self._for_catalog(catalog).recommend_many(descriptions)

    def _for_catalog(self, catalog: MappingCatalog) -> MappingRecommendationEngine:
        with self._lock:
            if self._catalog is not catalog or self._engine is None:
                self._catalog = catalog
                self._engine = MappingRecommendationEngine(catalog)
            return self._engine
