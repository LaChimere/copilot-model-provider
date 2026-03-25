"""Persistent conversation-to-session mapping primitives."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Literal, override

from pydantic import BaseModel, ConfigDict, Field

_SAFE_IDENTIFIER_PATTERN = re.compile(r'[^A-Za-z0-9._-]+')


def utc_now() -> datetime:
    """Return the current UTC timestamp with timezone information attached."""
    return datetime.now(tz=UTC)


def _slugify_identifier(identifier: str) -> str:
    """Collapse arbitrary identifiers into a filesystem-safe display prefix."""
    normalized = _SAFE_IDENTIFIER_PATTERN.sub('-', identifier).strip('-')
    if normalized:
        return normalized[:48]

    return 'conversation'


def build_storage_file_name(conversation_id: str) -> str:
    """Build a stable storage filename for a conversation mapping record."""
    digest = sha256(conversation_id.encode('utf-8')).hexdigest()
    return f'{_slugify_identifier(conversation_id)}-{digest}.json'


class SessionMapEntry(BaseModel):
    """Persisted mapping between an external conversation ID and a Copilot session.

    The provider uses this record to remember which Copilot session should be
    resumed for a given northbound ``conversation_id``. The entry intentionally
    stores only metadata that is safe to serialize locally and replay later.

    """

    model_config = ConfigDict(extra='forbid', frozen=True)

    conversation_id: str = Field(min_length=1)
    copilot_session_id: str = Field(min_length=1)
    runtime_name: str = Field(min_length=1)
    runtime_model_id: str | None = None
    execution_mode: Literal['stateless', 'sessional'] = 'sessional'
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class SessionMap(ABC):
    """Abstract storage contract for conversation-to-session mappings."""

    @abstractmethod
    def get(self, conversation_id: str) -> SessionMapEntry | None:
        """Return the stored mapping for ``conversation_id`` when one exists."""

    @abstractmethod
    def put(self, entry: SessionMapEntry) -> SessionMapEntry:
        """Persist ``entry`` and return the normalized record that was written."""

    @abstractmethod
    def delete(self, conversation_id: str) -> bool:
        """Delete the mapping for ``conversation_id`` and report whether it existed."""

    @abstractmethod
    def list_entries(self) -> list[SessionMapEntry]:
        """Return every stored mapping sorted by conversation identifier."""


class FileBackedSessionMap(SessionMap):
    """Store session mappings as JSON records on local disk.

    The implementation keeps storage local and file-backed so the session branch
    can ship an immediately useful persistence layer without coupling to shared
    configuration or hot-file runtime integration. Later branches can replace
    this class with a different ``SessionMap`` implementation if deployment
    requirements change.

    """

    def __init__(self, root_directory: Path | str) -> None:
        """Initialize the map with the directory that should hold JSON entries."""
        self._root_directory = Path(root_directory)
        self._root_directory.mkdir(parents=True, exist_ok=True)

    @override
    def get(self, conversation_id: str) -> SessionMapEntry | None:
        """Return the stored entry for ``conversation_id`` when present."""
        path = self._entry_path(conversation_id)
        if not path.exists():
            return None

        return SessionMapEntry.model_validate_json(path.read_text(encoding='utf-8'))

    @override
    def put(self, entry: SessionMapEntry) -> SessionMapEntry:
        """Persist ``entry`` atomically and return the normalized stored record."""
        existing_entry = self.get(entry.conversation_id)
        now = utc_now()
        persisted_entry = entry.model_copy(
            update={
                'created_at': existing_entry.created_at
                if existing_entry is not None
                else entry.created_at,
                'updated_at': now,
            }
        )

        path = self._entry_path(entry.conversation_id)
        pending_path = path.with_suffix('.json.pending')
        payload = f'{persisted_entry.model_dump_json(indent=2)}\n'
        pending_path.write_text(payload, encoding='utf-8')
        pending_path.replace(path)
        return persisted_entry

    @override
    def delete(self, conversation_id: str) -> bool:
        """Delete the stored entry for ``conversation_id`` when one exists."""
        path = self._entry_path(conversation_id)
        if not path.exists():
            return False

        path.unlink()
        return True

    @override
    def list_entries(self) -> list[SessionMapEntry]:
        """Return all stored entries sorted by conversation identifier."""
        entries = [
            SessionMapEntry.model_validate_json(path.read_text(encoding='utf-8'))
            for path in self._root_directory.glob('*.json')
        ]
        return sorted(entries, key=lambda entry: entry.conversation_id)

    def _entry_path(self, conversation_id: str) -> Path:
        """Build the storage path for ``conversation_id``."""
        return self._root_directory / build_storage_file_name(conversation_id)
