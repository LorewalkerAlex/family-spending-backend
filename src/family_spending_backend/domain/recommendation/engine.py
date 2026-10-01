"""Explainable, non-authoritative recommendations from reviewed Mapping knowledge."""

from collections import defaultdict
from dataclasses import dataclass
from typing import Literal

from family_spending_backend.domain.mapping import MappingCatalog
from family_spending_backend.domain.recommendation.drafting import (
    clean_merchant_name,
    guess_category,
    learn_region_prefixes,
)
from family_spending_backend.domain.recommendation.normalization import fold, parse
from family_spending_backend.domain.recommendation.scoring import RankingIndex

RECOMMENDATION_MODEL_VERSION = "mapping-ensemble-v2"
STRONG_SCORE_THRESHOLD = 0.70
WEAK_SCORE_THRESHOLD = 0.45
STRONG_MARGIN_THRESHOLD = 0.05
MIN_ALTERNATIVE_SCORE = 0.02

RecommendationConfidence = Literal["strong", "weak", "drafted"]
RecommendationOrigin = Literal["exact", "normalized_history", "history", "draft"]
CategoryBasis = Literal["reviewed_merchant_default", "keyword", "none"]


@dataclass(frozen=True, slots=True)
class MappingRecommendationAlternative:
    merchant: str
    category: str | None
    rank_score: float
    matched_description: str


@dataclass(frozen=True, slots=True)
class MappingRecommendation:
    """A disposable suggestion. It never becomes a durable decision by itself."""

    description: str
    merchant: str
    category: str | None
    rank_score: float
    score_margin: float
    confidence: RecommendationConfidence
    origin: RecommendationOrigin
    is_new_merchant: bool
    category_basis: CategoryBasis
    matched_description: str | None
    evidence: tuple[str, ...]
    signals: tuple[tuple[str, float], ...]
    alternatives: tuple[MappingRecommendationAlternative, ...]
    model_version: str = RECOMMENDATION_MODEL_VERSION


