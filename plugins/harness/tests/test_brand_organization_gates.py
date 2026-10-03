"""T007-02 pins: brand differences are organized inside the harness.

Positive facts pinned against this tree (source-inspected, not aspirational):

* Codex / Pi / Claude lifecycle, configuration and resource adaptation
  entries live inside ``plugins/harness``: every brand has a
  ``<brand>/registration.py`` factory publishing a ``BridgeConfigurationAdapter``
  for the neutral ``harness.configuration-adapters`` point
  (``configuration/model/plugin.py``), and the ``harnesses.toml`` brand rows
  declare the resource slots consumed by ``registry/schema.py`` ``ProfileSpec``
  (provider / permission / instruction / mcp / skill / hooks / memory).
* The already-top-level resource domains (``prompts``, ``memory``,
  ``command-templates``, ``extensions``, ``model-provider``, ``skills``,
  ``sandbox``) contain no *unregistered* brand comparison branch. The reverse
  scan below freezes the complete inventory of brand string literals by file
  category; a new file or branch must be registered here consciously.
* ``packages/backend/pacthold`` and ``apps/server`` ``src`` carry no brand
  literal/name/enumeration — the brand vocabulary stays out of the kernel and
  the wire host.

DRIFT registered (production untouched; current policy pinned, not judged):
* ``plugins/sandbox/api/src/ordessa_sandbox_api/platform.py:59`` holds
  ``if brand == "claude-code":`` — a brand business branch inside a
  top-level domain ``src`` (the documented Claude platform matrix). It is the
  only brand comparison branch found in the scanned domains.
* ``plugins/skills/desktop/src/view.tsx:439-441`` hardcodes the three brand
  options in a domain frontend select. It is recorded in the literal
  whitelist as current policy.
"""

from __future__ import annotations

import ast
import dataclasses
import importlib
import re
from pathlib import Path

import pytest

from ordessa_harness.registry.definitions import REGISTRY
from ordessa_harness.registry.schema import ProfileSpec

_HERE = Path(__file__).resolve()
_HARNESS_ROOT = _HERE.parents[1]
_PLUGINS_ROOT = _HARNESS_ROOT.parent
_REPO_ROOT = _PLUGINS_ROOT.parent
_HARNESS_SRC = _HARNESS_ROOT / "src" / "ordessa_harness"

_DOMAINS = (
    "prompts",
    "memory",
    "command-templates",
    "extensions",
    "model-provider",
    "skills",
    "sandbox",
)
_BRANDS = frozenset(
    {"codex", "claude", "claude-code", "pi", "hermes", "opencode", "dsh", "qwen", "kilo"}
)
_SOURCE_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".mjs")
_EXCLUDED_PATH_PARTS = (
    "node_modules",
    "__pycache__",
    ".egg-info",
    ".pytest_cache",
    "/build/",
    "/dist/",
)

