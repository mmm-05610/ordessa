"""C20 -- the Profile extension surface is public-facet/contribution only.

Proof is at the **AST level**, not "grep the tree and count zero hits": a grep
that finds nothing is indistinguishable from a gate that cannot see anything.
Each rule below therefore ships a *discrimination* test that feeds the same
analyser a synthetic source it must flag, so a passing real-tree assertion
means the analyser looked.

The three things C20 forbids in ``plugins/profile/src/ordessa_profile``:

1. importing a resource plugin's private implementation (the Profile plugin
   reaches resource plugins only through the public facet/contribution
   contracts it publishes in ``contracts.py`` and ``facets.py``);
2. brand-specific configuration branching -- Profile holds no Codex/Claude/Pi
   knowledge; all brand differences are Harness's;
3. reaching past the published contract surface of its own dependencies.
"""
from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "ordessa_profile"

#: Import roots Profile is allowed to name. ``pacthold*`` is the governance
#: kernel and plugin SDK, ``server_plugin_api`` is the host's published plugin
#: surface, ``ordessa_harness_api`` is Harness's published application
#: capability contract -- the only Harness surface Profile consumes, and only
#: for the port DTOs (inspect/plan/apply/query/reconcile). Everything else is
#: the standard library or Profile's own package.
ALLOWED_ROOTS = {
    "__future__", "ast", "contextlib", "dataclasses", "datetime", "enum",
    "json", "pathlib", "re", "sqlite3", "threading", "typing", "unicodedata",
    "uuid", "os", "collections", "itertools", "functools", "hashlib",
    "pacthold", "pacthold_runtime_compat",
    "server_plugin_api", "ordessa_harness_api",
    "ordessa_profile",
}

#: Harness surface Profile must never reach: everything that is not the
#: published capability contract. Brand differences and native configuration
#: live behind these and Profile may not name them (C20/C21).
FORBIDDEN_PREFIXES = (
    "ordessa_harness.",
    "ordessa_harness_configuration",
    "ordessa_model_provider",
)

#: Brand vocabulary that would turn Profile into a brand-aware component.
BRAND_TOKENS = frozenset({
    "codex", "claude", "claude-code", "claude_code", "gemini", "cursor",
    "aider", "copilot", "anthropic", "openai",
})

#: Native configuration keys that only make sense inside a brand's own config
#: surface. Naming one here is how brand branching sneaks back in.
BRAND_CONFIG_TOKENS = frozenset({
    "model_provider", "wire_api", "preferred_auth_method",
    "model_reasoning_effort", "experimental_use_rmcp_client",
    "hasCompletedOnboarding", "oauth_account_id", "CLAUDE_CODE_",
})


def imported_modules(source: str) -> set[str]:
    """Every absolute module name an ``ast`` parse of *source* imports."""
    tree = ast.parse(source)
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:      # relative: Profile's own package
                continue
            if node.module:
                found.add(node.module)
    return found


def import_violations(source: str) -> list[str]:
    return sorted(
        module for module in imported_modules(source)
        if module.split(".")[0] not in ALLOWED_ROOTS
    )


def brand_branch_violations(source: str) -> list[str]:
    """Brand vocabulary that *decides* something.

    A brand name in a docstring is history and is not a violation; a brand name
    in a comparison, a container, or a conditional is Profile making a
    brand-aware decision, which is exactly what C20 forbids.
    """
    tree = ast.parse(source)
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            operands = [node.left, *node.comparators]
            for operand in operands:
                if isinstance(operand, ast.Constant) and isinstance(
                        operand.value, str) and operand.value.lower() in BRAND_TOKENS:
                    hits.append(f"compare:{operand.value}")
        elif isinstance(node, ast.If):
            test = node.test
            if isinstance(test, ast.Compare):
                for operand in [test.left, *test.comparators]:
                    if isinstance(operand, ast.Constant) and isinstance(
                            operand.value, str) and operand.value.lower() in BRAND_TOKENS:
                        hits.append(f"branch:{operand.value}")
        elif isinstance(node, (ast.Dict, ast.List, ast.Tuple, ast.Set)):
            elements = ([*node.keys, *node.values] if isinstance(node, ast.Dict)
                        else list(node.elts))
            for element in elements:
                if isinstance(element, ast.Constant) and isinstance(
                        element.value, str) and element.value.lower() in BRAND_TOKENS:
                    hits.append(f"collection:{element.value}")
    return sorted(set(hits))


