"""One-time importer that treats a legacy canonical data root as strictly read-only."""

import os
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from family_spending_backend.migration.parity import ParityReport, verify_parity
from family_spending_backend.persistence.filesystem import (
    FilesystemCmbEmailEvidenceStore,
    FilesystemEnrichmentDecisionStore,
    FilesystemFeedbackStore,
    FilesystemIdentityStore,
    FilesystemLayout,
    FilesystemManualEvidenceStore,
    FilesystemMappingStore,
    FilesystemScheduleStore,
    StorageManifest,
    initialize_storage,
    read_manifest,
)
from family_spending_backend.persistence.filesystem.manifest import (
    require_current_schema,
    write_manifest,
)


class LegacyImportError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ImportReport:
    target_root: Path
    evidence_count: int
    parity: ParityReport


def _validate_paths(source: Path, target: Path) -> tuple[Path, Path]:
    source = source.resolve()
    target = target.resolve()
    if source == target:
        raise LegacyImportError("Source and target data roots must be different")
    if not source.is_dir():
        raise LegacyImportError(f"Source data root does not exist: {source}")
    if target.is_relative_to(source):
        raise LegacyImportError("Target data root must be outside the read-only source root")
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise LegacyImportError("Target data root must not exist or must be empty")
    return source, target


def import_legacy_copy(
    source_root: Path, target_root: Path, *, parser_version: str
) -> ImportReport:
    source_root, target_root = _validate_paths(source_root, target_root)
    source = FilesystemLayout(source_root)
    source_manifest = read_manifest(source)
    require_current_schema(source_manifest)

    target_root.parent.mkdir(parents=True, exist_ok=True)
    staging_path = Path(
        tempfile.mkdtemp(prefix=f".{target_root.name}.import-", dir=target_root.parent)
    )
    staging = FilesystemLayout(staging_path)
    try:
        initialize_storage(staging)
        source_cmb = FilesystemCmbEmailEvidenceStore(source).load_all()
        staging_cmb = FilesystemCmbEmailEvidenceStore(staging)
        for evidence in source_cmb:
            staging_cmb.add(evidence)
        FilesystemManualEvidenceStore(staging).replace_all(
            FilesystemManualEvidenceStore(source).load_all()
        )
        FilesystemIdentityStore(staging).replace(FilesystemIdentityStore(source).load())
        FilesystemMappingStore(staging).replace(FilesystemMappingStore(source).load())
        FilesystemEnrichmentDecisionStore(staging).replace(
            FilesystemEnrichmentDecisionStore(source).load()
        )
        source_schedule = FilesystemScheduleStore(source)
        staging_schedule = FilesystemScheduleStore(staging)
        staging_schedule.replace_rules(source_schedule.load_rules())
        staging_schedule.replace_execution(source_schedule.load_execution())
        FilesystemFeedbackStore(staging).replace(FilesystemFeedbackStore(source).load())
        write_manifest(
            staging,
            StorageManifest(
                source_manifest.storage_schema_version,
                source_manifest.created_at,
                datetime.now(UTC),
            ),
        )
        parity = verify_parity(source_root, staging_path, parser_version=parser_version)
        if target_root.exists():
            target_root.rmdir()
        os.replace(staging_path, target_root)
        return ImportReport(target_root, len(source_cmb), parity)
    except Exception:
        shutil.rmtree(staging_path, ignore_errors=True)
        raise
