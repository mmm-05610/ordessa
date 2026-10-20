"""Safety checks for the narrow standalone Local Library catalog runner."""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[3]
_RUNNER_PATH = _REPO_ROOT / "tooling/checks/server_product/local_library_catalog_check_runner.py"
_SPEC = importlib.util.spec_from_file_location("local_library_catalog_check_runner", _RUNNER_PATH)
assert _SPEC is not None and _SPEC.loader is not None
runner = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(runner)


def _project_root(tmp_path: Path) -> Path:
    (tmp_path / "catalog/tests").mkdir(parents=True)
    (tmp_path / "catalog/tests/__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "locallibrary").mkdir()
    (tmp_path / "locallibrary/urls.py").write_text("urlpatterns = []\n", encoding="utf-8")
    return tmp_path


def test_settings_are_fixed_and_use_memory_database_and_temporary_paths(tmp_path):
    root = _project_root(tmp_path / "demo")
    scratch = tmp_path / "scratch"
    settings = runner.isolated_django_settings(root, scratch)

    assert settings["ROOT_URLCONF"] == "locallibrary.urls"
    assert settings["DATABASES"]["default"]["ENGINE"] == "django.db.backends.sqlite3"
    assert settings["DATABASES"]["default"]["NAME"] == ":memory:"
    assert settings["DATABASES"]["default"]["TEST"]["NAME"] == ":memory:"
    assert settings["STATIC_ROOT"] == str(scratch / "static")
    assert settings["MEDIA_ROOT"] == str(scratch / "media")
    assert settings["INSTALLED_APPS"][-1] == "catalog.apps.CatalogConfig"
    assert "locallibrary.settings" not in sys.modules


@pytest.mark.parametrize(
    ("target", "uri", "allowed"),
    [
        (":memory:", False, True),
        ("file:memorydb_default?mode=memory&cache=shared", True, True),
        ("file:memorydb_default?mode=memory&cache=private", True, True),
        ("file:memorydb_default?mode=memory&cache=shared", False, False),
        ("/tmp/library.sqlite3", False, False),
        ("file:/tmp/library.sqlite3?mode=ro", True, False),
        ("file:/tmp/library.sqlite3?mode=memory", True, False),
        ("file:memorydb_default?mode=memory&vfs=unix", True, False),
        (b"/tmp/library.sqlite3", False, False),
    ],
)
def test_only_literal_or_named_memory_sqlite_targets_are_allowed(target, uri, allowed):
    assert runner.sqlite_target_is_memory(target, uri=uri) is allowed


def test_audit_guard_rejects_disk_without_recording_the_path():
    guard = runner.SQLiteMemoryGuard()

    with pytest.raises(runner.DiskSQLiteRefused, match="disk SQLite connections are disabled"):
        guard._audit("sqlite3.connect", ("/private/demo.sqlite3",))

    assert guard.denied_connections == 1
    assert guard.allowed_targets == set()
    assert "/private/demo.sqlite3" not in repr(guard.__dict__)


def test_audit_guard_records_only_a_prevalidated_shared_memory_uri():
    guard = runner.SQLiteMemoryGuard()
    target = "file:memorydb_default?mode=memory&cache=shared"
    guard._local.approved_uri = target

    guard._audit("sqlite3.connect", (target,))

    assert guard.allowed_connections == 1
    assert guard.allowed_targets == {"file:<memory>?mode=memory"}
    assert guard.denied_connections == 0


def test_audit_guard_does_not_accept_an_unapproved_memory_looking_uri():
    guard = runner.SQLiteMemoryGuard()

    with pytest.raises(runner.DiskSQLiteRefused):
        guard._audit("sqlite3.connect", ("file:memorydb_default?mode=memory&cache=shared",))

    assert guard.denied_connections == 1


def test_cli_has_only_project_root_and_rejects_arbitrary_test_or_settings_options():
    parser = runner.build_parser()
    parsed = parser.parse_args(["--project-root", "/tmp/catalog-demo"])
    assert parsed.project_root == "/tmp/catalog-demo"

    with pytest.raises(SystemExit):
        parser.parse_args(["--project-root", "/tmp/catalog-demo", "--test-label", "anything"])
    with pytest.raises(SystemExit):
        parser.parse_args(["--project-root", "/tmp/catalog-demo", "--settings", "locallibrary.settings"])
    with pytest.raises(SystemExit):
        parser.parse_args(["--project-root", "/tmp/catalog-demo", "check", "catalog"])


def test_runner_scope_and_import_policy_are_fixed_in_source():
    assert runner.TEST_LABELS == ("catalog.tests",)
    tree = ast.parse(_RUNNER_PATH.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not any(name == "locallibrary.settings" or name.startswith("locallibrary.settings.")
                   for name in imported)
    assert not any(name == "dotenv" or name.startswith("dotenv.") for name in imported)
    assert not any(isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "parse_known_args"
                   for node in ast.walk(tree))


def test_failed_or_errored_test_result_cannot_be_reported_as_green():
    assert runner.exit_code_from_counts(failures=0, errors=0) == 0
    assert runner.exit_code_from_counts(failures=1, errors=0) == 1
    assert runner.exit_code_from_counts(failures=0, errors=1) == 1
    report = runner._report(tests_run=5, failures=1, errors=0)
    assert report["testsRun"] == 5
    assert report["failures"] == 1
    assert report["exit_code"] == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"tests_run": 0},
        {"skipped": 1},
        {"expected_failures": 1},
        {"unexpected_successes": 1},
        {"framework_return": 1},
        {"was_successful": False},
    ],
)
def test_empty_or_non_clean_unittest_outcome_is_nonzero(changes):
    assert runner.exit_code_from_counts(failures=0, errors=0, **changes) == 1


