"""Identity pin: one package, one module object per name.

History: M1-P-A① pinned that the legacy alias names and the canonical package
resolved to one module object. Current pins protect the selected registry,
the one adapter map and the declaration digest. Retired Profile entrypoints
and filesystem stores must stay absent.
"""
from __future__ import annotations
from ordessa_server_product.composition import ProductCompositionUnavailable
from ordessa_server.composition.configuration.product_selection import bind_product_harness_effects

import os
import subprocess
import sys
import textwrap
import tomllib
from pathlib import Path

import pytest

CORE = "ordessa_agents.harness.providers"
BINDING = "ordessa_server_product.harness_adapters"
DECLARATIONS = CORE + ".declarations"
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
RETIRED_ROOT = REPOSITORY_ROOT / "plugins/harness/src/ordessa_harness"

# Each historical responsibility has exactly one current module owner. The
# retired registry globals are replaced by explicit captured values; resources
# have the Agents owner and no Kernel alias.
CANONICAL_MODULES = (
    "contributions", "registry", "registry.schema",
    "registry.loader", "registry.definitions", "registry.validation",
    "registry.capability_claims", "generic", "resources",
    "resources.executable", "resources.profile_codec", "adapters.base", "adapters.generic_cli",
)


def _canonical_name(dotted):
    if dotted == "contributions":
        return "ordessa_server.composition.configuration.contributions"
    if dotted == "registry":
        return DECLARATIONS
    if dotted.startswith("registry."):
        leaf = dotted.split(".", 1)[1]
        return DECLARATIONS + "." + ("fragments" if leaf == "definitions" else leaf)
    if dotted.startswith("resources"):
        return CORE + "." + dotted
    return BINDING + "." + dotted


@pytest.mark.parametrize("dotted", CANONICAL_MODULES)
def test_every_canonical_module_resolves_through_the_single_package(dotted: str) -> None:
    name = _canonical_name(dotted)
    module = __import__(name, fromlist=["*"])
    again = __import__(name, fromlist=["*"])
    assert module is again, f"{name} resolved to two module objects"
    assert module.__spec__.name == name
    assert Path(module.__file__).resolve().is_relative_to(REPOSITORY_ROOT)
    if dotted.startswith(("registry", "resources")):
        assert Path(module.__file__).resolve().is_relative_to(
            REPOSITORY_ROOT / "packages/execution/agents/src")
    assert not RETIRED_ROOT.exists(), "the retired root super-package tree must stay absent"


def test_the_registry_object_is_not_duplicated() -> None:
    from ordessa_server.composition.selected_harness_catalog import capture_selected_harness_catalog
    from ordessa_server_product.composition import ServerProductComposition
    captured = capture_selected_harness_catalog()
    composition = bind_product_harness_effects(ServerProductComposition())
    composition.bind_harness_registry(captured.registry)
    composition.bind_harness_registry(captured.registry)
    assert composition.harness_registry is captured.registry
    assert composition.harness_registry.get("codex") is captured.registry.get("codex")
    # The actual historical document contains eight canonical rows; the old
    # seven-row assertion contradicted its own eight-row digest test below.
    assert len(captured.registry.all()) == 8
    assert composition.capabilities_for("codex")["start"] is True
    with pytest.raises(ProductCompositionUnavailable, match="different composition"):
        composition.bind_harness_registry(capture_selected_harness_catalog().registry)
    assert composition.harness_registry is captured.registry


def test_the_brand_adapter_map_has_one_source() -> None:
    """Remaining pure adapter descriptors share one declared map."""
    from ordessa_server_product.harness_adapters.adapters import ADAPTERS as declared_once

    assert sorted(declared_once) == [
        "claude", "codex", "dsh", "hermes", "kilo", "opencode", "pi",
    ]


def test_the_brand_adapters_inherit_the_core_implementation() -> None:
    from ordessa_server_product.harness_adapters.adapters.generic_cli import GenericCliAdapter
    from ordessa_server_product.harness_adapters.adapters.codex import CodexAdapter
    from ordessa_server_product.harness_adapters.adapters.kilo import KiloAdapter

    assert issubclass(CodexAdapter, GenericCliAdapter)
    assert issubclass(KiloAdapter, GenericCliAdapter)
    assert CodexAdapter.__mro__[1] is GenericCliAdapter


def test_the_registry_content_is_the_declaration_file_unchanged() -> None:
    """The digest is recomputed from the file the loader is told to read.

    The declaration file did not move, so its bytes — and therefore the digest,
    which other tests and the JS projection compare against — must be identical.
    """
    from ordessa_server.composition.selected_harness_catalog import capture_selected_harness_catalog
    captured = capture_selected_harness_catalog()
    text = captured.registry_bytes.decode("utf-8")
    registry = captured.registry
    assert registry.digest == "sha256:" + __import__("hashlib").sha256(text.encode()).hexdigest()
    assert len(tomllib.loads(text)["harness"]) == len(registry.all()) == 8
    assert __import__("hashlib").sha256(captured.registry_bytes).hexdigest() == (
        "956aec189bc21eae998a17f2994648f929c905799538e89c3e947e2f1e1fea1f")
    import ordessa_agents.harness.providers.declarations as declarations
    assert not hasattr(declarations, "REGISTRY")
    assert not hasattr(declarations, "DEFINITIONS")


def test_retired_profile_factories_are_absent() -> None:
    import importlib.util
    for name in ("entrypoints", "plugin", "generic.factory", "generic.profile_store",
                 "generic.profile_manager", "generic.profile_selector", "generic.profile_provider",
                 "generic.profile_envelope", "generic.execution_provider"):
        assert importlib.util.find_spec(BINDING + "." + name) is None


CHILD = """
import sys

{first}
import {declarations}.loader as loader_a
import {declarations}.loader as loader_b
from ordessa_server.composition.selected_harness_catalog import capture_selected_harness_catalog
from ordessa_server_product.composition import ServerProductComposition
captured = capture_selected_harness_catalog()
composition = ServerProductComposition()
composition.bind_harness_registry(captured.registry)
assert loader_a is loader_b, "loader module duplicated"
assert composition.harness_registry is captured.registry, "registry state duplicated"
assert len(captured.registry.all()) == 8
print("OK")
"""


@pytest.mark.parametrize(
    "first",
    [
        f"import {DECLARATIONS}.loader",
        f"import {BINDING}.adapters",
        f"import {CORE}",
    ],
    ids=["loader-first", "adapters-first", "root-first"],
)
def test_identity_holds_whatever_is_imported_first(first: str) -> None:
    """Every import order must work: a core-first import used to raise.

    The child process still pins independent loader and selected product
    registry identity under distinct import orders.
    """
    script = textwrap.dedent(CHILD).format(first=first, core=CORE, binding=BINDING, declarations=DECLARATIONS)
    environment = dict(os.environ)
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, env=environment,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("OK")
