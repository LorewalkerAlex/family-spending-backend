"""Verified offline ZIP backup and staged restore."""

import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from family_spending_backend.operations.integrity import IntegrityReport, check_integrity
from family_spending_backend.persistence.filesystem import FilesystemLayout, read_manifest
from family_spending_backend.persistence.filesystem.manifest import require_current_schema

BACKUP_FORMAT_VERSION = 1
BACKUP_MANIFEST_NAME = "BACKUP-MANIFEST.json"


class BackupError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class BackupReport:
    archive: Path
    file_count: int
    byte_count: int
    integrity: IntegrityReport


@dataclass(frozen=True, slots=True)
class RestoreReport:
    target_root: Path
    file_count: int
    integrity: IntegrityReport


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _durable_files(root: Path) -> tuple[Path, ...]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if path.is_symlink():
            raise BackupError(f"Symlinks are not allowed in the data root: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if relative.as_posix() == ".backend.lock":
            continue
        if relative.parts and relative.parts[0] == "derived":
            continue
        files.append(path)
    return tuple(sorted(files, key=lambda item: item.relative_to(root).as_posix()))


def create_backup(
    data_root: Path,
    archive: Path,
    *,
    parser_version: str,
) -> BackupReport:
    root = data_root.resolve()
    destination = archive.resolve()
    layout = FilesystemLayout(root)
    require_current_schema(read_manifest(layout))
    integrity = check_integrity(root, parser_version=parser_version)
    if destination.exists():
        raise BackupError(f"Backup destination already exists: {destination}")
    try:
        destination.relative_to(root)
    except ValueError:
        pass
    else:
        raise BackupError("Backup archive must be outside the data root")

    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    entries: dict[str, dict[str, int | str]] = {}
    try:
        with zipfile.ZipFile(
            temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as bundle:
            for path in _durable_files(root):
                relative = path.relative_to(root).as_posix()
                data = path.read_bytes()
                entries[relative] = {"sha256": _digest(data), "size": len(data)}
                bundle.writestr(relative, data)
            manifest = {
                "backup_format_version": BACKUP_FORMAT_VERSION,
                "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                "files": entries,
            }
            bundle.writestr(
                BACKUP_MANIFEST_NAME,
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            )
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return BackupReport(
        destination,
        len(entries),
        sum(int(item["size"]) for item in entries.values()),
        integrity,
    )


def _validated_entries(bundle: zipfile.ZipFile) -> dict[str, bytes]:
    names = bundle.namelist()
    if len(names) != len(set(names)):
        raise BackupError("Backup contains duplicate archive paths")
    if BACKUP_MANIFEST_NAME not in names:
        raise BackupError("Backup manifest is missing")
    try:
        manifest = json.loads(bundle.read(BACKUP_MANIFEST_NAME))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise BackupError("Backup manifest is invalid") from exc
    if (
        not isinstance(manifest, dict)
        or manifest.get("backup_format_version") != BACKUP_FORMAT_VERSION
        or not isinstance(manifest.get("files"), dict)
    ):
        raise BackupError("Backup manifest has unsupported structure")
    declared = manifest["files"]
    actual_names = set(names) - {BACKUP_MANIFEST_NAME}
    if actual_names != set(declared):
        raise BackupError("Backup file list does not match its manifest")
    entries: dict[str, bytes] = {}
    for name in sorted(actual_names):
        pure = PurePosixPath(name)
        if (
            pure.is_absolute()
            or ".." in pure.parts
            or "" in pure.parts
            or "\\" in name
            or ":" in name
            or name.endswith("/")
        ):
            raise BackupError(f"Unsafe backup path: {name!r}")
        data = bundle.read(name)
        metadata = declared[name]
        if (
            not isinstance(metadata, dict)
            or metadata.get("size") != len(data)
            or metadata.get("sha256") != _digest(data)
        ):
            raise BackupError(f"Backup checksum mismatch: {name}")
        entries[name] = data
    return entries


def restore_backup(
    archive: Path,
    target_root: Path,
    *,
    parser_version: str,
) -> RestoreReport:
    source = archive.resolve()
    target = target_root.resolve()
    if not source.is_file():
        raise BackupError(f"Backup archive does not exist: {source}")
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise BackupError("Restore target must not exist or must be empty")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.restore-", dir=target.parent))
    try:
        with zipfile.ZipFile(source, "r") as bundle:
            entries = _validated_entries(bundle)
        for name, data in entries.items():
            output = staging.joinpath(*PurePosixPath(name).parts)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(data)
        integrity = check_integrity(staging, parser_version=parser_version)
        if target.exists():
            target.rmdir()
        os.replace(staging, target)
        return RestoreReport(target, len(entries), integrity)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