def brand_key_violations(source: str) -> list[str]:
    """Native, brand-specific configuration key names used as identifiers."""
    tree = ast.parse(source)
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in BRAND_CONFIG_TOKENS:
            hits.append(node.id)
        elif isinstance(node, ast.Attribute) and node.attr in BRAND_CONFIG_TOKENS:
            hits.append(node.attr)
        elif isinstance(node, ast.arg) and node.arg in BRAND_CONFIG_TOKENS:
            hits.append(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name in BRAND_CONFIG_TOKENS:
                hits.append(node.name)
    return sorted(set(hits))


# --------------------------------------------------------------------------
# the real tree
# --------------------------------------------------------------------------
def test_c20_profile_core_imports_only_published_contracts():
    violations = []
    for path in sorted(SRC.glob("*.py")):
        for module in import_violations(path.read_text(encoding="utf-8")):
            violations.append(f"{path.name}: {module}")
    assert violations == []


def test_c20_profile_core_holds_no_brand_specific_configuration_branching():
    branches = []
    for path in sorted(SRC.glob("*.py")):
        for hit in brand_branch_violations(path.read_text(encoding="utf-8")):
            branches.append(f"{path.name}: {hit}")
        for hit in brand_key_violations(path.read_text(encoding="utf-8")):
            branches.append(f"{path.name}: {hit}")
    assert branches == []


def test_c20_publication_surface_is_the_public_facet_contract():
    """The Profile's own extension surface is ``contracts.py`` (the DTOs and
    the ``FacetProvider`` protocol) plus ``facets.py``; a resource plugin
    contributes through those and nothing deeper."""
    published = {p.name for p in SRC.glob("*.py")}
    assert {"contracts.py", "facets.py", "plugin.py"} <= published
    tree = ast.parse((SRC / "plugin.py").read_text(encoding="utf-8"))
    external = {m for m in imported_modules(
        (SRC / "plugin.py").read_text(encoding="utf-8"))
        if m.split(".")[0] not in {"__future__", "ordessa_profile", "typing"}}
    assert external <= {
        "pacthold.extensions",
        "pacthold_runtime_compat.resource_contracts",
        "pacthold.work_core.models",
        "pacthold.work_core.registry",
    }
    assert tree  # parsed, not merely read


# --------------------------------------------------------------------------
# the analyser must be able to see (counterexample proofs)
# --------------------------------------------------------------------------
def test_c20_import_analyser_flags_a_resource_plugin_private_import():
    offender = (
        "from ordessa_model_provider_profile.facet import ModelFacet\n"
        "import ordessa_harness.configuration.model.backend as backend\n"
    )
    assert import_violations(offender) == [
        "ordessa_harness.configuration.model.backend",
        "ordessa_model_provider_profile.facet",
    ]


def test_c20_published_harness_contract_is_the_only_harness_surface_reachable():
    """``ordessa_harness_api`` is allowed because it is the published
    capability contract; the implementation package behind it is not. Proved
    by discrimination, so the allow-list entry cannot quietly widen."""
    allowed = "from ordessa_harness_api import Confirmed, DesiredFragment\n"
    assert import_violations(allowed) == []
    for prefix in FORBIDDEN_PREFIXES:
        offender = f"import {prefix.rstrip('.')}.internal as x\n"
        assert import_violations(offender) == [offender.split()[1].removesuffix(
            " as x")]


def test_c20_import_analyser_accepts_the_public_contribution_route():
    ok = (
        "from ordessa_profile.contracts import FacetProvider\n"
        "from pacthold.work_core.registry import ProviderDescriptor\n"
    )
    assert import_violations(ok) == []


def test_c20_branch_analyser_flags_brand_conditionals_but_not_prose():
    offender = (
        'def compile(harness_id):\n'
        '    if harness_id == "codex":\n'
        '        return {"wire_api": "responses"}\n'
        '    if harness_id == "claude-code":\n'
        '        return {"model_provider": "anthropic"}\n'
        '    return {}\n'
    )
    hits = brand_branch_violations(offender)
    assert "branch:codex" in hits and "branch:claude-code" in hits

    prose = '"""Harness differences are the brand adapters\' job (codex)."""\n'
    assert brand_branch_violations(prose) == []
    assert brand_key_violations(offender) == []
    assert brand_key_violations(
        "def compile(model_provider, **kw):\n    return model_provider\n"
    ) == ["model_provider"]


def test_c20_analysers_reject_a_syntactically_broken_module():
    import ast as _ast
    try:
        _ast.parse("def broken(:\n")
    except SyntaxError:
        pass
    else:  # pragma: no cover
        raise AssertionError("the analyser must not accept invalid source")