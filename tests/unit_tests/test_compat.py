"""Unit tests for shared compatibility classification helpers."""

from __future__ import annotations

from copilot_model_provider.core.compat import (
    FieldHandling,
    ProtocolSurface,
    classify_request_fields,
    get_field_compatibility_rule,
    iter_surface_rules,
)


def test_get_field_compatibility_rule_defaults_unknown_fields_to_reject() -> None:
    """Verify that unclassified fields are rejected by default."""
    rule = get_field_compatibility_rule(
        surface=ProtocolSurface.OPENAI_CHAT_COMPLETIONS,
        field_name='temperature',
    )

    assert rule.handling is FieldHandling.REJECT


def test_classify_request_fields_marks_current_responses_optional_fields_ignore() -> (
    None
):
    """Verify that current Responses compatibility-only fields are classified."""
    classified_fields = classify_request_fields(
        surface=ProtocolSurface.OPENAI_RESPONSES,
        payload={
            'model': 'gpt-5.4',
            'input': 'Hello',
            'tools': [],
            'reasoning': {'effort': 'medium'},
        },
    )

    assert classified_fields['model'].handling is FieldHandling.SUPPORTED
    assert classified_fields['input'].handling is FieldHandling.SUPPORTED
    assert classified_fields['tools'].handling is FieldHandling.ACCEPT_IGNORE
    assert classified_fields['reasoning'].handling is FieldHandling.ACCEPT_IGNORE


def test_iter_surface_rules_returns_stable_current_anthropic_fields() -> None:
    """Verify that the Anthropic messages registry exposes the current scaffold."""
    field_names = [
        field_name
        for field_name, _rule in iter_surface_rules(
            surface=ProtocolSurface.ANTHROPIC_MESSAGES
        )
    ]

    assert field_names == [
        'model',
        'messages',
        'system',
        'stream',
        'max_tokens',
        'metadata',
        'tools',
    ]
