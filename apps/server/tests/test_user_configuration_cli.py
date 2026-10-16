"""First-case configuration file routes the ordinary default runtime."""
import json
from pathlib import Path

import pytest

from ordessa_server import __main__ as host_cli
from ordessa_server_product import cli as product_cli


def _configuration(path):
    return {
        "version": 1,
        "engineering": {
            "libraryPath": str(path),
            "libraryId": "first-case-library",
            "realm": "first-case-realm",
            "project": "first-case-project",
            "schemaVersion": 15,
            "createLibrary": True,
            "machineCapabilities": ["engineering.capabilities"],
        },
    }


def test_user_config_plan_passes_explicit_values_to_default_runtime(tmp_path):
    library = (tmp_path / "fresh-library.sqlite").resolve()
    config_path = tmp_path / "first-case.json"
    config_path.write_text(json.dumps(_configuration(library)), encoding="utf-8")
    args = host_cli.parser(product_cli.SERVER_CLI_FLAGS).parse_args(
        ["--user-config", str(config_path)])

    plan = product_cli.plan_server_cli(vars(args))

    assert plan.error is None
    assert plan.method == "default_runtime"
    assert plan.args == ()
    assert plan.kwargs == {"engineering_options": {
        "library_path": library,
        "library_id": "first-case-library",
        "realm": "first-case-realm",
        "project": "first-case-project",
        "schema_version": 15,
        "create_library": True,
        "machine_capabilities": ("engineering.capabilities",),
    }}


@pytest.mark.parametrize("extra", [
    ["--engineering-schema-version", "8"],
    ["--engineering-library-id", "other"],
    ["--execution-mode", "native"],
    ["--native-profile-harness", "codex"],
    ["--native-installed-artifact-root", "/root-managed/artifacts"],
    ["--native-additional-adapters", "[]"],
    ["--native-adapter-command", "/usr/bin/node"],
    ["--native-adapter-arg", "adapter-arg"],
    ["--native-harness", "pi"],
    ["--native-continuation"],
    ["--native-pi-profile-bridge"],
])
def test_user_config_refuses_ambiguous_legacy_options(tmp_path, extra):
    config_path = tmp_path / "first-case.json"
    config_path.write_text(json.dumps(_configuration(tmp_path / "fresh.sqlite")), encoding="utf-8")
    args = host_cli.parser(product_cli.SERVER_CLI_FLAGS).parse_args(
        ["--user-config", str(config_path), *extra])
    plan = product_cli.plan_server_cli(vars(args))
    assert plan.method == ""
    assert plan.args == ()
    assert plan.kwargs == {}
    assert "cannot be combined" in plan.error


def test_user_config_rejects_duplicate_keys_and_unknown_capabilities_shape(tmp_path):
    config_path = tmp_path / "first-case.json"
    config_path.write_text('{"version":1,"version":1}', encoding="utf-8")
    parsed = host_cli.parser(product_cli.SERVER_CLI_FLAGS).parse_args(
        ["--user-config", str(config_path)])
    assert "strict UTF-8 JSON" in product_cli.plan_server_cli(vars(parsed)).error

    bad = _configuration(tmp_path / "fresh.sqlite")
    bad["engineering"]["roleGrant"] = True
    config_path.write_text(json.dumps(bad), encoding="utf-8")
    parsed = host_cli.parser(product_cli.SERVER_CLI_FLAGS).parse_args(
        ["--user-config", str(config_path)])
    assert "incomplete or unknown" in product_cli.plan_server_cli(vars(parsed)).error
