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


def test_classify_request_fields_marks_responses_tool_routing_fields_supported() -> (
    None
):
    """Verify that Responses tool-routing fields reflect current support levels."""
    classified_fields = classify_request_fields(
        surface=ProtocolSurface.OPENAI_RESPONSES,
        payload={
            'model': 'gpt-5.4',
            'input': 'Hello',
            'truncation': 'auto',
            'previous_response_id': 'resp_123',
            'tool_choice': 'required',
            'parallel_tool_calls': True,
            'tools': [],
            'reasoning': {'effort': 'medium'},
        },
    )

    assert classified_fields['model'].handling is FieldHandling.SUPPORTED
    assert classified_fields['input'].handling is FieldHandling.SUPPORTED
    assert classified_fields['truncation'].handling is FieldHandling.ACCEPT_IGNORE
    assert classified_fields['previous_response_id'].handling is FieldHandling.SUPPORTED
    assert classified_fields['tool_choice'].handling is FieldHandling.SUPPORTED
    assert classified_fields['parallel_tool_calls'].handling is FieldHandling.SUPPORTED
    assert classified_fields['tools'].handling is FieldHandling.SUPPORTED
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
        'thinking',
    ]


def test_get_field_compatibility_rule_marks_anthropic_tools_supported() -> None:
    """Verify that Anthropic tool passthrough is classified as supported."""
    rule = get_field_compatibility_rule(
        surface=ProtocolSurface.ANTHROPIC_MESSAGES,
        field_name='tools',
    )

    assert rule.handling is FieldHandling.SUPPORTED
