"""Filesystem persistence primitives."""

from family_spending_backend.persistence.filesystem.cmb_email_evidence_store import (
    CmbEmailEvidenceStoreError,
    FilesystemCmbEmailEvidenceStore,
)
from family_spending_backend.persistence.filesystem.enrichment_store import (
    EnrichmentDecisionStoreError,
    FilesystemEnrichmentDecisionStore,
)
from family_spending_backend.persistence.filesystem.feedback_store import (
    FeedbackStoreError,
    FilesystemFeedbackStore,
)
from family_spending_backend.persistence.filesystem.identity_store import (
    FilesystemIdentityStore,
    IdentityStoreError,
)
from family_spending_backend.persistence.filesystem.layout import FilesystemLayout
from family_spending_backend.persistence.filesystem.manifest import (
    CURRENT_STORAGE_SCHEMA_VERSION,
    StorageManifest,
    StorageManifestError,
    StorageMigrationRequiredError,
    UnsupportedStorageSchemaError,
    initialize_storage,
    read_manifest,
)
from family_spending_backend.persistence.filesystem.manual_evidence_store import (
    FilesystemManualEvidenceStore,
    ManualEvidenceStoreError,
)
from family_spending_backend.persistence.filesystem.mapping_store import (
    FilesystemMappingStore,
    MappingStoreError,
)
from family_spending_backend.persistence.filesystem.schedule_store import (
    FilesystemScheduleStore,
    ScheduleStoreError,
)
from family_spending_backend.persistence.filesystem.unit_of_work import (
    FileUnitOfWork,
    FileUnitOfWorkError,
    FileUnitOfWorkRollbackError,
)

__all__ = [
    "CURRENT_STORAGE_SCHEMA_VERSION",
    "CmbEmailEvidenceStoreError",
    "EnrichmentDecisionStoreError",
    "FeedbackStoreError",
    "FileUnitOfWork",
    "FileUnitOfWorkError",
    "FileUnitOfWorkRollbackError",
    "FilesystemCmbEmailEvidenceStore",
    "FilesystemEnrichmentDecisionStore",
    "FilesystemFeedbackStore",
    "FilesystemIdentityStore",
    "FilesystemLayout",
    "FilesystemManualEvidenceStore",
    "FilesystemMappingStore",
    "FilesystemScheduleStore",
    "IdentityStoreError",
    "ManualEvidenceStoreError",
    "MappingStoreError",
    "ScheduleStoreError",
    "StorageManifest",
    "StorageManifestError",
    "StorageMigrationRequiredError",
    "UnsupportedStorageSchemaError",
    "initialize_storage",
    "read_manifest",
]
