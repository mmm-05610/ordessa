"""Identity pin: one package, one module object per name.

History: M1-P-A① pinned that the legacy alias names and the canonical package
resolved to one module object. The monorepo baseline (2026-09-25) retires the
alias names with the old layout, so the pins that remain meaningful are the
ones the aliases existed to protect: the registry is not duplicated, the
adapter map has one source, the declaration file digest is stable, and the
entry-point facade builds - whichever module of the package is imported first.
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import tomllib
from pathlib import Path

import pytest

CORE = "ordessa_harness"

#: Modules that historically moved between distributions; each must still be
#: importable and resolve through the single canonical package.
CANONICAL_MODULES = (
    "plugin",
    "entrypoints",
    "registry",
    "registry.schema",
    "registry.loader",
    "registry.definitions",
    "registry.validation",
    "registry.capability_claims",
    "generic",
    "generic.factory",
    "generic.profile_store",
    "generic.profile_manager",
    "generic.profile_selector",
    "generic.profile_provider",
    "generic.execution_provider",
    "resources",
    "resources.executable",
    "resources.profile_codec",
    "adapters.base",
    "adapters.generic_cli",
)

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_SRC = PLUGIN_ROOT / "src" / "ordessa_harness"


@pytest.mark.parametrize("dotted", CANONICAL_MODULES)
def test_every_canonical_module_resolves_through_the_single_package(dotted: str) -> None:
    module = __import__(f"{CORE}.{dotted}", fromlist=["*"])
    again = __import__(f"{CORE}.{dotted}", fromlist=["*"])
    assert module is again, f"{CORE}.{dotted} resolved to two module objects"
    assert module.__spec__.name == f"{CORE}.{dotted}"
    # The one package is the plugin's own src tree (not a stray copy on sys.path).
    assert Path(module.__file__).resolve().is_relative_to(CANONICAL_SRC)


def test_the_registry_object_is_not_duplicated() -> None:
    from ordessa_harness.registry.definitions import DEFINITIONS as definitions_a
    from ordessa_harness.registry.definitions import REGISTRY as registry_a
    from ordessa_harness.registry import REGISTRY as registry_b
    from ordessa_harness.registry import DEFINITIONS as definitions_b

    assert registry_a is registry_b
    assert definitions_a is definitions_b
    assert len(registry_a.all()) == 7


def test_the_brand_adapter_map_has_one_source() -> None:
    """The core must not re-declare the map; it imports the existing object.

    A hand-copied second literal is exactly the drift `capability_claims.py`
    warns about, so the pin is identity, not equality.
    """
    from ordessa_harness.generic.factory import ADAPTERS as used_by_the_core
    from ordessa_harness.adapters import ADAPTERS as declared_once

    assert used_by_the_core is declared_once
    assert sorted(used_by_the_core) == [
        "claude", "codex", "dsh", "hermes", "kilo", "opencode", "pi",
    ]


def test_the_brand_adapters_inherit_the_core_implementation() -> None:
    from ordessa_harness.adapters.generic_cli import GenericCliAdapter
    from ordessa_harness.adapters.codex import CodexAdapter
    from ordessa_harness.adapters.kilo import KiloAdapter

    assert issubclass(CodexAdapter, GenericCliAdapter)
    assert issubclass(KiloAdapter, GenericCliAdapter)
    assert CodexAdapter.__mro__[1] is GenericCliAdapter


def test_the_registry_content_is_the_declaration_file_unchanged() -> None:
    """The digest is recomputed from the file the loader is told to read.

    The declaration file did not move, so its bytes — and therefore the digest,
    which other tests and the JS projection compare against — must be identical.
    """
    from ordessa_harness.registry.loader import _builtin_registry_resource, load_builtin_registry

    resource = _builtin_registry_resource()
    assert resource.name == "harnesses.toml"
    text = resource.read_text(encoding="utf-8")
    registry = load_builtin_registry()
    assert registry.digest == "sha256:" + __import__("hashlib").sha256(text.encode()).hexdigest()
    assert len(tomllib.loads(text)["harness"]) == len(registry.all()) == 7
    assert resource.is_relative_to(CANONICAL_SRC)


def test_the_entry_point_facade_still_builds_a_registration() -> None:
    from ordessa_harness.entrypoints import create_codex, create_hermes, create_profile_store

    assert create_profile_store().descriptor() is not None
    assert create_codex().descriptor() is not None
    assert create_hermes().descriptor() is not None
    assert create_codex().harness_type == "codex"
    assert create_profile_store().harness_type is None


CHILD = """
import sys

{first}
import {core}.registry.loader as loader_a
import {core}.registry.definitions as definitions_a
import {core}.generic.profile_store as store_a

import {core}.registry.loader as loader_b
import {core}.registry.definitions as definitions_b
import {core}.generic.profile_store as store_b

assert loader_a is loader_b, "loader module duplicated"
assert definitions_a.REGISTRY is definitions_b.REGISTRY, "registry state duplicated"
assert store_a.ProfileStore is store_b.ProfileStore, "profile store class duplicated"
assert len(definitions_a.REGISTRY.all()) == 7
print("OK")
"""


@pytest.mark.parametrize(
    "first",
    [
        f"import {CORE}.registry.loader",
        f"import {CORE}.plugin",
        f"import {CORE}",
    ],
    ids=["loader-first", "plugin-first", "root-first"],
)
def test_identity_holds_whatever_is_imported_first(first: str) -> None:
    """Every import order must work: a core-first import used to raise.

    Reproduced before the fix: `ImportError: cannot import name 'create_plugin'
    from partially initialized module 'ordessa_harness.plugin'`. The cause was
    an eager import chain while the package was still initialising, so the
    child process is the honest place to pin it.
    """
    script = textwrap.dedent(CHILD).format(first=first, core=CORE)
    environment = dict(os.environ)
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, env=environment,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("OK")
