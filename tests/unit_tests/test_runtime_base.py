"""Unit tests for runtime adapter scaffolding."""

from __future__ import annotations

import pytest

from copilot_model_provider.runtimes.base import ScaffoldRuntimeAdapter


def test_scaffold_runtime_exposes_canonical_name() -> None:
    """Verify that the scaffold adapter reports the expected runtime identifier."""
    adapter = ScaffoldRuntimeAdapter()

    assert adapter.runtime_name == 'copilot'


def test_scaffold_runtime_default_route_is_placeholder() -> None:
    """Verify that the scaffold adapter resolves to the placeholder route."""
    adapter = ScaffoldRuntimeAdapter()

    route = adapter.default_route()

    assert route.runtime == 'copilot'
    assert route.runtime_model_id is None


@pytest.mark.asyncio
async def test_scaffold_runtime_health_reports_unavailable_execution() -> None:
    """Verify that scaffold health is explicit about runtime execution being deferred."""
    adapter = ScaffoldRuntimeAdapter()

    health = await adapter.check_health()

    assert health.runtime == 'copilot'
    assert health.available is False
    assert health.detail == 'Scaffold only; runtime execution is not implemented yet.'
