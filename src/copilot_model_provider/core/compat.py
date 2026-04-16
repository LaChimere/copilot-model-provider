"""Shared compatibility scaffolding for protocol request surfaces."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from collections.abc import Mapping


class FieldHandling(StrEnum):
    """Classify how the provider treats one northbound protocol field."""

    SUPPORTED = 'supported'
    ACCEPT_IGNORE = 'accept_ignore'
    REJECT = 'reject'


class ProtocolSurface(StrEnum):
    """Identify one public request surface exposed by the provider."""

    OPENAI_CHAT_COMPLETIONS = 'openai_chat_completions'
    OPENAI_RESPONSES = 'openai_responses'
    ANTHROPIC_MESSAGES = 'anthropic_messages'


class FieldCompatibilityRule(BaseModel):
    """Describe the current handling rule for one request field."""

    model_config = ConfigDict(frozen=True)

    handling: FieldHandling
    note: str | None = None


_REJECT_RULE = FieldCompatibilityRule(
    handling=FieldHandling.REJECT,
    note='Unclassified fields are rejected unless a surface explicitly accepts them.',
)

_SURFACE_RULES: dict[ProtocolSurface, dict[str, FieldCompatibilityRule]] = {
    ProtocolSurface.OPENAI_CHAT_COMPLETIONS: {
        'model': FieldCompatibilityRule(handling=FieldHandling.SUPPORTED),
        'messages': FieldCompatibilityRule(handling=FieldHandling.SUPPORTED),
        'stream': FieldCompatibilityRule(handling=FieldHandling.SUPPORTED),
    },
    ProtocolSurface.OPENAI_RESPONSES: {
        'model': FieldCompatibilityRule(handling=FieldHandling.SUPPORTED),
        'input': FieldCompatibilityRule(handling=FieldHandling.SUPPORTED),
        'instructions': FieldCompatibilityRule(handling=FieldHandling.SUPPORTED),
        'stream': FieldCompatibilityRule(handling=FieldHandling.SUPPORTED),
        'store': FieldCompatibilityRule(
            handling=FieldHandling.ACCEPT_IGNORE,
            note='Accepted for compatibility but not persisted by the provider.',
        ),
        'truncation': FieldCompatibilityRule(
            handling=FieldHandling.ACCEPT_IGNORE,
            note='Context truncation policy remains runtime-managed.',
        ),
        'previous_response_id': FieldCompatibilityRule(
            handling=FieldHandling.SUPPORTED,
            note='Supported as provider-side continuation state via response-id to session-id recovery.',
        ),
        'parallel_tool_calls': FieldCompatibilityRule(
            handling=FieldHandling.SUPPORTED,
            note='Preserved as a routing hint for tool-aware sessions; full parallel execution semantics remain runtime-managed.',
        ),
        'tool_choice': FieldCompatibilityRule(
            handling=FieldHandling.SUPPORTED,
            note='Preserved as a routing hint for tool-aware sessions; the provider does not yet guarantee full tool-policy enforcement.',
        ),
        'tools': FieldCompatibilityRule(
            handling=FieldHandling.SUPPORTED,
            note='Supported as client-passthrough tool definitions forwarded into tool-aware runtime sessions.',
        ),
        'include': FieldCompatibilityRule(
            handling=FieldHandling.ACCEPT_IGNORE,
            note='Optional include expansions are not materialized today.',
        ),
        'prompt_cache_key': FieldCompatibilityRule(
            handling=FieldHandling.ACCEPT_IGNORE,
            note='Prompt caching is not implemented in the provider facade.',
        ),
        'reasoning': FieldCompatibilityRule(
            handling=FieldHandling.ACCEPT_IGNORE,
            note='Reasoning controls are preserved only as wire compatibility today.',
        ),
    },
    ProtocolSurface.ANTHROPIC_MESSAGES: {
        'model': FieldCompatibilityRule(handling=FieldHandling.SUPPORTED),
        'messages': FieldCompatibilityRule(handling=FieldHandling.SUPPORTED),
        'system': FieldCompatibilityRule(handling=FieldHandling.SUPPORTED),
        'stream': FieldCompatibilityRule(handling=FieldHandling.SUPPORTED),
        'max_tokens': FieldCompatibilityRule(
            handling=FieldHandling.ACCEPT_IGNORE,
            note='The runtime owns actual token budgeting semantics.',
        ),
        'metadata': FieldCompatibilityRule(
            handling=FieldHandling.ACCEPT_IGNORE,
            note='Metadata is accepted for compatibility but not surfaced northbound.',
        ),
        'tools': FieldCompatibilityRule(
            handling=FieldHandling.SUPPORTED,
            note='Supported as client-passthrough tool definitions forwarded into tool-aware runtime sessions.',
        ),
        'thinking': FieldCompatibilityRule(
            handling=FieldHandling.ACCEPT_IGNORE,
            note='Accepted for compatibility, but current runtime path cannot surface structured thinking blocks.',
        ),
    },
}


def get_field_compatibility_rule(
    *,
    surface: ProtocolSurface,
    field_name: str,
) -> FieldCompatibilityRule:
    """Return the configured compatibility rule for one request field.

    Args:
        surface: Public request surface whose field policy should be inspected.
        field_name: Incoming request field name to classify.

    Returns:
        The explicit rule configured for the surface, or the shared reject rule
        when the field is currently unclassified.

    """
    return _SURFACE_RULES[surface].get(field_name, _REJECT_RULE)


def classify_request_fields(
    *,
    surface: ProtocolSurface,
    payload: Mapping[str, object],
) -> dict[str, FieldCompatibilityRule]:
    """Classify every field present in a request-like payload.

    Args:
        surface: Public request surface whose compatibility rules should apply.
        payload: Request-like mapping whose keys represent incoming field names.

    Returns:
        A dictionary keyed by each field present in ``payload`` with the rule the
        provider currently applies to that field.

    """
    return {
        field_name: get_field_compatibility_rule(
            surface=surface,
            field_name=field_name,
        )
        for field_name in payload
    }


def iter_surface_rules(
    *,
    surface: ProtocolSurface,
) -> tuple[tuple[str, FieldCompatibilityRule], ...]:
    """Return the stable compatibility table for one request surface.

    Args:
        surface: Public request surface whose full rule set should be returned.

    Returns:
        A tuple of ``(field_name, rule)`` pairs in stable insertion order so tests
        can inspect the current compatibility table deterministically.

    """
    return tuple(_SURFACE_RULES[surface].items())
