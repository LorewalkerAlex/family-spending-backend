from family_spending_backend.domain.mapping import MappingCatalog
from family_spending_backend.domain.recommendation import MappingRecommendationEngine


def catalog() -> MappingCatalog:
    return MappingCatalog(
        {
            "支付宝-瑞幸咖啡上海静安店": "瑞幸咖啡",
            "京东支付-瑞幸咖啡杭州西湖店": "瑞幸咖啡",
            "支付宝-迪卡侬上海南丰城店": "迪卡侬",
            "财付通-迪卡侬杭州金沙店": "迪卡侬",
            "支付宝-盒马鲜生上海店": "盒马",
        },
        {
            "瑞幸咖啡": "餐饮美食",
            "迪卡侬": "体育运动",
            "盒马": "日常采购",
        },
        frozenset({"餐饮美食", "体育运动", "日常采购"}),
    )


def test_channel_wrapper_does_not_change_unique_normalized_match() -> None:
    engine = MappingRecommendationEngine(catalog())
    recommendation = engine.recommend("财付通-瑞幸咖啡上海静安店")
    assert recommendation.merchant == "瑞幸咖啡"
    assert recommendation.category == "餐饮美食"
    assert recommendation.origin == "normalized_history"
    assert recommendation.confidence == "strong"
    assert recommendation.matched_description == "支付宝-瑞幸咖啡上海静安店"


def test_ranked_history_exposes_margin_evidence_and_structured_alternatives() -> None:
    engine = MappingRecommendationEngine(catalog())
    recommendation = engine.recommend("云闪付-迪卡侬北京新门店")
    assert recommendation.merchant == "迪卡侬"
    assert recommendation.category == "体育运动"
    assert recommendation.origin == "history"
    assert 0 <= recommendation.rank_score <= 1
    assert recommendation.score_margin >= 0
    assert recommendation.evidence
    assert all(item.merchant != recommendation.merchant for item in recommendation.alternatives)


def test_unknown_history_drafts_without_creating_a_durable_decision() -> None:
    source = catalog()
    engine = MappingRecommendationEngine(source)
    before = dict(source.description_to_merchant)
    recommendation = engine.recommend("支付宝-某某水果旗舰店")
    assert recommendation.merchant == "某某水果"
    assert recommendation.category == "日常采购"
    assert recommendation.category_basis == "keyword"
    assert recommendation.origin == "draft"
    assert recommendation.is_new_merchant is True
    assert dict(source.description_to_merchant) == before


def test_recommendation_is_deterministic_and_cached_per_engine() -> None:
    engine = MappingRecommendationEngine(catalog())
    first = engine.recommend("云闪付-迪卡侬北京新门店")
    second = engine.recommend("云闪付-迪卡侬北京新门店")
    assert second is first


def test_close_candidates_are_not_presented_as_strong_without_margin() -> None:
    ambiguous = MappingCatalog(
        {
            "支付宝-ABC商店": "ABC",
            "支付宝-ABD商店": "ABD",
        },
        {"ABC": "日常采购", "ABD": "日常采购"},
        frozenset({"日常采购"}),
    )
    recommendation = MappingRecommendationEngine(ambiguous).recommend("支付宝-ABX商店")
    assert recommendation.confidence != "strong"
    assert recommendation.score_margin < 0.05
