from pathlib import Path

import pytest

from family_spending_backend.persistence.filesystem import (
    CmbEmailEvidenceStoreError,
    FilesystemCmbEmailEvidenceStore,
    FilesystemLayout,
)
from family_spending_backend.sources.cmb_email.evidence import CmbEmailEvidence


def test_store_is_content_addressed_and_retry_is_idempotent(tmp_path: Path) -> None:
    layout = FilesystemLayout(tmp_path)
    store = FilesystemCmbEmailEvidenceStore(layout)
    evidence = CmbEmailEvidence(b"raw-eml-bytes")
    assert store.add(evidence) is True
    assert store.add(evidence) is False
    assert store.load_all() == (evidence,)
    assert (layout.cmb_email_evidence / evidence.filename).read_bytes() == evidence.raw_bytes


def test_store_rejects_filename_content_mismatch(tmp_path: Path) -> None:
    layout = FilesystemLayout(tmp_path)
    layout.initialize()
    wrong_name = CmbEmailEvidence(b"name-source").filename
    (layout.cmb_email_evidence / wrong_name).write_bytes(b"different-content")
    with pytest.raises(CmbEmailEvidenceStoreError, match="filename does not match"):
        FilesystemCmbEmailEvidenceStore(layout).load_all()
