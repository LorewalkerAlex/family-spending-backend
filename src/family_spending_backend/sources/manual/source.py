"""Manual Evidence source adapter."""

from dataclasses import dataclass
from typing import ClassVar, Protocol

from family_spending_backend.domain.manual import (
    MANUAL_SOURCE_TYPE,
    ManualEvidence,
    manual_evidence_to_source_record,
)
from family_spending_backend.domain.source import SourceRecord


class ManualEvidenceReader(Protocol):
    def load_all(self) -> tuple[ManualEvidence, ...]: ...


@dataclass(frozen=True, slots=True)
class ManualSource:
    evidence_reader: ManualEvidenceReader
    source_type: ClassVar[str] = MANUAL_SOURCE_TYPE

    def load_records(self) -> tuple[SourceRecord, ...]:
        return tuple(
            manual_evidence_to_source_record(evidence)
            for evidence in self.evidence_reader.load_all()
        )
