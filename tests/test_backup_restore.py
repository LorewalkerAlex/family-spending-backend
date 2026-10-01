import hashlib
import json
import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from family_spending_backend.domain.manual import (
    create_manual_evidence,
    manual_evidence_to_source_record,
)
from family_spending_backend.domain.transaction import SourceLink, build_transaction_id
from family_spending_backend.operations import check_integrity, create_backup, restore_backup
from family_spending_backend.operations.backup import (
    BACKUP_FORMAT_VERSION,
    BACKUP_MANIFEST_NAME,
    BackupError,
)
from family_spending_backend.persistence.filesystem import (
    FilesystemIdentityStore,
    FilesystemLayout,
    FilesystemManualEvidenceStore,
)


def data_fixture(root: Path) -> FilesystemLayout:
    layout = FilesystemLayout(root)
    layout.initialize()
    evidence = create_manual_evidence(
        evidence_id="manual_1",
        transaction_type="expense",
        transaction_date=date(2026, 9, 1),
        amount=Decimal("12.34"),
        description="market",
    )
    FilesystemManualEvidenceStore(layout).replace_all((evidence,))
    record = manual_evidence_to_source_record(evidence)
    FilesystemIdentityStore(layout).replace(
        (SourceLink(build_transaction_id(record), record.id, "authoritative"),)
    )
    derived = layout.root / "derived" / "cache.bin"
    derived.write_bytes(b"rebuildable")
    return layout


def test_backup_restore_round_trip_omits_derived_and_rebuilds_integrity(
    tmp_path: Path,
) -> None:
    source = data_fixture(tmp_path / "source")
    archive = tmp_path / "backup.zip"
    backup = create_backup(source.root, archive, parser_version="test-v1")
    assert backup.file_count >= 3
    assert backup.integrity.transactions == 1

    restored = tmp_path / "restored"
    report = restore_backup(archive, restored, parser_version="test-v1")
    assert report.integrity.transactions == 1
    assert not (restored / "derived" / "cache.bin").exists()
    assert check_integrity(restored, parser_version="test-v1") == report.integrity


def test_restore_rejects_checksum_tampering(tmp_path: Path) -> None:
    source = data_fixture(tmp_path / "source")
    archive = tmp_path / "backup.zip"
    create_backup(source.root, archive, parser_version="test-v1")
    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(archive, "r") as original, zipfile.ZipFile(tampered, "w") as output:
        for name in original.namelist():
            data = original.read(name)
            if name.endswith("records.jsonl"):
                data += b"tamper"
            output.writestr(name, data)
    with pytest.raises(BackupError, match="checksum mismatch"):
        restore_backup(tampered, tmp_path / "target", parser_version="test-v1")


def test_restore_rejects_windows_drive_path(tmp_path: Path) -> None:
    archive = tmp_path / "unsafe.zip"
    unsafe_name = "C:/outside.txt"
    data = b"must not escape"
    manifest = {
        "backup_format_version": BACKUP_FORMAT_VERSION,
        "created_at": "2026-09-30T00:00:00Z",
        "files": {
            unsafe_name: {
                "sha256": hashlib.sha256(data).hexdigest(),
                "size": len(data),
            }
        },
    }
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr(unsafe_name, data)
        bundle.writestr(BACKUP_MANIFEST_NAME, json.dumps(manifest))

    with pytest.raises(BackupError, match="Unsafe backup path"):
        restore_backup(archive, tmp_path / "target", parser_version="test-v1")
    assert not (tmp_path / "outside.txt").exists()
