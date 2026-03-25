"""Integration checks for persistent session resume storage behavior."""

from __future__ import annotations

from copilot_model_provider.storage import FileBackedSessionMap
from tests.session_persistence_helpers import (
    build_session_map_entry,
    managed_scratch_directory,
)


def test_session_resume_storage_survives_map_reconstruction() -> None:
    """Verify that a persisted conversation mapping can be loaded after restart."""
    with managed_scratch_directory('integration-session-resume') as scratch_directory:
        initial_map = FileBackedSessionMap(scratch_directory / 'session-map')
        initial_entry = initial_map.put(
            build_session_map_entry(
                conversation_id='conversation-resume',
                copilot_session_id='copilot-session-resume',
            )
        )

        restarted_map = FileBackedSessionMap(scratch_directory / 'session-map')
        resumed_entry = restarted_map.get('conversation-resume')

        assert resumed_entry == initial_entry


def test_session_resume_storage_keeps_same_copilot_session_id_across_follow_ups() -> (
    None
):
    """Verify that follow-up turns can refresh metadata without changing session identity."""
    with managed_scratch_directory(
        'integration-session-follow-up'
    ) as scratch_directory:
        session_map = FileBackedSessionMap(scratch_directory / 'session-map')
        initial_entry = session_map.put(
            build_session_map_entry(
                conversation_id='conversation-follow-up',
                copilot_session_id='copilot-session-stable',
                runtime_model_id='copilot-initial',
            )
        )

        refreshed_entry = session_map.put(
            build_session_map_entry(
                conversation_id='conversation-follow-up',
                copilot_session_id='copilot-session-stable',
                runtime_model_id='copilot-follow-up',
            )
        )

        assert refreshed_entry.copilot_session_id == initial_entry.copilot_session_id
        assert refreshed_entry.runtime_model_id == 'copilot-follow-up'
        assert refreshed_entry.created_at == initial_entry.created_at
        assert refreshed_entry.updated_at >= initial_entry.updated_at
