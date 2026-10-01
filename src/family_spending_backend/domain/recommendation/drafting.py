# ruff: noqa: RUF001
"""Conservative fallback drafting for descriptions with no credible history match."""

import re

from family_spending_backend.domain.recommendation.normalization import parse

BRACKET_RE = re.compile(r"[（(【\[][^）)】\]]*[）)】\]]")
LEGAL_TAILS = (
    "股份有限公司",
    "有限责任公司",
    "有限公司",
    "有限公",
    "限公司",
    "分公司",
    "公司",
    "发展",
    "实业",
    "集团",
    "企业管理",
    "餐饮管理",
    "品牌管理",
    "商业管理",
    "管理",
    "商贸",
    "贸易",
    "电子商务",
    "商务",
    "文化传媒",
    "传媒",
    "文化",
    "网络科技",
    "信息技术",
    "网络",
    "电子",
    "科技",
    "在线",
    "投资",
    "咨询",
    "供应链",
    "物流",
    "工程",
    "装饰",
    "装修",
)
PLATFORM_TAILS = (
    "京东自营旗舰店",
    "京东自营专区",
    "自营旗舰店",
    "官方旗舰店",
    "旗舰店",
    "专营店",
    "专卖店",
    "自营专区",
    "自营",
    "平台商户",
    "代金券",
    "京东自营旗",
)
KNOWN_CITIES = (
    "上海",
    "北京",
    "天津",
    "重庆",
    "广州",
    "深圳",
    "杭州",
    "南京",
    "苏州",
    "宁波",
    "无锡",
    "常州",
    "温州",
    "嘉兴",
    "绍兴",
    "金华",
    "台州",
    "湖州",
    "徐州",
    "镇江",
    "扬州",
    "南通",
    "宿迁",
    "合肥",
    "福州",
    "厦门",
    "泉州",
    "南昌",
    "济南",
    "青岛",
    "郑州",
    "武汉",
    "长沙",
    "成都",
    "昆明",
    "西安",
    "沈阳",
    "大连",
    "东莞",
    "佛山",
    "中山",
    "珠海",
    "昆山",
    "义乌",
)
CITY_RE = re.compile(
    r"^(北京市|上海市|天津市|重庆市|[\u4e00-\u9fa5]{2}市|"
    r"[\u4e00-\u9fa5]{2,3}省|[\u4e00-\u9fa5]{2,4}自治区)"
)
BRANCH_SUFFIX_RE = re.compile(
    r"(\d+元|代金券|电子券|提货券|"
    r"[\u4e00-\u9fa5]{2,6}(?:店|广场|商厦|商场|中心|大厦|步行街|印象城)$)"
)
CATEGORY_KEYWORDS = (
    ("炸鸡", "餐饮美食"),
    ("火锅", "餐饮美食"),
    ("餐饮", "餐饮美食"),
    ("烧烤", "餐饮美食"),
    ("小吃", "餐饮美食"),
    ("面馆", "餐饮美食"),
    ("汉堡", "餐饮美食"),
    ("咖啡", "餐饮美食"),
    ("奶茶", "餐饮美食"),
    ("烘焙", "餐饮美食"),
    ("菜馆", "餐饮美食"),
    ("酒家", "餐饮美食"),
    ("便利", "日常采购"),
    ("超市", "日常采购"),
    ("生鲜", "日常采购"),
    ("菜场", "日常采购"),
    ("水果", "日常采购"),
    ("药房", "医疗健康"),
    ("医疗", "医疗健康"),
    ("医学", "医疗健康"),
    ("医院", "医疗健康"),
    ("口腔", "医疗健康"),
    ("图书", "图书阅读"),
    ("书店", "图书阅读"),
    ("停车", "交通出行"),
    ("高速", "交通出行"),
    ("出行", "交通出行"),
    ("打车", "交通出行"),
    ("地铁", "交通出行"),
    ("铁路", "交通出行"),
    ("航空", "交通出行"),
    ("加油", "交通出行"),
    ("酒店", "旅行住宿"),
    ("住宿", "旅行住宿"),
    ("民宿", "旅行住宿"),
    ("旅行", "旅行住宿"),
    ("影院", "休闲娱乐"),
    ("电影", "休闲娱乐"),
    ("游戏", "电子游戏"),
    ("服饰", "服饰美容"),
    ("服装", "服饰美容"),
    ("美容", "服饰美容"),
    ("健身", "体育运动"),
    ("体育", "体育运动"),
    ("运动", "体育运动"),
    ("家居", "家居家电"),
    ("家具", "家居家电"),
    ("电器", "家居家电"),
    ("五金", "家居家电"),
    ("电信", "生活缴费"),
    ("移动", "生活缴费"),
    ("缴费", "生活缴费"),
    ("物业", "住房支出"),
    ("保险", "保险保障"),
)


def learn_region_prefixes(mapping: dict[str, str]) -> tuple[str, ...]:
    support: dict[str, set[str]] = {}
    for raw, merchant in mapping.items():
        core = BRACKET_RE.sub("", parse(raw).core)
        for length in range(2, 5):
            if len(core) > length:
                support.setdefault(core[:length], set()).add(merchant)
    learned = {
        prefix
        for prefix, merchants in support.items()
        if len(merchants) >= 3 and not any(character.isdigit() for character in prefix)
    }
    ordered = sorted(learned, key=len, reverse=True)
    kept: list[str] = []
    for prefix in ordered:
        if not any(other.startswith(prefix) and other != prefix for other in kept):
            kept.append(prefix)
    return tuple(kept)


def clean_merchant_name(raw: str, region_prefixes: tuple[str, ...]) -> str:
    core = parse(raw).core.strip()
    if not core:
        return raw.strip()
    value = BRACKET_RE.sub("", core).strip() or core
    changed = True
    while changed and value:
        changed = False
        for tail in sorted((*PLATFORM_TAILS, *LEGAL_TAILS), key=len, reverse=True):
            if value.endswith(tail) and len(value) - len(tail) >= 2:
                value = value[: -len(tail)]
                changed = True
                break
    value = value.strip("·・-—_ ") or core
    stripped = CITY_RE.sub("", value)
    if len(stripped) >= 2:
        value = stripped
    for region in (*region_prefixes, *KNOWN_CITIES):
        if value.startswith(region) and len(value) - len(region) >= 2:
            value = value[len(region) :]
            break
    stripped = BRANCH_SUFFIX_RE.sub("", value)
    if len(stripped) >= 2:
        value = stripped
    return value.strip() or core


def guess_category(
    name: str,
    raw: str,
    categories: frozenset[str],
) -> tuple[str | None, str | None]:
    haystack = f"{name} {parse(raw).core}"
    best: tuple[int, str, str] | None = None
    for keyword, category in CATEGORY_KEYWORDS:
        if category in categories and keyword in haystack:
            candidate = (len(keyword), category, keyword)
            if best is None or candidate[0] > best[0]:
                best = candidate
    if best is None:
        return None, None
    return best[1], best[2]
