# ruff: noqa: RUF001
"""Symmetric normalization for bank descriptions and reviewed Mapping keys."""

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

PROMO_PREFIXES = (
    "消费金抵扣-商户红包-",
    "消费金抵扣-招财红包-",
    "消费金抵扣-银联加倍返现-",
    "消费金抵扣-",
    "（特约）",
)
CHANNELS = (
    "云闪付扫码-",
    "掌上生活优惠商户-",
    "中移动和包-",
    "京东支付-",
    "华为支付-",
    "支付宝-",
    "财付通-",
    "云闪付-",
    "扫码-",
)
GENERIC_FRAGMENTS = (
    "股份有限公司",
    "有限责任公司",
    "有限公司",
    "有限公",
    "限公司",
    "公司",
    "京东自营旗舰店",
    "京东自营专区",
    "自营旗舰店",
    "官方旗舰店",
    "旗舰店",
    "专营店",
    "专卖店",
    "京东自营",
    "自营",
    "企业管理",
    "餐饮管理",
    "经营管理",
    "管理",
    "连锁",
    "便利",
    "服务",
    "经营",
    "商贸",
    "贸易",
    "实业",
    "集团",
    "企业",
    "科技发展",
    "网络科技",
    "信息技术",
    "文化传媒",
    "电子商务",
    "科技",
    "发展",
    "信息",
    "技术",
    "网络",
    "文化",
    "传媒",
    "电子",
    "商务",
    "投资",
    "咨询",
    "餐饮",
    "食品",
    "医药",
    "药房",
    "医疗",
    "健康",
    "家居",
    "电器",
    "设备",
    "工程",
    "建材",
    "装修",
    "装饰",
    "物流",
    "供应链",
    "酒店",
    "超市",
    "百货",
    "批发",
    "零售",
    "中心",
    "市场",
    "数码",
    "智能",
    "数据",
    "软件",
    "通信",
    "通讯",
    "教育",
    "培训",
    "服饰",
    "服装",
    "店",
)
_PUNCTUATION = re.compile(r"[\s·・\-—–_/\\|()（）\[\]【】{}、,，.。'\"“”‘’!！?？:：;；~～+*&#@￥$]")


@dataclass(frozen=True, slots=True)
class ParsedDescription:
    raw: str
    promo: tuple[str, ...]
    channel: str | None
    core: str


def parse(description: str) -> ParsedDescription:
    text = description
    promo: list[str] = []
    channel: str | None = None
    progressed = True
    while progressed:
        progressed = False
        if channel is None:
            for token in CHANNELS:
                if text.startswith(token):
                    channel = token.rstrip("-")
                    text = text[len(token) :]
                    progressed = True
                    break
        if progressed:
            continue
        for token in PROMO_PREFIXES:
            if text.startswith(token):
                promo.append(token.rstrip("-") or token)
                text = text[len(token) :]
                progressed = True
                break
    return ParsedDescription(description, tuple(promo), channel, text)


@lru_cache(maxsize=4096)
def fold(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return _PUNCTUATION.sub("", normalized)


@lru_cache(maxsize=4096)
def brand_key(text: str) -> str:
    value = fold(text)
    changed = True
    while changed and value:
        changed = False
        for fragment in sorted(GENERIC_FRAGMENTS, key=len, reverse=True):
            suffix = fold(fragment)
            if suffix and value.endswith(suffix) and len(value) > len(suffix):
                value = value[: -len(suffix)]
                changed = True
                break
    return value


@lru_cache(maxsize=4096)
def is_generic(stem: str) -> bool:
    residue = stem
    for fragment in sorted(GENERIC_FRAGMENTS, key=len, reverse=True):
        residue = residue.replace(fold(fragment), "")
    return len(residue) < 2


@lru_cache(maxsize=16384)
def longest_common_prefix(left: str, right: str) -> int:
    index = 0
    while index < min(len(left), len(right)) and left[index] == right[index]:
        index += 1
    return index
