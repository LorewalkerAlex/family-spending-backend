"""Immutable content-addressed CMB EML persistence."""

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from family_spending_backend.persistence.filesystem.layout import FilesystemLayout
from family_spending_backend.sources.cmb_email.evidence import CmbEmailEvidence


class CmbEmailEvidenceStoreError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class FilesystemCmbEmailEvidenceStore:
    layout: FilesystemLayout

    def add(self, evidence: CmbEmailEvidence) -> bool:
        directory = self.layout.cmb_email_evidence
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / evidence.filename
        if target.exists():
            try:
                existing = target.read_bytes()
            except OSError as exc:
                raise CmbEmailEvidenceStoreError(f"Unable to read {target}: {exc}") from exc
            if existing != evidence.raw_bytes:
                raise CmbEmailEvidenceStoreError(
                    f"CMB evidence content-address collision or corruption at {target}"
                )
            return False

        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=directory,
                prefix=f".{evidence.digest}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                handle.write(evidence.raw_bytes)
                handle.flush()
                os.fsync(handle.fileno())
                temporary = Path(handle.name)
            if target.exists():
                if target.read_bytes() != evidence.raw_bytes:
                    raise CmbEmailEvidenceStoreError(
                        f"CMB evidence content-address collision or corruption at {target}"
                    )
                return False
            os.replace(temporary, target)
            temporary = None
            return True
        except OSError as exc:
            raise CmbEmailEvidenceStoreError(f"Unable to persist {target}: {exc}") from exc
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def load_all(self) -> tuple[CmbEmailEvidence, ...]:
        directory = self.layout.cmb_email_evidence
        if not directory.exists():
            return ()
        items: list[CmbEmailEvidence] = []
        for path in sorted(directory.glob("*.eml"), key=lambda item: item.name):
            try:
                evidence = CmbEmailEvidence(path.read_bytes())
            except (OSError, ValueError) as exc:
                raise CmbEmailEvidenceStoreError(f"Unable to load {path}: {exc}") from exc
            if path.name != evidence.filename:
                raise CmbEmailEvidenceStoreError(
                    f"CMB evidence filename does not match content hash: {path}"
                )
            items.append(evidence)
        return tuple(items)
