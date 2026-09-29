"""Builders shared by the 016 LSP adapter tests.

Pins come from the repository's harnesses.toml (never hardcoded), fake PATH
lookups are dicts — controlled counterexamples without touching the machine.
"""
from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Mapping

from ordessa_lsp_api import FormatterDefinition, LspServerDefinition

REPO_ROOT = Path(__file__).resolve().parents[5]
HARNESSES_TOML = (REPO_ROOT / "plugins" / "harness" / "src" /
                  "ordessa_harness" / "harnesses.toml")


def toml_pin(harness_type: str) -> str:
    document = tomllib.loads(HARNESSES_TOML.read_text(encoding="utf-8"))
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
