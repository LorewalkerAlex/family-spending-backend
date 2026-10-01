"""Deterministic multi-signal ranking over reviewed Mapping descriptions."""

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher

from family_spending_backend.domain.recommendation.normalization import (
    brand_key,
    fold,
    is_generic,
    longest_common_prefix,
    parse,
)

DEFAULT_WEIGHTS = {
    "structure": 0.35,
    "idf": 0.40,
    "sequence": 0.10,
    "jaccard": 0.15,
}
MIN_STEM_LENGTH = 3
MAX_STEM_LENGTH = 12
ASCII_WORD = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> tuple[str, ...]:
    tokens = [match.group(0) for match in ASCII_WORD.finditer(text)]
    for index in range(len(text) - 1):
        pair = text[index : index + 2]
        if not (pair[0].isascii() and pair[1].isascii()):
            tokens.append(pair)
    return tuple(tokens)


def _key_space(description: str) -> str:
    return fold(parse(description).core)


class TfidfSpace:
    def __init__(self, description_to_merchant: dict[str, str]) -> None:
        tokens_by_merchant: dict[str, Counter[str]] = defaultdict(Counter)
        for raw, merchant in description_to_merchant.items():
            tokens_by_merchant[merchant].update(tokenize(_key_space(raw)))
        merchant_count = max(len(tokens_by_merchant), 1)
        document_frequency: Counter[str] = Counter()
        for counter in tokens_by_merchant.values():
            document_frequency.update(counter.keys())
        self._idf = {
            token: math.log((merchant_count + 1) / (count + 1)) + 1.0
            for token, count in document_frequency.items()
        }
        self._vectors = {raw: self._vector(_key_space(raw)) for raw in description_to_merchant}

    def _vector(self, text: str) -> dict[str, float]:
        counter = Counter(tokenize(text))
        vector = {
            token: (1.0 + math.log(count)) * self._idf.get(token, 1.0)
            for token, count in counter.items()
        }
        norm = math.sqrt(sum(value * value for value in vector.values())) or 1.0
        return {token: value / norm for token, value in vector.items()}

    @staticmethod
    def _similarity(left: dict[str, float], right: dict[str, float]) -> float:
        if len(left) > len(right):
            left, right = right, left
        return sum(value * right.get(token, 0.0) for token, value in left.items())

    def scores(self, description: str, *, exclude: str | None = None) -> dict[str, float]:
        vector = self._vector(_key_space(description))
        return {
            raw: self._similarity(vector, other)
            for raw, other in self._vectors.items()
            if raw != exclude
        }


def _substrings(text: str, *, prefix_only: bool) -> set[str]:
    values: set[str] = set()
    starts = (0,) if prefix_only else range(len(text))
    for size in range(MIN_STEM_LENGTH, min(MAX_STEM_LENGTH, len(text)) + 1):
        for start in starts:
            if start + size <= len(text):
                values.add(text[start : start + size])
    return values


def _mine_stems(
    mapping: dict[str, str], *, prefix_only: bool, drop_generic: bool
) -> dict[str, str]:
    cores_by_merchant: dict[str, list[str]] = defaultdict(list)
    for description, merchant in mapping.items():
        cores_by_merchant[merchant].append(brand_key(parse(description).core))
    support: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for merchant, cores in cores_by_merchant.items():
        for core in cores:
            for token in _substrings(core, prefix_only=prefix_only):
                support[token][merchant] += 1
    result: dict[str, str] = {}
    for token, merchants in support.items():
        if len(merchants) != 1:
            continue
        merchant, count = next(iter(merchants.items()))
        if count >= 2 and (not drop_generic or not is_generic(token)):
            result[token] = merchant
    return result


def mine_stems(mapping: dict[str, str]) -> dict[str, str]:
    generic = _mine_stems(mapping, prefix_only=False, drop_generic=True)
    generic.update(_mine_stems(mapping, prefix_only=True, drop_generic=False))
    return generic


