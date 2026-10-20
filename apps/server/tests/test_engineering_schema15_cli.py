"""Source-facing Server opt-in for Engineering's reviewer-assignment schema."""
import sqlite3
import pytest

from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_server import __main__ as host_cli
from ordessa_server.composition.engineering import (
    DEFAULT_MACHINE_CAPABILITIES,
    _engineering_selection,
)
from ordessa_server.composition.product_runtime import build_product_runtime
from ordessa_server_product import cli as product_cli
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary


REVIEWER_ASSIGNMENT_CAPABILITIES = {
    "engineering.reviews.assign_reviewer",
    "engineering.reviews.revoke_reviewer",
}


def test_schema15_is_explicit_and_schema8_remains_the_cli_and_selection_default(tmp_path):
    parser = host_cli.parser(product_cli.SERVER_CLI_FLAGS)
    assert parser.parse_args([]).engineering_schema_version == 8
    assert parser.parse_args(["--engineering-schema-version", "15"]).engineering_schema_version == 15

    options = {
        "library_path": (tmp_path / "library.sqlite").resolve(),
        "library_id": "schema15-explicit",
        "scope": Scope("schema15-realm", "schema15-project"),
        "create_library": True,
        "schema_version": 15,
    }
    assert _engineering_selection(options)[5] == 15
    assert _engineering_selection({key: value for key, value in options.items()
                                    if key != "schema_version"})[5] == 8


def test_reviewer_assignment_capabilities_are_not_default_machine_grants():
    assert REVIEWER_ASSIGNMENT_CAPABILITIES.isdisjoint(DEFAULT_MACHINE_CAPABILITIES)


@pytest.mark.parametrize("version", [8, 14])
def test_explicit_schema15_selection_does_not_migrate_existing_library(tmp_path, version):
    path = (tmp_path / "existing.sqlite").resolve()
    created = EngineeringLibrary.create(path, library_id="existing", schema_version=version)
    created.close()
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
        before_tables = tuple(connection.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name"))
    runtime = build_product_runtime(tmp_path / "server", library_path=path,
        library_id="existing", scope=Scope("schema15-realm", "schema15-project"),
        create_library=False, schema_version=15,
        machine_capabilities=("engineering.capabilities",))
    try:
        assert runtime.plugin_host.is_active("ordessa.engineering")
        plugin = next(plugin for plugin in runtime.plugin_selection
                      if plugin.descriptor().id == "ordessa.engineering")
        assert plugin.library.schema_version == version
    finally:
        runtime.stop()
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (version,)
        assert tuple(connection.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name")) == before_tables
