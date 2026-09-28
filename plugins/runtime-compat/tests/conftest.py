"""Shared fixtures for the runtime-compat assembly tests.

Mirrors the kernel test conftest (same historical env defaults and the same
artifact-presence verdict hook) and additionally isolates the namespaced
migration registration between tests.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

from pacthold.work_core.db import (
    _reset_connection_for_tests,
    _reset_registered_migration_sources_for_tests,
)

# Runtime environments resolve the sandbox provider by name; under pytest the
# plugin is importable through PYTHONPATH but not pip-installed, so the test
# session states the module explicitly (the same variable the gate scripts set).
os.environ.setdefault("AGENT_BOX_SANDBOX_MODULE", "agent_box_sandbox_bwrap")

_PRESENCE_PATH = (Path(__file__).resolve().parents[3]
                  / "scripts/artifact_presence.py")
_SKIPPED_REASONS: list[str] = []


def _presence():
    spec = importlib.util.spec_from_file_location("artifact_presence_118", _PRESENCE_PATH)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def pytest_runtest_logreport(report):
    if report.skipped:
        _SKIPPED_REASONS.append(str(report.longrepr))


def _presence_lines(presence, failures=0):
    classes = {f"skip-{index}": presence.classify_skip(reason)
               for index, reason in enumerate(_SKIPPED_REASONS)}
    return presence.render(classes, failures=failures)


def _counted_failures(terminalreporter) -> int:
    """Everything that means "this run did not pass".

    `failed` is a test that ran and failed. `error` is a collection error or a
    fixture/teardown error - it must count too, or a session that could not even
    collect would report the green verdict (LNX-002 review, item 1).
    """
    stats = terminalreporter.stats
    return len(stats.get("failed", [])) + len(stats.get("error", []))


def pytest_terminal_summary(terminalreporter):
    """Order 118 presence verdict, identical to the kernel gate hook."""
    presence = _presence()
    if presence is None:
        terminalreporter.write_line(
            f"VERDICT=DEGRADED_PRESENCE_REPORT_UNAVAILABLE ({_PRESENCE_PATH})")
        return
    failures = _counted_failures(terminalreporter)
    for line in _presence_lines(presence, failures):
        terminalreporter.write_line(line)
    if os.environ.get("AGENTBOX_STRICT_PRESENCE"):
        terminalreporter.write_line("STRICT_PRESENCE=1 (a non-green VERDICT fails the session)")


def pytest_sessionfinish(session, exitstatus):
    """Strict mode turns "degraded" into a non-zero exit code."""
    presence = _presence()
    if presence is None or not os.environ.get("AGENTBOX_STRICT_PRESENCE"):
        return
    if exitstatus != 0:
        return
    classes = {f"skip-{i}": presence.classify_skip(r) for i, r in enumerate(_SKIPPED_REASONS)}
    verdict = presence.verdict({c for cs in classes.values() for c in cs}, failures=0)
    if not verdict.startswith("GREEN"):
        session.exitstatus = 1


@pytest.fixture
def tmp_agent_box_home(tmp_path, monkeypatch):
    home = tmp_path / "ab-home"
    home.mkdir()
    monkeypatch.setenv("AGENT_BOX_HOME", str(home))
    _reset_connection_for_tests()
    _reset_registered_migration_sources_for_tests()
    yield home
    _reset_connection_for_tests()
    _reset_registered_migration_sources_for_tests()
