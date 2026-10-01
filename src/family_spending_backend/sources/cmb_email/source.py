"""CMB email Source adapter backed by immutable evidence and one-pass parsing."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from types import MappingProxyType
from typing import ClassVar, Protocol

from family_spending_backend.domain.source import SourceRecord
from family_spending_backend.sources.cmb_email.cache import CmbParserCache
from family_spending_backend.sources.cmb_email.evidence import CmbEmailEvidence
from family_spending_backend.sources.cmb_email.parser import CMB_SOURCE_TYPE, ParsedCmbEmail


class CmbEmailEvidenceReader(Protocol):
    def load_all(self) -> tuple[CmbEmailEvidence, ...]: ...


@dataclass(frozen=True, slots=True)
class CmbEmailSource:
    evidence_reader: CmbEmailEvidenceReader
    parser_cache: CmbParserCache
    source_type: ClassVar[str] = CMB_SOURCE_TYPE

    def load_parsed(self) -> tuple[tuple[str, ParsedCmbEmail], ...]:
        return tuple(
            (evidence.identity, self.parser_cache.get_or_parse(evidence))
            for evidence in self.evidence_reader.load_all()
        )

    def load_records(self) -> tuple[SourceRecord, ...]:
        return tuple(record for _, parsed in self.load_parsed() for record in parsed.records)

    def load_statement_dates_by_evidence(self) -> Mapping[str, date]:
        return MappingProxyType(
            {identity: parsed.statement_date for identity, parsed in self.load_parsed()}
        )
