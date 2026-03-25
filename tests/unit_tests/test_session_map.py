"""Unit tests for file-backed persistent session mappings."""

from __future__ import annotations

from datetime import UTC, datetime

from copilot_model_provider.storage import FileBackedSessionMap
from tests.session_persistence_helpers import (
    build_session_map_entry,
    managed_scratch_directory,
)


def test_file_backed_session_map_persists_and_lists_entries() -> None:
    """Verify that stored conversation mappings round-trip through JSON storage."""
    with managed_scratch_directory('unit-session-map') as scratch_directory:
        session_map = FileBackedSessionMap(scratch_directory / 'session-map')
        entry = build_session_map_entry()

        persisted_entry = session_map.put(entry)
        loaded_entry = session_map.get(entry.conversation_id)

        assert loaded_entry == persisted_entry
        assert session_map.list_entries() == [persisted_entry]


def test_file_backed_session_map_get_returns_none_for_missing_conversation_id() -> None:
    """Verify that unknown conversation IDs do not create or return placeholder entries."""
    with managed_scratch_directory('unit-session-map-missing') as scratch_directory:
        session_map = FileBackedSessionMap(scratch_directory / 'session-map')

        assert session_map.get('missing-conversation') is None


def test_file_backed_session_map_preserves_original_creation_time_on_update() -> None:
    """Verify that updates touch ``updated_at`` without resetting ``created_at``."""
    with managed_scratch_directory('unit-session-map-update') as scratch_directory:
        session_map = FileBackedSessionMap(scratch_directory / 'session-map')
        original_timestamp = datetime(2024, 12, 31, tzinfo=UTC)
        original_entry = build_session_map_entry(created_at=original_timestamp)
        stored_original = session_map.put(original_entry)

        updated_entry = build_session_map_entry(
            conversation_id=original_entry.conversation_id,
            copilot_session_id='copilot-session-2',
            created_at=datetime(2025, 1, 2, tzinfo=UTC),
        )
        stored_updated = session_map.put(updated_entry)

        assert stored_original.created_at == original_timestamp
        assert stored_updated.created_at == original_timestamp
        assert stored_updated.updated_at > original_timestamp
        assert stored_updated.copilot_session_id == 'copilot-session-2'


def test_file_backed_session_map_delete_removes_entries() -> None:
    """Verify that deleting an entry removes it from future reads and listings."""
    with managed_scratch_directory('unit-session-map-delete') as scratch_directory:
        session_map = FileBackedSessionMap(scratch_directory / 'session-map')
        entry = session_map.put(build_session_map_entry())

        deleted = session_map.delete(entry.conversation_id)

        assert deleted is True
        assert session_map.get(entry.conversation_id) is None
        assert session_map.list_entries() == []