#: Reverse-scan inventory: every domain ``src`` file with a non-docstring
#: Python brand literal or a quoted TypeScript/JavaScript brand literal, by
#: the category the current policy actually uses. Exact set equality below:
#: additions and removals both require a conscious update (and a DRIFT note
#: when the new hit is a brand business judgment).
_BRAND_LITERAL_CATEGORIES = {
    # brand adapter registration / per-brand adapter submodules
    "plugins/extensions/src/ordessa_extensions/adapters/contribution.py": "domain-brand-adapter",
    "plugins/prompts/src/ordessa_prompts/harness_adapters/contribution.py": "domain-brand-adapter",
    "plugins/prompts/src/ordessa_prompts/harness_adapters/capabilities.py": "support-matrix",
    "plugins/sandbox/adapters/src/ordessa_sandbox_adapters/claude_code.py": "domain-brand-adapter",
    "plugins/sandbox/adapters/src/ordessa_sandbox_adapters/codex.py": "domain-brand-adapter",
    "plugins/sandbox/adapters/src/ordessa_sandbox_adapters/matrix.py": "support-matrix",
    "plugins/sandbox/adapters/src/ordessa_sandbox_adapters/pi.py": "domain-brand-adapter",
    "plugins/skills/src/ordessa_skills/harness_adapters/__init__.py": "domain-brand-adapter-surface",
    "plugins/skills/src/ordessa_skills/harness_adapters/capabilities.py": "support-matrix",
    "plugins/skills/src/ordessa_skills/harness_adapters/claude.py": "domain-brand-adapter",
    "plugins/skills/src/ordessa_skills/harness_adapters/codex.py": "domain-brand-adapter",
    "plugins/skills/src/ordessa_skills/harness_adapters/conflict.py": "domain-brand-adapter",
    "plugins/skills/src/ordessa_skills/harness_adapters/pi.py": "domain-brand-adapter",
    # neutral inventory/declaration tables
    "plugins/extensions/src/ordessa_extensions/capabilities.py": "support-matrix",
    "plugins/memory/src/ordessa_memory/common.py": "support-matrix",
    "plugins/model-provider/profile-contribution/src/ordessa_model_provider_profile/profile_glue.py": "support-declaration",
    "plugins/model-provider/server/src/ordessa_model_provider/protocols.py": "protocol-dialect-table",
    "plugins/model-provider/server/src/ordessa_model_provider/testing.py": "test-wire-fixture",
    "plugins/sandbox/api/src/ordessa_sandbox_api/intent.py": "brand-keyed-schema-vocabulary",
    "plugins/sandbox/api/src/ordessa_sandbox_api/matrix.py": "support-matrix",
    # DRIFT: registered current-policy hits, not fixed by this pin
    "plugins/sandbox/api/src/ordessa_sandbox_api/platform.py": "DRIFT-platform-branch",
    "plugins/model-provider/desktop/src/settings.tsx": "frontend-default-draft",
    "plugins/skills/desktop/src/view.tsx": "DRIFT-frontend-static-options",
}

#: The exact brand comparison branches (any comparison operator, including
#: membership) found in the scanned domains' ``src``, keyed by repo-relative
#: path with the unparsed expression. One known DRIFT exception.
_REGISTERED_BRAND_BRANCHES = {
    "plugins/sandbox/api/src/ordessa_sandbox_api/platform.py": ("brand == 'claude-code'",),
}


def _iter_domain_src(domain: str):
    for path in sorted((_PLUGINS_ROOT / domain).rglob("*")):
        if not path.is_file() or path.suffix not in _SOURCE_SUFFIXES:
            continue
        posix = path.as_posix()
        if any(part in posix for part in _EXCLUDED_PATH_PARTS):
            continue
        if "/src/" not in posix:
            continue
        yield path


def _docstring_constant_ids(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                ids.add(id(body[0].value))
    return ids


def _iter_python_files(root: Path):
    for path in sorted(root.rglob("*.py")):
        posix = path.as_posix()
        if any(part in posix for part in _EXCLUDED_PATH_PARTS):
            continue
        yield path


def _strip_ts_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    # ``(?<!:)`` keeps URL literals like ``https://`` intact.
    return re.sub(r"(?<!:)//[^\n]*", "", text)


def _python_brand_literal_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for domain in _DOMAINS:
        for path in _iter_domain_src(domain):
            if path.suffix != ".py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            docstrings = _docstring_constant_ids(tree)
            found = [
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.Constant)
                and node.value in _BRANDS
                and id(node) not in docstrings
            ]
            if found:
                counts[path.relative_to(_REPO_ROOT).as_posix()] = len(found)
    return counts


def _ts_brand_literals() -> dict[str, tuple[str, ...]]:
    pattern = re.compile(
        r"""['"](codex|claude|claude-code|pi|hermes|opencode|dsh|qwen|kilo)['"]"""
    )
    hits: dict[str, tuple[str, ...]] = {}
    for domain in _DOMAINS:
        for path in _iter_domain_src(domain):
            if path.suffix == ".py":
                continue
            code = _strip_ts_comments(path.read_text(encoding="utf-8"))
            found = tuple(dict.fromkeys(match.group(1) for match in pattern.finditer(code)))
            if found:
                hits[path.relative_to(_REPO_ROOT).as_posix()] = found
    return hits


