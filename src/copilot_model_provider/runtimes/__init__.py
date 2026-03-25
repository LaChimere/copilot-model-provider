"""Runtime adapter contracts for the provider scaffold."""

from .base import RuntimeAdapter, ScaffoldRuntimeAdapter
from .copilot import CopilotRuntimeAdapter

__all__ = ['CopilotRuntimeAdapter', 'RuntimeAdapter', 'ScaffoldRuntimeAdapter']
