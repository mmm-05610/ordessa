"""Batch-2 owner checks: retired adapter paths and the connection-primitive owner.

Counter-examples for S1 (decision client), S2a (filesystem adapters) and S2b
(SQLite connection through the infrastructure primitive).
"""
from __future__ import annotations

import importlib.util


def _spec(module: str):
    return importlib.util.find_spec(module)


def test_retired_adapter_module_paths_are_absent():
    # adapters.execution was fully retired: decision/filesystem/registry moved.
    assert _spec('ordessa_engineering.adapters.execution') is None


def test_new_adapter_owners_are_single_and_importable():
    from ordessa_engineering.adapters.decision.client import select_review
    from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader
    from ordessa_engineering.adapters.filesystem.package_writer import PackageFiles
    from ordessa_engineering.adapters.registry.loading import load_registry
    from ordessa_engineering.adapters.registry.source_integrity import implementation_facts
    assert callable(select_review) and callable(FileResourceReader) and callable(PackageFiles)
    assert callable(load_registry) and callable(implementation_facts)


def test_sqlite_connections_use_the_infrastructure_primitive():
    import ordessa_infrastructure.database as infra
    from ordessa_engineering.adapters.persistence import sqlite as _pkg  # noqa: F401
    from ordessa_engineering.adapters.persistence.sqlite import engineering_library, migrations
    assert engineering_library.create_connection is infra.create_connection
    assert migrations.create_connection is infra.create_connection
    assert engineering_library.SQLiteOptions is infra.SQLiteOptions