def _brand_branches() -> dict[str, tuple[str, ...]]:
    branches: dict[str, tuple[str, ...]] = {}
    for domain in _DOMAINS:
        for path in _iter_domain_src(domain):
            if path.suffix != ".py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            expressions: dict[str, None] = {}
            for node in ast.walk(tree):
                if not isinstance(node, ast.Compare):
                    continue
                operands = (node.left, *node.comparators)
                direct = any(
                    isinstance(item, ast.Constant) and item.value in _BRANDS
                    for item in operands
                )
                inline = any(
                    isinstance(item, (ast.Tuple, ast.Set, ast.List))
                    and any(
                        isinstance(element, ast.Constant) and element.value in _BRANDS
                        for element in item.elts
                    )
                    for item in operands
                )
                if direct or inline:
                    expressions[ast.unparse(node)] = None
            if expressions:
                branches[path.relative_to(_REPO_ROOT).as_posix()] = tuple(expressions)
    return branches


def _ts_brand_branches() -> dict[str, tuple[str, ...]]:
    compare = re.compile(
        r"""(===|!==|==|!=)\s*['"](?:codex|claude|claude-code|pi|hermes|opencode|dsh|qwen|kilo)['"]"""
        r"""|['"](?:codex|claude|claude-code|pi|hermes|opencode|dsh|qwen|kilo)['"]\s*(===|!==|==|!=)"""
    )
    switches = re.compile(
        r"""case\s+['"](?:codex|claude|claude-code|pi|hermes|opencode|dsh|qwen|kilo)['"]\s*:"""
    )
    hits: dict[str, tuple[str, ...]] = {}
    for domain in _DOMAINS:
        for path in _iter_domain_src(domain):
            if path.suffix == ".py":
                continue
            code = _strip_ts_comments(path.read_text(encoding="utf-8"))
            if compare.search(code) or switches.search(code):
                hits[path.relative_to(_REPO_ROOT).as_posix()] = ()
    return hits


def test_codex_pi_claude_rows_declare_profile_resource_slots():
    """harnesses.toml brand rows expose the registry-consumed resource slots."""
    expectations = {
        "codex": {
            "driver": "codex",
            "slots": {"provider", "permission", "instruction", "mcp", "skill", "hooks"},
            "skill_env": "CODEX_HOME",
            "mcp_key": "mcp_servers",
            "hooks_key": None,
            "memory_paths": True,
        },
        "pi": {
            "driver": "pi",
            "slots": {"instruction", "mcp", "skill"},
            "skill_env": None,
            "mcp_key": None,
            "hooks_key": None,
            "memory_paths": False,
        },
        "claude-code": {
            "driver": "claude",
            "slots": {"provider", "instruction", "mcp", "skill", "hooks"},
            "skill_env": None,
            "mcp_key": "mcpServers",
            "hooks_key": "hooks",
            "memory_paths": True,
        },
    }
    for harness_id, expected in expectations.items():
        definition = REGISTRY.get(harness_id)
        assert definition.driver == expected["driver"]
        assert definition.harness_type == harness_id
        assert set(expected["slots"]) <= set(definition.profile.slots)
        assert definition.profile.skill_target is not None
        assert "{skill_id}" in definition.profile.skill_target
        assert definition.profile.skill_env == expected["skill_env"]
        assert definition.profile.mcp_key == expected["mcp_key"]
        assert definition.profile.hooks_key == expected["hooks_key"]
        assert bool(definition.profile.memory_paths) is expected["memory_paths"]
        assert definition.launch_modes
        assert definition.continuation.kind == "native_session"
        assert {"start", "observe", "finish"} <= set(definition.capabilities)


def test_profile_spec_declares_the_resource_slot_fields():
    """registry/schema.py owns the slot vocabulary the brand rows use."""
    field_names = {field.name for field in dataclasses.fields(ProfileSpec)}
    assert {
        "native_home",
        "guest_home",
        "config_format",
        "payload_schema",
        "codec",
        "overlay_policy",
        "slots",
        "skill_target",
        "skill_env",
        "mcp_target",
        "mcp_key",
        "hooks_target",
        "hooks_key",
        "memory_paths",
    } <= field_names


def test_brand_registration_modules_publish_bridge_adapters_inside_harness():
    """Codex/Pi/Claude configuration entries are harness-internal factories."""
    expected = {
        "codex": ("codex", "assets.model-provider.codex"),
        "pi": ("pi", "assets.model-provider.pi"),
        "claude": ("claude-code", "assets.model-provider.claude"),
    }
    for module_name, (harness_id, adapter_id) in expected.items():
        module = importlib.import_module(f"ordessa_harness.{module_name}.registration")
        adapters = module.configuration_adapters()
        assert len(adapters) == 1, module_name
        adapter = adapters[0]
        assert adapter.brand == harness_id
        assert adapter.descriptor.adapter_id == adapter_id
        assert adapter.descriptor.harness_id == harness_id
        assert adapter.descriptor.facet_id == "assets.model-provider"

    for harness_id, directory in (("codex", "codex"), ("pi", "pi"), ("claude-code", "claude")):
        brand_dir = _HARNESS_SRC / directory
        assert (brand_dir / "registration.py").is_file(), harness_id
        assert (brand_dir / "configuration" / "model.py").is_file(), harness_id


