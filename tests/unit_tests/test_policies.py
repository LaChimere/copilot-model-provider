"""Unit tests for tool-permission policy evaluation."""

from __future__ import annotations

from copilot_model_provider.core.policies import PolicyEngine, ToolPermissionPolicy
from copilot_model_provider.tools import (
    MCPRegistry,
    MCPServerDefinition,
    ToolDefinition,
    ToolRegistry,
)


def test_policy_engine_allows_registered_server_approved_tools() -> None:
    """Verify that the default policy approves registered server-approved tools."""
    registry = ToolRegistry(
        (
            ToolDefinition(
                name='search-docs',
                description='Search provider documentation.',
                input_schema={'type': 'object'},
                permission_mode='server-approved',
            ),
        )
    )
    engine = PolicyEngine(tool_registry=registry)

    decision = engine.evaluate_tool_permission('search-docs')

    assert decision.allowed is True
    assert 'server-approved' in decision.reason


def test_policy_engine_requires_explicit_allow_for_manual_tools() -> None:
    """Verify that manual-approval tools stay denied without an allow rule."""
    registry = ToolRegistry(
        (
            ToolDefinition(
                name='open-runbook',
                description='Open an operational runbook.',
                input_schema={'type': 'object'},
                permission_mode='require-approval',
            ),
        )
    )
    engine = PolicyEngine(tool_registry=registry)

    decision = engine.evaluate_tool_permission('open-runbook')

    assert decision.allowed is False
    assert 'explicit allow rule' in decision.reason


def test_policy_engine_honors_explicit_allow_and_deny_rules() -> None:
    """Verify that explicit lists override the registry's default policy behavior."""
    registry = ToolRegistry(
        (
            ToolDefinition(
                name='search-docs',
                description='Search provider documentation.',
                input_schema={'type': 'object'},
            ),
        )
    )
    engine = PolicyEngine(
        tool_registry=registry,
        tool_policy=ToolPermissionPolicy(
            allowed_tool_names=frozenset({'open-runbook'}),
            denied_tool_names=frozenset({'search-docs'}),
        ),
    )

    denied = engine.evaluate_tool_permission('search-docs')
    allowed = engine.evaluate_tool_permission('open-runbook')

    assert denied.allowed is False
    assert 'explicitly denied' in denied.reason
    assert allowed.allowed is True
    assert 'explicitly allowed' in allowed.reason


def test_policy_engine_supports_allow_listed_builtin_tools() -> None:
    """Verify that built-in tool approval follows the dedicated built-in policy."""
    engine = PolicyEngine(
        tool_policy=ToolPermissionPolicy(
            builtin_tool_policy='allow-listed',
            allowed_builtin_tool_names=frozenset({'view'}),
        )
    )

    assert engine.can_approve_tool('view', is_builtin=True) is True
    assert engine.can_approve_tool('bash', is_builtin=True) is False


def test_policy_engine_allows_registered_mcp_servers() -> None:
    """Verify that registered MCP mounts are approved by the default policy."""
    engine = PolicyEngine(
        mcp_registry=MCPRegistry(
            (
                MCPServerDefinition(
                    name='docs-api',
                    transport='http',
                    url='http://localhost:8123/mcp',
                ),
            )
        )
    )

    decision = engine.evaluate_mcp_server_permission('docs-api')

    assert decision.allowed is True
    assert 'registered' in decision.reason
