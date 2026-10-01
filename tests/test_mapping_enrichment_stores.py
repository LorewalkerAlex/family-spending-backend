from pathlib import Path

import pytest

from family_spending_backend.domain.enrichment import EnrichmentDecision
from family_spending_backend.domain.mapping import MappingCatalog
from family_spending_backend.persistence.filesystem import (
    EnrichmentDecisionStoreError,
    FilesystemEnrichmentDecisionStore,
    FilesystemLayout,
    FilesystemMappingStore,
    MappingStoreError,
)


def test_mapping_store_round_trip_is_deterministic(tmp_path: Path) -> None:
    layout = FilesystemLayout(tmp_path)
    store = FilesystemMappingStore(layout)
    mappings = MappingCatalog(
        {"z-desc": "B", "a-desc": "A"},
        {"B": "Other", "A": "Food"},
        frozenset({"Other", "Food"}),
    )
    store.replace(mappings)
    assert store.load() == mappings
    assert layout.merchant_mappings.read_text(encoding="utf-8").startswith("A:")
    store.replace(MappingCatalog.empty())
    assert not layout.merchant_mappings.exists()
    assert not layout.category_mappings.exists()


def test_mapping_store_rejects_partial_duplicate_and_duplicate_membership(tmp_path: Path) -> None:
    layout = FilesystemLayout(tmp_path)
    layout.merchant_mappings.parent.mkdir(parents=True)
    layout.merchant_mappings.write_text("A: [one]\n", encoding="utf-8")
    store = FilesystemMappingStore(layout)
    with pytest.raises(MappingStoreError, match="must exist together"):
        store.load()

    layout.category_mappings.write_text("Food: [A]\nFood: [B]\n", encoding="utf-8")
    with pytest.raises(MappingStoreError, match="duplicate key"):
        store.load()

    layout.category_mappings.write_text("Food: [A]\nOther: [A]\n", encoding="utf-8")
    with pytest.raises(MappingStoreError, match="assigned to both"):
        store.load()


def test_enrichment_store_round_trip_is_sparse_and_rejects_materialized_state(
    tmp_path: Path,
) -> None:
    layout = FilesystemLayout(tmp_path)
    store = FilesystemEnrichmentDecisionStore(layout)
    decisions = (
        EnrichmentDecision("txn_1", note="keep"),
        EnrichmentDecision("txn_2", merchant_override="Cafe", category_override="Food"),
    )
    store.replace(decisions)
    assert store.load() == decisions
    text = layout.enrichment_decisions.read_text(encoding="utf-8")
    assert "display_name" not in text
    assert '"note":"keep"' in text

    layout.enrichment_decisions.write_text(
        '{"transaction_id":"txn_1","display_name":"legacy"}\n', encoding="utf-8"
    )
    with pytest.raises(EnrichmentDecisionStoreError, match="fields"):
        store.load()


def test_enrichment_store_rejects_duplicate_ids_and_removes_empty_file(tmp_path: Path) -> None:
    layout = FilesystemLayout(tmp_path)
    store = FilesystemEnrichmentDecisionStore(layout)
    decision = EnrichmentDecision("txn_1", note="keep")
    with pytest.raises(EnrichmentDecisionStoreError, match="Duplicate"):
        store.replace((decision, decision))
    store.replace((decision,))
    store.replace(())
    assert not layout.enrichment_decisions.exists()