def test_brand_lifecycle_entrypoints_live_inside_harness():
    """The declared lifecycle entry factories stay harness-internal."""
    from ordessa_harness import entrypoints

    for factory, harness_id in (
        ("create_codex", "codex"),
        ("create_pi", "pi"),
        ("create_claude", "claude-code"),
    ):
        plugin = getattr(entrypoints, factory)()
        assert plugin.harness_type == harness_id
        assert plugin.descriptor().id == harness_id


def test_model_provider_adapter_plugin_publishes_all_three_on_the_neutral_point():
    """configuration/model/plugin.py assembles the three brands explicitly."""
    from ordessa_harness.configuration.model.plugin import (
        CONFIGURATION_POINT,
        ModelProviderAdaptersPlugin,
    )

    registration = ModelProviderAdaptersPlugin().build(None)
    contributions = registration.contributions.contributions
    assert {item.point_id for item in contributions} == {CONFIGURATION_POINT}
    assert {item.api_version for item in contributions} == {"v1"}
    assert {item.payload.brand for item in contributions} == {"pi", "codex", "claude-code"}
    assert registration.contributions.open_points == frozenset({CONFIGURATION_POINT})


def test_top_level_domains_have_no_unregistered_brand_branches():
    """No brand business branch in a top-level domain src beyond the frozen DRIFT."""
    branches = _brand_branches()
    assert branches == _REGISTERED_BRAND_BRANCHES, (
        "brand comparison branch inventory drifted; register the new hit "
        "(and its category) consciously"
    )
    assert _ts_brand_branches() == {}


def test_top_level_domain_brand_literals_match_the_registered_category_whitelist():
    """Every brand literal in a domain src is in a categorized, frozen file."""
    actual = set(_python_brand_literal_counts()) | set(_ts_brand_literals())
    registered = set(_BRAND_LITERAL_CATEGORIES)
    assert actual == registered, (
        f"unregistered brand-literal files: {sorted(actual - registered)}; "
        f"stale whitelist entries: {sorted(registered - actual)}"
    )
    assert sum(1 for category in _BRAND_LITERAL_CATEGORIES.values() if "DRIFT" in category) == 2


@pytest.mark.parametrize(
    "root",
    (
        "packages/backend/pacthold/src",
        "apps/server/src",
    ),
)
def test_pacthold_and_server_src_carry_no_brand_enumeration(root):
    """The kernel and the wire host carry no brand literal, name or comparison."""
    scanned = 0
    offenders: list[tuple[str, int, str]] = []
    for path in _iter_python_files(_REPO_ROOT / root):
        scanned += 1
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and node.value in _BRANDS:
                offenders.append((path.as_posix(), node.lineno, repr(node.value)))
            elif isinstance(node, ast.Name) and node.id.lower() in _BRANDS:
                offenders.append((path.as_posix(), node.lineno, node.id))
            elif isinstance(node, ast.Attribute) and node.attr.lower() in _BRANDS:
                offenders.append((path.as_posix(), node.lineno, node.attr))
            elif isinstance(node, ast.Compare):
                operands = (node.left, *node.comparators)
                for item in operands:
                    if (
                        isinstance(item, ast.Constant)
                        and isinstance(item.value, str)
                        and item.value.lower() in _BRANDS
                    ):
                        offenders.append((path.as_posix(), node.lineno, ast.unparse(node)))
                    if isinstance(item, (ast.Tuple, ast.Set, ast.List)) and any(
                        isinstance(element, ast.Constant)
                        and isinstance(element.value, str)
                        and element.value.lower() in _BRANDS
                        for element in item.elts
                    ):
                        offenders.append((path.as_posix(), node.lineno, ast.unparse(node)))
    assert scanned >= 20, "expected the pacthold/server sources to be scanned"
    assert offenders == []
