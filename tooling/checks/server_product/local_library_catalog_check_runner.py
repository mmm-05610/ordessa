#!/usr/bin/env python3
"""Run only the Local Library ``catalog.tests`` against isolated in-memory SQLite.

This is a narrow check runner for the standalone Local Library demo. It does not
load the demo's settings module or accept arbitrary Django test labels/settings.
"""
from __future__ import annotations

import argparse
import contextlib
import importlib
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
import threading
from typing import Any
from urllib.parse import parse_qsl, unquote, urlsplit


DJANGO_VERSION = "5.1.15"
TEST_LABELS = ("catalog.tests",)
_MEMORY_URI_PATH = re.compile(r"^[A-Za-z0-9_.-]+$")


class RunnerConfigurationError(RuntimeError):
    """A safe, non-secret runner configuration failure."""


class DiskSQLiteRefused(RuntimeError):
    """A connection attempted to use SQLite outside the in-memory allowlist."""


def sqlite_target_is_memory(database: Any, *, uri: bool = False) -> bool:
    """Return true only for literal or narrowly shaped in-memory SQLite targets."""
    if isinstance(database, bytes):
        try:
            database = database.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            return False
    if not isinstance(database, str):
        return False
    if database == ":memory:":
        return True
    if not uri or not database.startswith("file:"):
        return False
    try:
        parsed = urlsplit(database)
        query_pairs = parse_qsl(parsed.query, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        return False
    query: dict[str, str] = {}
    for key, value in query_pairs:
        if key in query:
            return False
        query[key] = value
    path = unquote(parsed.path)
    # Django's SQLite test database uses e.g. file:memorydb_default?mode=memory&cache=shared.
    # Reject authority, path separators, fragments and every SQLite URI option
    # beyond the in-memory mode and optional shared/private cache selector.
    return (
        parsed.scheme == "file"
        and not parsed.netloc
        and not parsed.fragment
        and bool(_MEMORY_URI_PATH.fullmatch(path))
        and query.get("mode") == "memory"
        and set(query) <= {"mode", "cache"}
        and query.get("cache", "shared") in {"shared", "private"}
    )


class SQLiteMemoryGuard:
    """Block disk SQLite before opening it and report only safe target labels."""

    def __init__(self) -> None:
        self.allowed_targets: set[str] = set()
        self.allowed_connections = 0
        self.denied_connections = 0
        self.denied_attach_detach = 0
        self._local = threading.local()
        self._original_connect: Any = None

    @staticmethod
    def _uri_argument(args: tuple[Any, ...], kwargs: dict[str, Any]) -> bool:
        if "uri" in kwargs:
            return kwargs["uri"] is True
        # sqlite3.connect positional args after database are timeout, detect_types,
        # isolation_level, check_same_thread, factory, cached_statements, uri.
        return len(args) >= 7 and args[6] is True

    def _audit(self, event: str, args: tuple[Any, ...]) -> None:
        if event != "sqlite3.connect" or not args:
            return
        database = args[0]
        if database == ":memory:":
            self.allowed_connections += 1
            self.allowed_targets.add(":memory:")
            return
        approved_uri = getattr(self._local, "approved_uri", None)
        if isinstance(database, str) and database == approved_uri and sqlite_target_is_memory(database, uri=True):
            self.allowed_connections += 1
            self.allowed_targets.add("file:<memory>?mode=memory")
            return
        self.denied_connections += 1
        raise DiskSQLiteRefused("disk SQLite connections are disabled")

    def _authorize_sql(self, action: int, arg1: Any, arg2: Any, database: Any, source: Any) -> int:
        if action in (sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH):
            self.denied_attach_detach += 1
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    def install(self) -> None:
        """Install an audit hook and a URI-aware gate in this short-lived process."""
        original_connect = sqlite3.connect
        self._original_connect = original_connect

        def guarded_connect(database: Any, *args: Any, **kwargs: Any):
            uri = self._uri_argument(args, kwargs)
            if not sqlite_target_is_memory(database, uri=uri):
                self.denied_connections += 1
                raise DiskSQLiteRefused("disk SQLite connections are disabled")
            factory = kwargs.get("factory")
            if len(args) >= 5:
                factory = args[4]
            if factory not in (None, sqlite3.Connection):
                self.denied_connections += 1
                raise DiskSQLiteRefused("custom SQLite connection factories are disabled")
            old_approved = getattr(self._local, "approved_uri", None)
            if uri and isinstance(database, str):
                self._local.approved_uri = database
            try:
                connection = original_connect(database, *args, **kwargs)
                connection.set_authorizer(self._authorize_sql)
                return connection
            finally:
                if hasattr(self._local, "approved_uri"):
                    if old_approved is None:
                        del self._local.approved_uri
                    else:
                        self._local.approved_uri = old_approved

        # Patch the shared sqlite3 module so callers that use sqlite3.connect
        # cannot pass a disk path with uri=False and rely on URI-looking text.
        sqlite3.connect = guarded_connect
        # Django's SQLite backend imports ``sqlite3.dbapi2`` directly.
        sqlite3.dbapi2.connect = guarded_connect
        sys.addaudithook(self._audit)


def isolated_django_settings(project_root: Path, scratch_root: Path) -> dict[str, Any]:
    """Return fixed settings without importing any project settings module."""
    root = project_root.resolve(strict=True)
    scratch = scratch_root.resolve()
    return {
        "SECRET_KEY": "local-catalog-check-only",
        "DEBUG": False,
        "ALLOWED_HOSTS": ["testserver", "localhost"],
        "ROOT_URLCONF": "locallibrary.urls",
        "INSTALLED_APPS": [
            "django.contrib.admin",
            "django.contrib.auth",
            "django.contrib.contenttypes",
            "django.contrib.sessions",
            "django.contrib.messages",
            "django.contrib.staticfiles",
            "catalog.apps.CatalogConfig",
        ],
        "MIDDLEWARE": [
            "django.middleware.security.SecurityMiddleware",
            "django.contrib.sessions.middleware.SessionMiddleware",
            "django.middleware.common.CommonMiddleware",
            "django.middleware.csrf.CsrfViewMiddleware",
            "django.contrib.auth.middleware.AuthenticationMiddleware",
            "django.contrib.messages.middleware.MessageMiddleware",
            "django.middleware.clickjacking.XFrameOptionsMiddleware",
        ],
        "TEMPLATES": [{
            "BACKEND": "django.template.backends.django.DjangoTemplates",
            "DIRS": [str(root / "templates")],
            "APP_DIRS": True,
            "OPTIONS": {"context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]},
        }],
        "DATABASES": {"default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": ":memory:",
            "TEST": {"NAME": ":memory:"},
            "OPTIONS": {"timeout": 20},
        }},
        "AUTH_PASSWORD_VALIDATORS": [],
        "LANGUAGE_CODE": "en-us",
        "TIME_ZONE": "UTC",
        "USE_I18N": True,
        "USE_TZ": True,
        "STATIC_URL": "/static/",
        "STATIC_ROOT": str(scratch / "static"),
        "MEDIA_URL": "/media/",
        "MEDIA_ROOT": str(scratch / "media"),
        "DEFAULT_AUTO_FIELD": "django.db.models.BigAutoField",
        "APPEND_SLASH": True,
    }


def validate_project_root(value: str | os.PathLike[str]) -> Path:
    root = Path(value)
    if not root.is_absolute():
        raise RunnerConfigurationError("project root must be an absolute path")
    try:
        root = root.resolve(strict=True)
    except OSError:
        raise RunnerConfigurationError("project root is unavailable") from None
    required = (root / "catalog" / "tests" / "__init__.py", root / "locallibrary" / "urls.py")
    if not root.is_dir() or not all(path.is_file() for path in required):
        raise RunnerConfigurationError("project root does not contain the fixed catalog test layout")
    return root


def exit_code_from_counts(
    *,
    failures: int,
    errors: int,
    tests_run: int = 1,
    skipped: int = 0,
    expected_failures: int = 0,
    unexpected_successes: int = 0,
    framework_return: int = 0,
    was_successful: bool = True,
) -> int:
    return 1 if (
        failures or errors or tests_run == 0 or skipped or expected_failures
        or unexpected_successes or framework_return != 0 or not was_successful
    ) else 0


def _test_ids(items: list[Any]) -> list[str]:
    result: list[str] = []
    for item in items:
        test = item[0] if isinstance(item, tuple) else item
        try:
            result.append(str(test.id()))
        except Exception:
            result.append(type(test).__name__)
    return result


def _module_status() -> tuple[bool, bool]:
    product_settings = any(
        name == "locallibrary.settings" or name.startswith("locallibrary.settings.")
        for name in sys.modules
    )
    dotenv_loaded = any(name == "dotenv" or name.startswith("dotenv.") for name in sys.modules)
    return product_settings, dotenv_loaded


def _report(
    *,
    tests_run: int = 0,
    failures: int = 0,
    errors: int = 0,
    skipped: int = 0,
    expected_failures: int = 0,
    unexpected_successes: int = 0,
    framework_return: int = 0,
    was_successful: bool = True,
    failure_tests: list[str] | None = None,
    error_tests: list[str] | None = None,
    skipped_tests: list[str] | None = None,
    database: dict[str, Any] | None = None,
    error_class: str | None = None,
) -> dict[str, Any]:
    product_settings_imported, dotenv_imported = _module_status()
    result: dict[str, Any] = {
        "testsRun": tests_run,
        "failures": failures,
        "errors": errors,
        "skipped": skipped,
        "expectedFailures": expected_failures,
        "unexpectedSuccesses": unexpected_successes,
        "framework_return": framework_return,
        "unittest_was_successful": was_successful,
        "failure_tests": failure_tests or [],
        "error_tests": error_tests or [],
        "skipped_tests": skipped_tests or [],
        "database": database or {
            "engine": "django.db.backends.sqlite3",
            "configured_name": ":memory:",
            "configured_test_name": ":memory:",
            "allowed_sqlite_targets": [],
            "allowed_connections": 0,
            "denied_connections": 0,
            "denied_attach_detach": 0,
        },
        "product_settings_imported": product_settings_imported,
        "dotenv_imported": dotenv_imported,
        "exit_code": exit_code_from_counts(
            failures=failures,
            errors=errors,
            tests_run=tests_run,
            skipped=skipped,
            expected_failures=expected_failures,
            unexpected_successes=unexpected_successes,
            framework_return=framework_return,
            was_successful=was_successful,
        ),
    }
    if error_class:
        result["setup_error"] = error_class
        if errors == 0:
            result["errors"] = 1
            result["exit_code"] = 1
    return result


def run_catalog_tests(project_root: Path) -> dict[str, Any]:
    """Configure the fixed project test scope and return a safe structured result."""
    sys.dont_write_bytecode = True
    try:
        if any(_module_status()):
            raise RunnerConfigurationError("isolated process required")
        root = validate_project_root(project_root)
        sys.path.insert(0, str(root))
        django = importlib.import_module("django")
        if django.get_version() != DJANGO_VERSION:
            raise RunnerConfigurationError("required Django version is unavailable")
        from django.conf import settings

        if settings.configured:
            raise RunnerConfigurationError("Django settings were already configured")
        with tempfile.TemporaryDirectory(prefix="ordessa-local-catalog-check-") as scratch:
            config = isolated_django_settings(root, Path(scratch))
            Path(config["STATIC_ROOT"]).mkdir(parents=True, exist_ok=True)
            Path(config["MEDIA_ROOT"]).mkdir(parents=True, exist_ok=True)
            settings.configure(**config)
            guard = SQLiteMemoryGuard()
            guard.install()
            django.setup()

            from django.test.runner import DiscoverRunner

            class ResultCaptureRunner(DiscoverRunner):
                result = None

                def run_suite(self, suite, **kwargs):
                    self.result = super().run_suite(suite, **kwargs)
                    return self.result

            test_runner = ResultCaptureRunner(
                verbosity=0,
                interactive=False,
                failfast=False,
                keepdb=False,
                parallel=1,
                debug_mode=False,
                buffer=True,
            )
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                framework_return = test_runner.run_tests(list(TEST_LABELS))
            result = test_runner.result
            if result is None:
                raise RunnerConfigurationError("Django test runner returned no result")
            failures = len(result.failures)
            errors = len(result.errors)
            expected_failures = len(result.expectedFailures)
            unexpected_successes = len(result.unexpectedSuccesses)
            was_successful = bool(result.wasSuccessful())
            if type(framework_return) is not int:
                framework_return = 1
            database = {
                "engine": config["DATABASES"]["default"]["ENGINE"],
                "configured_name": config["DATABASES"]["default"]["NAME"],
                "configured_test_name": config["DATABASES"]["default"]["TEST"]["NAME"],
                "allowed_sqlite_targets": sorted(guard.allowed_targets),
                "allowed_connections": guard.allowed_connections,
                "denied_connections": guard.denied_connections,
                "denied_attach_detach": guard.denied_attach_detach,
            }
            report = _report(
                tests_run=result.testsRun,
                failures=failures,
                errors=errors,
                skipped=len(result.skipped),
                expected_failures=expected_failures,
                unexpected_successes=unexpected_successes,
                framework_return=framework_return,
                was_successful=was_successful,
                failure_tests=_test_ids(result.failures),
                error_tests=_test_ids(result.errors),
                skipped_tests=_test_ids(result.skipped),
                database=database,
            )
            if report["product_settings_imported"] or report["dotenv_imported"]:
                report["errors"] += 1
                report["setup_error"] = "IsolationImportDetected"
                report["exit_code"] = 1
            return report
    except Exception as error:
        # Do not serialize exception text, which can contain local paths or settings.
        return _report(error_class=type(error).__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run only catalog.tests with isolated in-memory SQLite."
    )
    parser.add_argument("--project-root", required=True, help="absolute Local Library project root")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        project_root = validate_project_root(args.project_root)
        report = run_catalog_tests(project_root)
    except Exception as error:
        report = _report(error_class=type(error).__name__)
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return int(report["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
