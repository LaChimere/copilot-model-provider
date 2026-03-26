"""Shared helpers for session-persistence-focused tests."""

from __future__ import annotations

import shutil
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from copilot_model_provider.storage import SessionMapEntry

if TYPE_CHECKING:
    from collections.abc import Iterator

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRATCH_ROOT = _REPO_ROOT / '.test-scratch'


@contextmanager
def managed_scratch_directory(prefix: str) -> Iterator[Path]:
    """Create and clean up a repository-local scratch directory for a test."""
    _SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
    path = _SCRATCH_ROOT / f'{prefix}-{uuid4().hex}'
    path.mkdir(parents=True, exist_ok=False)
    try:
        yield path
    finally:
        if path.exists():
            shutil.rmtree(path)
        if _SCRATCH_ROOT.exists() and not any(_SCRATCH_ROOT.iterdir()):
            _SCRATCH_ROOT.rmdir()


def build_session_map_entry(
    *,
    conversation_id: str = 'conversation-1',
    copilot_session_id: str = 'copilot-session-1',
    runtime_name: str = 'copilot',
    runtime_model_id: str | None = 'copilot-default',
    auth_subject: str | None = None,
    created_at: datetime | None = None,
) -> SessionMapEntry:
    """Build a deterministic session-map entry for tests."""
    timestamp = created_at or datetime(2025, 1, 1, tzinfo=UTC)
    return SessionMapEntry(
        conversation_id=conversation_id,
        copilot_session_id=copilot_session_id,
        runtime_name=runtime_name,
        runtime_model_id=runtime_model_id,
        auth_subject=auth_subject,
        created_at=timestamp,
        updated_at=timestamp,
    )
