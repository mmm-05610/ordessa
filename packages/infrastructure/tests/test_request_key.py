from __future__ import annotations

import subprocess
import sys
from dataclasses import FrozenInstanceError

import pytest

from ordessa_infrastructure import identifiers
from ordessa_infrastructure.identifiers import RequestKey


def test_public_module_exports_request_key_without_changing_existing_helpers() -> None:
    assert identifiers.__all__ == ["now", "opaque_id", "RequestKey"]
    assert identifiers.RequestKey is RequestKey
    assert callable(identifiers.now)
    assert callable(identifiers.opaque_id)


def test_request_key_keeps_existing_positional_and_keyword_field_format() -> None:
    positional = RequestKey("env-a", "user:local:team", "request-1")
    keyword = RequestKey(
        environment_namespace="env-a",
        principal_scope="user:local:team",
        request_id="request-1",
    )

    assert positional == keyword
    assert positional.environment_namespace == "env-a"
    assert positional.principal_scope == "user:local:team"
    assert positional.request_id == "request-1"
    assert positional.comparison == {}
    with pytest.raises(FrozenInstanceError):
        positional.request_id = "request-2"  # type: ignore[misc]


def test_request_key_accepts_existing_identifier_and_scope_length_boundaries() -> None:
    key = RequestKey("a" * 64, "a" * 128, "b" * 64)

    assert len(key.environment_namespace) == 64
    assert len(key.principal_scope) == 128
    assert len(key.request_id) == 64


@pytest.mark.parametrize("value", ["Env-a", "1env", "env/a", "a" * 65])
def test_environment_namespace_and_request_id_keep_local_id_validation(value: str) -> None:
    with pytest.raises(ValueError, match="RequestKey.environment_namespace must match"):
        RequestKey(value, "user:local:team", "request-1")

    with pytest.raises(ValueError, match="RequestKey.request_id must match"):
        RequestKey("env-a", "user:local:team", value)


@pytest.mark.parametrize("scope", ["User:local:team", "1user", "user/remote", "a" * 129])
def test_principal_scope_keeps_existing_validation(scope: str) -> None:
    with pytest.raises(ValueError, match="RequestKey.principal_scope is malformed"):
        RequestKey("env-a", scope, "request-1")


def test_request_ids_are_distinct_within_the_same_opaque_partition() -> None:
    first = RequestKey("env-a", "user:local:team", "request-1")
    second = RequestKey("env-a", "user:local:team", "request-2")

    assert (first.environment_namespace, first.principal_scope) == (
        second.environment_namespace,
        second.principal_scope,
    )
    assert first.request_id != second.request_id
    assert first != second


def test_comparison_payload_remains_compare_true_without_changing_three_key_fields() -> None:
    first = RequestKey("env-a", "user:local:team", "request-1", {"target": "alpha"})
    same = RequestKey("env-a", "user:local:team", "request-1", {"target": "alpha"})
    changed = RequestKey("env-a", "user:local:team", "request-1", {"target": "beta"})

    assert (first.environment_namespace, first.principal_scope, first.request_id) == (
        changed.environment_namespace,
        changed.principal_scope,
        changed.request_id,
    )
    assert first == same
    assert first != changed


_TECHNICAL_ONLY = r'''
import importlib.abc, os, socket, sqlite3, subprocess, sys

class TechnicalImportsOnly(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] not in sys.stdlib_module_names | {'ordessa_infrastructure'}:
            raise AssertionError('foreign import: ' + fullname)

sys.meta_path.insert(0, TechnicalImportsOnly())
def forbidden(*args, **kwargs):
    raise AssertionError('runtime IO attempted')
os.open = os.makedirs = os.mkdir = os.fsync = forbidden
sqlite3.connect = subprocess.Popen = socket.socket = forbidden
from ordessa_infrastructure.identifiers import RequestKey
value = RequestKey('env-a', 'user:local:team', 'request-1')
assert value.request_id == 'request-1'
'''


def _run_isolated(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)


def test_request_key_import_is_io_free_and_has_no_business_imports() -> None:
    completed = _run_isolated(_TECHNICAL_ONLY)
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize("module", ["ordessa_execution_api.environment", "ordessa_agents"])
def test_actual_subprocess_canary_blocks_c1_and_execution_imports(module: str) -> None:
    completed = _run_isolated(_TECHNICAL_ONLY + f"\nimport {module}\n")

    assert completed.returncode != 0
    assert f"foreign import: {module.split('.')[0]}" in completed.stderr
