"""Builders shared by the 016 LSP adapter tests.

Pins come from the provider-owned declaration fragments (never hardcoded), fake PATH
lookups are dicts — controlled counterexamples without touching the machine.
"""
from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Mapping

from ordessa_lsp_api import FormatterDefinition, LspServerDefinition

REPO_ROOT = Path(__file__).resolve().parents[5]


def toml_pin(harness_type: str) -> str:
    document = tomllib.loads(captured_harnesses_text())
    for entry in document["harness"]:
        if entry["identity"]["harness_type"] == harness_type:
            return entry["identity"]["version"]
    raise AssertionError(f"harness_type {harness_type!r} missing from toml")


def fake_lookup(table: Mapping[str, str]):
    def lookup(command: str):
        return table.get(command)
    return lookup


def pyright_server() -> LspServerDefinition:
    return LspServerDefinition(name="pyright", command="pyright-langserver",
                               languages=("python",), args=("--stdio",))


def nil_server() -> LspServerDefinition:
    return LspServerDefinition(name="nil", command="nil",
                               languages=("nix",))


def ruff_formatter() -> FormatterDefinition:
    return FormatterDefinition(name="ruff-format", command="ruff",
                               languages=("python",), args=("format", "-"))


def captured_harnesses_text() -> str:
    """Capture actual provider fragments, independent of the default product roster."""
    from ordessa_execution_agents.harness.providers.declarations import RegistrationDeclarations
    from ordessa_server.composition.harness_catalog import capture_harness_catalog

    paths = sorted(REPO_ROOT.glob(
        "plugins/harness/*/src/ordessa_harness_*/_registration_declarations/harness.toml"))
    fragments = tuple(RegistrationDeclarations(
        registry_toml=path.read_bytes(),
        launch_json=path.with_name("launch.json").read_bytes())
        for path in paths)
    if not fragments:
        raise AssertionError("no provider-owned Harness registration declarations found")
    return capture_harness_catalog(
        fragments, launch_declarations=fragments).registry_bytes.decode("utf-8")