def test_report_preserves_non_green_unittest_counters():
    report = runner._report(
        tests_run=4,
        skipped=1,
        expected_failures=2,
        unexpected_successes=1,
        framework_return=0,
        was_successful=False,
    )
    assert report["testsRun"] == 4
    assert report["skipped"] == 1
    assert report["expectedFailures"] == 2
    assert report["unexpectedSuccesses"] == 1
    assert report["framework_return"] == 0
    assert report["unittest_was_successful"] is False
    assert report["exit_code"] == 1


def test_exception_report_contains_class_only_and_nonzero_exit():
    class SensitiveFailure(Exception):
        pass

    report = runner._report(error_class=type(SensitiveFailure("private path should not escape")).__name__)

    assert report["errors"] == 1
    assert report["setup_error"] == "SensitiveFailure"
    assert report["exit_code"] == 1
    assert "private path" not in repr(report)


def test_sqlite_attach_cannot_create_a_disk_database_in_isolated_subprocess(tmp_path):
    destination = tmp_path / "attached.sqlite3"
    script = """
import importlib.util
import pathlib
import sqlite3
import sys
spec = importlib.util.spec_from_file_location('local_catalog_runner', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
guard = module.SQLiteMemoryGuard()
guard.install()
connection = sqlite3.connect(':memory:')
try:
    try:
        connection.execute('ATTACH DATABASE ? AS external_db', (sys.argv[2],))
    except sqlite3.DatabaseError:
        pass
    else:
        raise SystemExit(21)
finally:
    connection.close()
if pathlib.Path(sys.argv[2]).exists():
    raise SystemExit(22)
print('blocked')
"""
    completed = subprocess.run(
        [sys.executable, "-I", "-B", "-c", script, str(_RUNNER_PATH), str(destination)],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert completed.returncode == 0, "isolated SQLite ATTACH guard did not hold"
    assert completed.stdout.strip() == "blocked"
    assert not destination.exists()


def test_project_root_must_be_absolute_and_contain_fixed_catalog_layout(tmp_path):
    root = _project_root(tmp_path / "demo")
    assert runner.validate_project_root(root) == root.resolve()

    with pytest.raises(runner.RunnerConfigurationError):
        runner.validate_project_root("relative/demo")
    with pytest.raises(runner.RunnerConfigurationError):
        runner.validate_project_root(tmp_path)