class MappingRecommendationEngine:
    """Immutable index built from one reviewed Mapping catalog."""

    def __init__(self, catalog: MappingCatalog) -> None:
        self._catalog = catalog
        descriptions = dict(catalog.description_to_merchant)
        categories = dict(catalog.merchant_to_category)
        self._ranking = RankingIndex(descriptions, categories)
        self._region_prefixes = learn_region_prefixes(descriptions)
        self._known_merchants = frozenset(descriptions.values())
        self._merchant_by_folded_name = {
            fold(merchant): merchant for merchant in self._known_merchants
        }
        merchants_by_core: dict[str, set[str]] = defaultdict(set)
        descriptions_by_core: dict[str, list[str]] = defaultdict(list)
        for raw, merchant in descriptions.items():
            core = fold(parse(raw).core)
            merchants_by_core[core].add(merchant)
            descriptions_by_core[core].append(raw)
        self._unique_core_match = {
            core: next(iter(merchants))
            for core, merchants in merchants_by_core.items()
            if core and len(merchants) == 1
        }
        self._description_by_core = {
            core: min(values, key=lambda item: (len(item), item))
            for core, values in descriptions_by_core.items()
        }
        self._cache: dict[str, MappingRecommendation] = {}

    def recommend(self, description: str) -> MappingRecommendation:
        raw = description.strip()
        if not raw:
            raise ValueError("description must be non-empty text")
        cached = self._cache.get(raw)
        if cached is not None:
            return cached
        result = self._recommend_uncached(raw)
        if len(self._cache) >= 4096:
            self._cache.clear()
        self._cache[raw] = result
        return result

    def _recommend_uncached(self, raw: str) -> MappingRecommendation:

        exact = self._catalog.description_to_merchant.get(raw)
        if exact is not None:
            return self._historical_result(
                raw,
                exact,
                score=1.0,
                margin=1.0,
                confidence="strong",
                origin="exact",
                matched_description=raw,
                evidence=("exact reviewed Mapping key",),
            )

        core = fold(parse(raw).core)
        normalized = self._unique_core_match.get(core)
        if normalized is not None:
            return self._historical_result(
                raw,
                normalized,
                score=0.99,
                margin=0.99,
                confidence="strong",
                origin="normalized_history",
                matched_description=self._description_by_core[core],
                evidence=("unique normalized description core",),
            )

        ranked = self._ranking.rank(raw)
        top = ranked[0] if ranked else None
        runner_up = ranked[1] if len(ranked) > 1 else None
        margin = max(0.0, top.score - runner_up.score) if top and runner_up else 0.0
        if top is not None and top.score >= WEAK_SCORE_THRESHOLD:
            confidence: RecommendationConfidence = (
                "strong"
                if top.score >= STRONG_SCORE_THRESHOLD and margin >= STRONG_MARGIN_THRESHOLD
                else "weak"
            )
            return MappingRecommendation(
                description=raw,
                merchant=top.merchant,
                category=top.category,
                rank_score=round(top.score, 4),
                score_margin=round(margin, 4),
                confidence=confidence,
                origin="history",
                is_new_merchant=False,
                category_basis="reviewed_merchant_default",
                matched_description=top.matched_description,
                evidence=top.evidence,
                signals=tuple((name, round(value, 4)) for name, value in top.signals),
                alternatives=self._alternatives(ranked[1:4]),
            )

        name = clean_merchant_name(raw, self._region_prefixes) or raw
        existing = self._merchant_by_folded_name.get(fold(name))
        if existing is not None:
            category = self._catalog.merchant_to_category.get(existing)
            return MappingRecommendation(
                description=raw,
                merchant=existing,
                category=category,
                rank_score=0.0,
                score_margin=0.0,
                confidence="drafted",
                origin="normalized_history",
                is_new_merchant=False,
                category_basis="reviewed_merchant_default",
                matched_description=None,
                evidence=("drafted name equals an existing reviewed Merchant",),
                signals=(),
                alternatives=self._alternatives(ranked[:3]),
            )

        category, keyword = guess_category(name, raw, self._catalog.categories)
        evidence = ["drafted after removing payment, branch, legal, and region wrappers"]
        if keyword is not None:
            evidence.append(f"category keyword {keyword!r}")
        return MappingRecommendation(
            description=raw,
            merchant=name,
            category=category,
            rank_score=0.0,
            score_margin=0.0,
            confidence="drafted",
            origin="draft",
            is_new_merchant=True,
            category_basis="keyword" if category is not None else "none",
            matched_description=None,
            evidence=tuple(evidence),
            signals=(),
            alternatives=self._alternatives(ranked[:3]),
        )

    def recommend_many(self, descriptions: tuple[str, ...]) -> tuple[MappingRecommendation, ...]:
        return tuple(self.recommend(description) for description in descriptions)

    def _historical_result(
        self,
        description: str,
        merchant: str,
        *,
        score: float,
        margin: float,
        confidence: RecommendationConfidence,
        origin: RecommendationOrigin,
        matched_description: str,
        evidence: tuple[str, ...],
    ) -> MappingRecommendation:
        return MappingRecommendation(
            description=description,
            merchant=merchant,
            category=self._catalog.merchant_to_category.get(merchant),
            rank_score=score,
            score_margin=margin,
            confidence=confidence,
            origin=origin,
            is_new_merchant=False,
            category_basis="reviewed_merchant_default",
            matched_description=matched_description,
            evidence=evidence,
            signals=(),
            alternatives=(),
        )

    def _alternatives(self, ranked) -> tuple[MappingRecommendationAlternative, ...]:
        return tuple(
            MappingRecommendationAlternative(
                item.merchant,
                item.category,
                round(item.score, 4),
                item.matched_description,
            )
            for item in ranked
            if item.score > MIN_ALTERNATIVE_SCORE
        )
