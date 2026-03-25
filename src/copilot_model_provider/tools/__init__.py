"""Tool and MCP registry primitives for the provider runtime."""

from .mcp import MCPRegistry, MCPServerDefinition
from .registry import ToolDefinition, ToolRegistry

__all__ = [
    'MCPRegistry',
    'MCPServerDefinition',
    'ToolDefinition',
    'ToolRegistry',
]
