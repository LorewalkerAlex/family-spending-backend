"""Acquire raw mailbox messages as immutable CMB Evidence."""

from dataclasses import dataclass
from typing import ClassVar, Protocol

from family_spending_backend.application.ports.source import SourceAcquisitionResult
from family_spending_backend.sources.cmb_email.evidence import CmbEmailEvidence
from family_spending_backend.sources.cmb_email.parser import CMB_SOURCE_TYPE


class CmbEmailConnector(Protocol):
    def fetch_raw_messages(self) -> tuple[bytes, ...]: ...


class CmbEmailEvidenceWriter(Protocol):
    def add(self, evidence: CmbEmailEvidence) -> bool: ...


@dataclass(frozen=True, slots=True)
class CmbEmailAcquirer:
    connector: CmbEmailConnector
    evidence_writer: CmbEmailEvidenceWriter
    source_type: ClassVar[str] = CMB_SOURCE_TYPE

    def acquire(self) -> SourceAcquisitionResult:
        messages = self.connector.fetch_raw_messages()
        added = sum(self.evidence_writer.add(CmbEmailEvidence(raw_bytes)) for raw_bytes in messages)
        return SourceAcquisitionResult(self.source_type, len(messages), added)
