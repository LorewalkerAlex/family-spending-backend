"""Fail-closed storage schema manifest."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from family_spending_backend.persistence.filesystem.atomic import atomic_write_text
from family_spending_backend.persistence.filesystem.layout import FilesystemLayout

CURRENT_STORAGE_SCHEMA_VERSION = 1


class StorageManifestError(RuntimeError):
    pass


class StorageMigrationRequiredError(StorageManifestError):
    pass


class UnsupportedStorageSchemaError(StorageManifestError):
    pass


@dataclass(frozen=True, slots=True)
class StorageManifest:
    storage_schema_version: int
    created_at: datetime
    last_migrated_at: datetime | None = None


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise StorageManifestError("manifest timestamps must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_timestamp(raw: object, field: str) -> datetime:
    if not isinstance(raw, str):
        raise StorageManifestError(f"manifest {field} must be an ISO timestamp string")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise StorageManifestError(f"manifest {field} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise StorageManifestError(f"manifest {field} must include a timezone")
    return parsed.astimezone(UTC)


def write_manifest(layout: FilesystemLayout, manifest: StorageManifest) -> None:
    payload = {
        "storage_schema_version": manifest.storage_schema_version,
        "created_at": _timestamp(manifest.created_at),
        "last_migrated_at": (
            _timestamp(manifest.last_migrated_at) if manifest.last_migrated_at is not None else None
        ),
    }
    atomic_write_text(
        layout.manifest,
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
    )


def read_manifest(layout: FilesystemLayout) -> StorageManifest:
    if not layout.manifest.is_file():
        raise StorageManifestError(f"Storage manifest is missing: {layout.manifest}")
    try:
        raw = json.loads(layout.manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StorageManifestError(f"Unable to read storage manifest: {exc}") from exc
    if not isinstance(raw, dict) or set(raw) != {
        "storage_schema_version",
        "created_at",
        "last_migrated_at",
    }:
        raise StorageManifestError("Storage manifest has invalid fields")
    version = raw["storage_schema_version"]
    if isinstance(version, bool) or not isinstance(version, int) or version <= 0:
        raise StorageManifestError("storage_schema_version must be a positive integer")
    return StorageManifest(
        version,
        _parse_timestamp(raw["created_at"], "created_at"),
        (
            None
            if raw["last_migrated_at"] is None
            else _parse_timestamp(raw["last_migrated_at"], "last_migrated_at")
        ),
    )


def require_current_schema(manifest: StorageManifest) -> None:
    if manifest.storage_schema_version < CURRENT_STORAGE_SCHEMA_VERSION:
        raise StorageMigrationRequiredError(
            "Storage schema is older; run the explicit storage migration"
        )
    if manifest.storage_schema_version > CURRENT_STORAGE_SCHEMA_VERSION:
        raise UnsupportedStorageSchemaError(
            "Storage schema is newer; refusing to start with older code"
        )


def initialize_storage(layout: FilesystemLayout, *, now: datetime | None = None) -> StorageManifest:
    if layout.manifest.exists():
        manifest = read_manifest(layout)
        require_current_schema(manifest)
        for directory in layout.required_directories:
            directory.mkdir(parents=True, exist_ok=True)
        return manifest
    existing = tuple(layout.root.iterdir()) if layout.root.exists() else ()
    if any(path.name != ".backend.lock" for path in existing):
        raise StorageManifestError(
            "Refusing to initialize a non-empty data root without manifest.json"
        )
    created_at = now or datetime.now(UTC)
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise StorageManifestError("manifest timestamps must be timezone-aware")
    manifest = StorageManifest(CURRENT_STORAGE_SCHEMA_VERSION, created_at.astimezone(UTC))
    write_manifest(layout, manifest)
    for directory in layout.required_directories:
        directory.mkdir(parents=True, exist_ok=True)
    return manifest
