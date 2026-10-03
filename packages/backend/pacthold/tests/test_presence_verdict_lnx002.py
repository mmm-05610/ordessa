"""LNX-002 — the presence verdict cannot contradict the run it describes.

I's `control/LNX-002-review.md` item 1: a run with three failures and zero skips
still printed `VERDICT=GREEN_NO_SKIPS`. `artifact_presence.verdict()` was always
right (`failures` wins); `tests/conftest.py:pytest_terminal_summary` computed the
count and then dropped it on the way into `render`. A summary line that can
disagree with the exit code is worse than no summary line, because it is the line
people quote.

These cases drive the real hook with a fake reporter, which is where the bug was.
The full-session path is exercised too: a subprocess run over a deliberately
failing and a deliberately uncollectable file, asserting the printed verdict and
the exit code agree.
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

TREE = Path(__file__).resolve().parents[4]
ROOT = Path(__file__).resolve().parents[1]  # the pacthold package root
CONFTEST = ROOT / "tests/conftest.py"
PRESENCE = TREE / "scripts/artifact_presence.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def presence():
    return _load("presence_lnx002", PRESENCE)


@pytest.fixture
def conftest():
    # The hook lives in the test suite's own conftest; load it by path so this
    # file does not depend on `tests/` being importable as a package.
    return _load("conftest_lnx002", CONFTEST)


class _Reporter:
    """Just enough of pytest's terminal reporter for the summary hook."""

    def __init__(self, failed=0, error=0):
        self.stats = {"failed": [None] * failed, "error": [None] * error}
        self.lines: list[str] = []

    def write_line(self, line):
        self.lines.append(line)

    def verdict(self):
        return next(line for line in self.lines if line.startswith("VERDICT="))


# -- the unit the hook must reach ----------------------------------------

def test_verdict_is_failed_whenever_there_is_a_failure(presence):
    assert presence.verdict(set(), 1) == "FAILED"
    assert presence.verdict({presence.ARTIFACT}, 3) == "FAILED"


def test_render_carries_the_failure_count_into_the_verdict(presence):
    lines = presence.render({}, failures=3)
    assert "VERDICT=FAILED" in lines
    assert "VERDICT=GREEN_NO_SKIPS" not in lines


def test_render_without_failures_and_without_skips_is_still_green(presence):
    # The control: the fix must not make a genuinely green run red.
    assert "VERDICT=GREEN_NO_SKIPS" in presence.render({}, failures=0)


# -- the regression: the hook used to drop the count ---------------------

def test_the_summary_hook_reports_failed_not_green(presence, conftest, monkeypatch):
    reporter = _Reporter(failed=3)
    monkeypatch.setattr(conftest, "_SKIPPED_REASONS", [], raising=False)
    conftest.pytest_terminal_summary(reporter)

    assert reporter.verdict() == "VERDICT=FAILED", reporter.lines


def test_the_summary_hook_counts_collection_errors_as_failures(presence, conftest, monkeypatch):
    """A session that could not collect must not report the green verdict."""
    reporter = _Reporter(error=1)
    monkeypatch.setattr(conftest, "_SKIPPED_REASONS", [], raising=False)
    conftest.pytest_terminal_summary(reporter)

    assert reporter.verdict() == "VERDICT=FAILED", reporter.lines


def test_the_summary_hook_still_reports_green_for_a_clean_run(presence, conftest, monkeypatch):
    reporter = _Reporter()
    monkeypatch.setattr(conftest, "_SKIPPED_REASONS", [], raising=False)
    conftest.pytest_terminal_summary(reporter)

    assert reporter.verdict() == "VERDICT=GREEN_NO_SKIPS", reporter.lines


# -- end to end: the printed verdict and the exit code agree -------------

def _run_pytest(tmp_path: Path, body: str):
    target = tmp_path / "test_probe_lnx002.py"
    target.write_text(textwrap.dedent(body), encoding="utf-8")
    # The probe lives in a temp dir, so the suite's conftest would not apply by
    # path. Load it explicitly as a plugin (`-p conftest`, with `tests/` on
    # PYTHONPATH) so the *real* hook runs - not a copy of it.
    import os

    env = {
        **os.environ,
        "AGENTBOX_STRICT_PRESENCE": "1",
        "PYTHONPATH": os.pathsep.join(
            [str(ROOT / "tests"), str(ROOT / "src"), str(TREE / "plugins" / "harness" / "src"), os.environ.get("PYTHONPATH", "")]
        ).strip(os.pathsep),
    }
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         "-p", "conftest", "--rootdir", str(ROOT), str(target)],
        capture_output=True, text=True, cwd=str(ROOT), timeout=300, env=env,
    )


@pytest.mark.parametrize("body,expected_exit", [
    ("def test_it_fails():\n    assert False\n", "fail"),
    ("import definitely_not_a_module_lnx002\n", "error"),
])
def test_printed_verdict_and_exit_code_never_contradict(tmp_path, body, expected_exit):
    result = _run_pytest(tmp_path, body)
    verdict = next((line for line in result.stdout.splitlines()
                    if line.startswith("VERDICT=")), None)
    assert verdict is not None, result.stdout
    assert verdict == "VERDICT=FAILED", (expected_exit, verdict, result.stdout)
    assert result.returncode != 0, (expected_exit, result.returncode, result.stdout)
