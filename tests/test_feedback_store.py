import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from family_spending_backend.domain.feedback import FeedbackContext, FeedbackItem
from family_spending_backend.persistence.filesystem import (
    FeedbackStoreError,
    FilesystemFeedbackStore,
    FilesystemLayout,
)


def test_feedback_store_round_trip_and_strict_schema(tmp_path: Path) -> None:
    layout = FilesystemLayout(tmp_path)
    store = FilesystemFeedbackStore(layout)
    item = FeedbackItem(
        "feedback_1",
        datetime(2026, 8, 16, 1, 2, 3, tzinfo=UTC),
        "open",
        "Needs polish",
        FeedbackContext(runtime="android", page="overview"),
    )
    store.replace((item,))
    assert store.load() == (item,)
    raw = json.loads(layout.feedback.read_text(encoding="utf-8"))
    raw["unexpected"] = True
    layout.feedback.write_text(json.dumps(raw) + "\n", encoding="utf-8")
    with pytest.raises(FeedbackStoreError, match="fields"):
        store.load()