@dataclass(frozen=True, slots=True)
class RankedMerchant:
    merchant: str
    category: str | None
    matched_description: str
    score: float
    signals: tuple[tuple[str, float], ...]
    evidence: tuple[str, ...]


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _structural_signal(candidate: str, other: str) -> tuple[float, str]:
    best = 0.0
    note = ""
    if candidate and other:
        if other in candidate or candidate in other:
            overlap = min(len(other), len(candidate))
            coverage = overlap / max(len(other), len(candidate))
            best = 0.50 + 0.50 * coverage
            note = f"normalized core containment ({coverage:.0%})"
        prefix = longest_common_prefix(candidate, other)
        if prefix >= 3:
            score = 0.55 + 0.45 * prefix / max(len(candidate), len(other))
            if score > best:
                best = score
                note = f"shared normalized prefix ({prefix} chars)"
    return best, note


class RankingIndex:
    """Precomputed ranking structures for one immutable Mapping catalog."""

    def __init__(
        self,
        description_to_merchant: dict[str, str],
        merchant_to_category: dict[str, str],
    ) -> None:
        self._mapping = description_to_merchant
        self._categories = merchant_to_category
        self._keys = tuple(sorted(description_to_merchant))
        self._brand = {raw: brand_key(parse(raw).core) for raw in self._keys}
        self._grams = {raw: set(tokenize(_key_space(raw))) for raw in self._keys}
        self._tfidf = TfidfSpace(description_to_merchant)
        self._stems = mine_stems(description_to_merchant)
        self._weight_total = sum(DEFAULT_WEIGHTS.values())

    def rank(self, candidate: str, *, exclude: str | None = None) -> tuple[RankedMerchant, ...]:
        brand = brand_key(parse(candidate).core)
        grams = set(tokenize(_key_space(candidate)))
        idf_scores = self._tfidf.scores(candidate, exclude=exclude)

        # Match stems once per candidate, rather than scanning every stem for every raw key.
        stem_strength: dict[str, tuple[float, str]] = {}
        for stem, merchant in self._stems.items():
            if stem in brand:
                score = 0.75 + min(len(stem), 8) / 40
                previous = stem_strength.get(merchant)
                if previous is None or score > previous[0]:
                    stem_strength[merchant] = (score, f"shared learned brand stem {stem!r}")

        ranked: list[RankedMerchant] = []
        for raw in self._keys:
            if raw == exclude:
                continue
            merchant = self._mapping[raw]
            structure, structure_note = _structural_signal(brand, self._brand[raw])
            learned = stem_strength.get(merchant)
            if learned is not None and learned[0] > structure:
                structure, structure_note = learned
            idf = idf_scores.get(raw, 0.0)
            sequence = 0.0
            if (
                (DEFAULT_WEIGHTS["structure"] * structure > 0.05 or idf > 0.10)
                and brand
                and self._brand[raw]
            ):
                sequence = SequenceMatcher(None, brand, self._brand[raw]).ratio()
            jaccard = _jaccard(grams, self._grams[raw])
            signal_values = {
                "structure": structure,
                "idf": idf,
                "sequence": sequence,
                "jaccard": jaccard,
            }
            score = (
                sum(DEFAULT_WEIGHTS[name] * value for name, value in signal_values.items())
                / self._weight_total
            )
            evidence = tuple(
                item
                for item in (
                    structure_note if structure > 0.01 else "",
                    "IDF-weighted character similarity" if idf > 0.01 else "",
                    "normalized character sequence similarity" if sequence > 0.01 else "",
                )
                if item
            )
            ranked.append(
                RankedMerchant(
                    merchant,
                    self._categories.get(merchant),
                    raw,
                    score,
                    tuple((name, value) for name, value in signal_values.items() if value > 0.01),
                    evidence,
                )
            )
        ranked.sort(key=lambda item: (-item.score, len(item.matched_description)))
        deduplicated: list[RankedMerchant] = []
        seen: set[str] = set()
        for item in ranked:
            if item.merchant not in seen:
                seen.add(item.merchant)
                deduplicated.append(item)
        return tuple(deduplicated)
