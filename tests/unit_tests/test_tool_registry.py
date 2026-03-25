"""Unit tests for the provider's tool registry primitives."""

from __future__ import annotations

import pytest
from copilot.types import ToolInvocation, ToolResult

from copilot_model_provider.tools import ToolDefinition, ToolRegistry


def test_tool_registry_preserves_registration_order() -> None:
    """Verify that registered tools are listed in stable insertion order."""
    registry = ToolRegistry()

    search_tool = ToolDefinition(
        name='search-docs',
        description='Search provider documentation.',
        input_schema={'type': 'object'},
    )
    runbook_tool = ToolDefinition(
        name='open-runbook',
        description='Open an operational runbook.',
        input_schema={'type': 'object'},
        permission_mode='require-approval',
    )

    registry.register(search_tool)
    registry.register(runbook_tool)

    assert registry.list_tools() == (search_tool, runbook_tool)
    assert registry.get_tool('search-docs') == search_tool


def test_tool_registry_rejects_duplicate_names() -> None:
    """Verify that duplicate tool registrations raise a descriptive error."""
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name='search-docs',
            description='Search provider documentation.',
            input_schema={'type': 'object'},
        )
    )

    with pytest.raises(ValueError, match='already registered'):
        registry.register(
            ToolDefinition(
                name='search-docs',
                description='Duplicate definition.',
                input_schema={'type': 'object'},
            )
        )


def test_tool_registry_reports_server_approved_tools_only() -> None:
    """Verify that automatic-approval lookups exclude manual-approval tools."""
    registry = ToolRegistry(
        (
            ToolDefinition(
                name='search-docs',
                description='Search provider documentation.',
                input_schema={'type': 'object'},
                permission_mode='server-approved',
            ),
            ToolDefinition(
                name='open-runbook',
                description='Open an operational runbook.',
                input_schema={'type': 'object'},
                permission_mode='require-approval',
            ),
        )
    )

    assert registry.approved_tool_names() == ('search-docs',)


def test_tool_registry_builds_sdk_tools_for_executable_definitions() -> None:
    """Verify that executable tool definitions become SDK ``Tool`` objects."""

    def _handler(invocation: ToolInvocation) -> ToolResult:
        """Return a deterministic tool result for the registry test."""
        return ToolResult(text_result_for_llm=str(invocation.arguments))

    registry = ToolRegistry(
        (
            ToolDefinition(
                name='search-docs',
                description='Search provider documentation.',
                input_schema={'type': 'object'},
                handler=_handler,
            ),
        )
    )

    sdk_tool = registry.sdk_tools()[0]

    assert sdk_tool.name == 'search-docs'
    assert sdk_tool.skip_permission is True
