"""Pytest configuration shared by all test suites."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast

if TYPE_CHECKING:
    from collections.abc import Sequence


class _CoverageOptionsLike(Protocol):
    """Typed subset of pytest-cov options mutated by this repository hook."""

    no_cov: bool
    cov_report: dict[str, str | None]
    cov_fail_under: float | int | None


class _CoveragePluginLike(Protocol):
    """Typed subset of the pytest-cov plugin used by the shared test hook."""

    _disabled: bool
    options: _CoverageOptionsLike


_REPO_ROOT = Path(__file__).resolve().parents[1]
_UNIT_TESTS_ROOT = _REPO_ROOT / 'tests' / 'unit_tests'
_CONTRACT_TESTS_ROOT = _REPO_ROOT / 'tests' / 'contract_tests'
_INTEGRATION_TESTS_ROOT = _REPO_ROOT / 'tests' / 'integration_tests'

if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def _is_unit_test_path(*, path: Path) -> bool:
    """Report whether one collected test path lives under ``tests/unit_tests``.

    Args:
        path: Collected filesystem path for one pytest item.

    Returns:
        ``True`` when the path belongs to the unit-test tree, otherwise ``False``.

    """
    try:
        path.resolve().relative_to(_UNIT_TESTS_ROOT.resolve())
    except ValueError:
        return False

    return True


def _is_coverage_test_path(*, path: Path) -> bool:
    """Report whether one collected path should contribute to the coverage gate.

    Args:
        path: Collected filesystem path for one pytest item.

    Returns:
        ``True`` for in-process unit/contract tests and ``False`` for
        container-backed integration tests.

    """
    resolved_path = path.resolve()
    for root in (_UNIT_TESTS_ROOT.resolve(), _CONTRACT_TESTS_ROOT.resolve()):
        try:
            resolved_path.relative_to(root)
        except ValueError:
            continue
        else:
            return True

    return False


def pytest_collection_modifyitems(
    config: Any,
    items: Sequence[Any],
) -> None:
    """Restrict coverage accounting to unit tests while keeping other suites runnable.

    Contract and integration tests should still run under plain ``pytest -q``, but
    the coverage gate in this repository is intended to apply only to
    ``tests/unit_tests``. This hook marks non-unit tests with ``no_cover`` so
    pytest-cov ignores them, and disables coverage reporting entirely when the
    selected test subset contains no unit tests.

    Args:
        config: Active pytest configuration object.
        items: Collected pytest items for the current invocation.

    """
    coverage_items = [
        item for item in items if _is_coverage_test_path(path=Path(str(item.path)))
    ]
    for item in items:
        if _is_coverage_test_path(path=Path(str(item.path))):
            continue

        if _is_unit_test_path(path=Path(str(item.path))):
            continue

        if (
            Path(str(item.path))
            .resolve()
            .is_relative_to(_INTEGRATION_TESTS_ROOT.resolve())
        ):
            item.add_marker('no_cover')

    if coverage_items:
        return

    coverage_plugin = config.pluginmanager.getplugin('_cov')
    if coverage_plugin is None:
        return

    typed_coverage_plugin = cast('_CoveragePluginLike', coverage_plugin)
    typed_coverage_plugin._disabled = True
    typed_coverage_plugin.options.no_cov = True
    typed_coverage_plugin.options.cov_report = {}
    typed_coverage_plugin.options.cov_fail_under = None
