"""Runtime adapter contracts for the provider scaffold."""

from .base import RuntimeAdapter
from .copilot import CopilotRuntimeAdapter

__all__ = ['CopilotRuntimeAdapter', 'RuntimeAdapter']
