"""Pure technical tests for the generic database record contract."""
from __future__ import annotations

import ast
import inspect
from pathlib import Path
import subprocess
import sys
import textwrap
from typing import get_type_hints

import pytest

from ordessa_infrastructure.database.records import (
    DOMAIN_STORE_VERSION,
    DomainRevisionConflict,
    DomainStorePort,
    DomainWrite,
)
from ordessa_infrastructure.identifiers import RequestKey


def test_domain_write_preserves_opaque_mapping_and_cas_revision_values():
    value = {"payload": object()}
    absent = DomainWrite("catalog", "one", 0, value)
    existing = DomainWrite("catalog", "one", 7, value)
    large = DomainWrite("catalog", "one", 2**80, value)

    assert absent.value is value
    assert existing.expected_revision == 7
    assert large.expected_revision == 2**80
    assert absent.namespace == "catalog" and absent.record_id == "one"
    with pytest.raises(AttributeError):
        absent.record_id = "two"


@pytest.mark.parametrize(
    "namespace,record_id,revision,value,error",
    [
        ("", "record", 0, {}, ValueError),
        (1, "record", 0, {}, ValueError),
        ("namespace", "", 0, {}, ValueError),
        ("namespace", None, 0, {}, ValueError),
        ("namespace", "record", -1, {}, ValueError),
        ("namespace", "record", True, {}, ValueError),
        ("namespace", "record", 1.0, {}, ValueError),
        ("namespace", "record", 0, None, TypeError),
        ("namespace", "record", 0, [], TypeError),
    ],
)
def test_domain_write_rejects_invalid_local_fields(namespace, record_id, revision, value, error):
    with pytest.raises(error):
        DomainWrite(namespace, record_id, revision, value)


def test_domain_revision_conflict_is_stable_and_business_neutral():
    assert DOMAIN_STORE_VERSION == "domain-records/1"
    assert DomainRevisionConflict.__bases__ == (RuntimeError,)
    conflict = DomainRevisionConflict("stale revision")
    assert conflict.code == "DOMAIN_REVISION_CONFLICT"
    assert str(conflict) == "stale revision"


def test_domain_store_port_keeps_the_existing_four_method_surface():
    assert list(inspect.signature(DomainStorePort.read_domain).parameters) == [
        "self", "environment", "namespace", "record_id"
    ]
    assert list(inspect.signature(DomainStorePort.list_domain).parameters) == [
        "self", "environment", "namespace"
    ]
    assert list(inspect.signature(DomainStorePort.read_domain_result).parameters) == [
        "self", "request", "digest"
    ]
    assert list(inspect.signature(DomainStorePort.commit_domain_change).parameters) == [
        "self", "request", "digest", "writes", "result"
    ]
    assert get_type_hints(DomainStorePort.read_domain_result)["request"] is RequestKey
    assert get_type_hints(DomainStorePort.commit_domain_change)["request"] is RequestKey


def test_runtime_protocol_requires_all_four_capabilities_without_calling_them():
    class CompleteStore:
        def __init__(self):
            self.calls = 0

        def _called(self, *args, **kwargs):
            self.calls += 1

        def read_domain(self, environment, namespace, record_id):
            return self._called(environment, namespace, record_id)

        def list_domain(self, environment, namespace):
            return self._called(environment, namespace)

        def read_domain_result(self, request, digest):
            return self._called(request, digest)

        def commit_domain_change(self, request, digest, writes, result):
            return self._called(request, digest, writes, result)

    class MissingCommit:
        def read_domain(self, environment, namespace, record_id): ...
        def list_domain(self, environment, namespace): ...
        def read_domain_result(self, request, digest): ...

    store = CompleteStore()
    assert isinstance(store, DomainStorePort)
    assert not isinstance(MissingCommit(), DomainStorePort)
    assert store.calls == 0


def test_contract_source_imports_only_stdlib_and_its_infrastructure_identity():
    import ordessa_infrastructure.database.records as records
    source = Path(records.__file__)
    tree = ast.parse(source.read_text(encoding="utf-8"))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            roots.add((node.module or "").split(".", 1)[0])
    assert roots <= sys.stdlib_module_names | {"ordessa_infrastructure"}
    assert not roots.intersection(
        {"ordessa_execution_api", "ordessa_execution_agents", "ordessa_units", "pacthold", "ordessa_server"}
    )


def test_import_is_io_free_and_does_not_probe_execution_or_store_callbacks():
    script = textwrap.dedent(
        """
        import importlib.abc, os, socket, sqlite3, subprocess, sys
        import datetime, uuid

        forbidden_owners = {
            'ordessa_execution_api', 'ordessa_execution_agents',
            'ordessa_units', 'pacthold', 'ordessa_server',
        }
        class BlockOwners(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname.split('.', 1)[0] in forbidden_owners:
                    raise AssertionError('contract imported an execution owner: ' + fullname)
        sys.meta_path.insert(0, BlockOwners())

        def forbidden(*args, **kwargs):
            raise AssertionError('contract import attempted runtime IO')
        sqlite3.connect = subprocess.Popen = socket.socket = forbidden
        os.open = os.mkdir = os.makedirs = os.fsync = forbidden

        from ordessa_infrastructure.database.records import DomainStorePort, DomainWrite
        class Store:
            calls = 0
            def read_domain(self, *args): self.calls += 1
            def list_domain(self, *args): self.calls += 1
            def read_domain_result(self, *args): self.calls += 1
            def commit_domain_change(self, *args): self.calls += 1
        store = Store()
        assert isinstance(store, DomainStorePort)
        value = {'opaque': object()}
        assert DomainWrite('ns', 'key', 0, value).value is value
        assert store.calls == 0
        """
    )
    completed = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
