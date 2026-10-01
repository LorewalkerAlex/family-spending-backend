"""Process-local parser cache keyed by evidence content and parser version."""

from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock

from family_spending_backend.sources.cmb_email.evidence import CmbEmailEvidence
from family_spending_backend.sources.cmb_email.parser import ParsedCmbEmail, parse_cmb_email


@dataclass(frozen=True, slots=True)
class ParserCacheStats:
    hits: int
    misses: int


class CmbParserCache:
    def __init__(
        self,
        parser_version: str,
        *,
        parser: Callable[[CmbEmailEvidence], ParsedCmbEmail] = parse_cmb_email,
    ) -> None:
        if not parser_version.strip():
            raise ValueError("parser_version must not be blank")
        self._parser_version = parser_version
        self._parser = parser
        self._entries: dict[tuple[str, str], ParsedCmbEmail] = {}
        self._hits = 0
        self._misses = 0
        self._lock = RLock()

    def get_or_parse(self, evidence: CmbEmailEvidence) -> ParsedCmbEmail:
        key = (evidence.digest, self._parser_version)
        with self._lock:
            cached = self._entries.get(key)
            if cached is not None:
                self._hits += 1
                return cached
            parsed = self._parser(evidence)
            self._entries[key] = parsed
            self._misses += 1
            return parsed

    def parser_cache_stats(self) -> ParserCacheStats:
        with self._lock:
            return ParserCacheStats(self._hits, self._misses)

    def parser_cache_counts(self) -> tuple[int, int]:
        stats = self.parser_cache_stats()
        return stats.hits, stats.misses
