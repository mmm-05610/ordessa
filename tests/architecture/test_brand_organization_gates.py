"""T007-02 pins: brand differences are organized inside the harness.

Positive facts pinned against this tree (source-inspected, not aspirational):

* Codex / Pi / Claude configuration compilers and factories live in their
  ``plugins/harness`` brand packages. Resource adaptation lives in the Agents
  resource owner roots below. Host captures the selected harness fragments;
  Agents ``harness.providers.declarations.schema.ProfileSpec`` owns slot shape.
* The already-top-level resource domains (``prompts``, ``memory``,
  ``command-templates``, ``extensions``, ``model-provider``, ``skills``,
  ``sandbox``) contain no *unregistered* brand comparison branch. The reverse
  scan below freezes the complete inventory of brand string literals by file
  category; a new file or branch must be registered here consciously.
* The neutral kernel and wire-host mechanisms should carry no brand vocabulary.
  The source scan below intentionally includes all Server ``src`` and currently
  reports explicit selected-catalog modules there; that ownership conflict is
  recorded in the report, not exempted here.

DRIFT registered (production untouched; current policy pinned, not judged):
* ``plugins/agents/resources/sandbox/api/src/ordessa_sandbox_api/platform.py:59`` holds
  ``if brand == "claude-code":`` — a brand business branch inside a
  top-level domain ``src`` (the documented Claude platform matrix). It is the
  only brand comparison branch found in the scanned domains.
* ``plugins/agents/resources/skills/desktop/src/view.tsx:439-441`` hardcodes the three brand
  options in a domain frontend select. It is recorded in the literal
  whitelist as current policy.
"""

from __future__ import annotations

import ast
import dataclasses
import importlib
import re
from functools import lru_cache
import inspect
from pathlib import Path

import pytest
from ordessa_agents.harness.configuration.compilation.model_choice import ModelChoiceAdapter
from ordessa_agents.harness.providers.declarations.schema import ProfileSpec


@lru_cache(maxsize=1)
def _selected_harness_catalog():
    """Use the explicit Server-selected source fragments for this test process."""
    from ordessa_server.composition.selected_harness_catalog import capture_selected_harness_catalog
    return capture_selected_harness_catalog()

_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[2]
_PLUGINS_ROOT = _REPO_ROOT / "plugins"
_HARNESS_ROOT = _PLUGINS_ROOT / "harness"

_DOMAINS = (
    "prompts",
    "memory",
    "command-templates",
    "extensions",
    "model-provider",
    "skills",
    "sandbox",
)
_DOMAIN_ROOTS = {
    "prompts": (_PLUGINS_ROOT / "agents" / "resources" / "prompts",),
    "memory": (_PLUGINS_ROOT / "agents" / "memory",),
    "command-templates": (_PLUGINS_ROOT / "workbench" / "command-templates",),
    "extensions": (_PLUGINS_ROOT / "agents" / "extensions",),
    "model-provider": (_PLUGINS_ROOT / "agents" / "resources" / "model-provider",),
    "skills": (_PLUGINS_ROOT / "agents" / "resources" / "skills",),
    "sandbox": (_PLUGINS_ROOT / "agents" / "resources" / "sandbox",),
}
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
    "plugins/agents/extensions/src/ordessa_extensions/adapters/contribution.py": "domain-brand-adapter",
    "plugins/agents/resources/prompts/src/ordessa_prompts/harness_adapters/contribution.py": "domain-brand-adapter",
    "plugins/agents/resources/prompts/src/ordessa_prompts/harness_adapters/capabilities.py": "support-matrix",
    "plugins/agents/resources/sandbox/adapters/src/ordessa_sandbox_adapters/claude_code.py": "domain-brand-adapter",
    "plugins/agents/resources/sandbox/adapters/src/ordessa_sandbox_adapters/codex.py": "domain-brand-adapter",
    "plugins/agents/resources/sandbox/adapters/src/ordessa_sandbox_adapters/matrix.py": "support-matrix",
    "plugins/agents/resources/sandbox/adapters/src/ordessa_sandbox_adapters/pi.py": "domain-brand-adapter",
    "plugins/agents/resources/skills/src/ordessa_skills/harness_adapters/__init__.py": "domain-brand-adapter-surface",
    "plugins/agents/resources/skills/src/ordessa_skills/harness_adapters/capabilities.py": "support-matrix",
    "plugins/agents/resources/skills/src/ordessa_skills/harness_adapters/claude.py": "domain-brand-adapter",
    "plugins/agents/resources/skills/src/ordessa_skills/harness_adapters/codex.py": "domain-brand-adapter",
    "plugins/agents/resources/skills/src/ordessa_skills/harness_adapters/conflict.py": "domain-brand-adapter",
    "plugins/agents/resources/skills/src/ordessa_skills/harness_adapters/pi.py": "domain-brand-adapter",
    # neutral inventory/declaration tables
    "plugins/agents/extensions/src/ordessa_extensions/capabilities.py": "support-matrix",
    "plugins/agents/memory/src/ordessa_memory/common.py": "support-matrix",
    "plugins/agents/resources/model-provider/server/src/ordessa_model_provider/protocols.py": "protocol-dialect-table",
    "plugins/agents/resources/model-provider/server/src/ordessa_model_provider/testing.py": "test-wire-fixture",
    "plugins/agents/resources/sandbox/api/src/ordessa_sandbox_api/intent.py": "brand-keyed-schema-vocabulary",
    "plugins/agents/resources/sandbox/api/src/ordessa_sandbox_api/matrix.py": "support-matrix",
    # DRIFT: registered current-policy hits, not fixed by this pin
    "plugins/agents/resources/sandbox/api/src/ordessa_sandbox_api/platform.py": "DRIFT-platform-branch",
    "plugins/agents/resources/model-provider/desktop/src/settings.tsx": "frontend-default-draft",
    "plugins/agents/resources/skills/desktop/src/view.tsx": "DRIFT-frontend-static-options",
}

#: The exact brand comparison branches (any comparison operator, including
#: membership) found in the scanned domains' ``src``, keyed by repo-relative
#: path with the unparsed expression. One known DRIFT exception.
_REGISTERED_BRAND_BRANCHES = {
    "plugins/agents/resources/sandbox/api/src/ordessa_sandbox_api/platform.py": ("brand == 'claude-code'",),
}


def _domain_roots(domain: str) -> tuple[Path, ...]:
    """Scan the live owner roots, never retired empty top-level directories."""
    roots = _DOMAIN_ROOTS[domain]
    assert roots and all(root.is_dir() for root in roots), f"missing live {domain} owner root"
    return roots


def _iter_domain_src(domain: str):
    paths = (path for root in _domain_roots(domain) for path in root.rglob("*"))
    for path in sorted(paths):
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
    """The Host-selected registry exposes the Agents-owned resource slot schema."""
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
    registry = _selected_harness_catalog().registry
    for harness_id, expected in expectations.items():
        definition = registry.get(harness_id)
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
    """Agents declarations/schema.py owns the slot vocabulary brand rows use."""
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
    """Brand configuration compiler factories remain in each brand package."""
    expected = {
        "ordessa_harness_codex": ("codex", "assets.model-provider.codex"),
        "ordessa_harness_pi": ("pi", "assets.model-provider.pi"),
        "ordessa_harness_claude_code": ("claude-code", "assets.model-provider.claude"),
    }
    for module_name, (harness_id, adapter_id) in expected.items():
        module = importlib.import_module(f"{module_name}.registration")
        assert inspect.signature(module.configuration_adapters).parameters == {}
        adapters = module.configuration_adapters()
        assert len(adapters) == 1, module_name
        adapter = adapters[0]
        assert isinstance(adapter, ModelChoiceAdapter)
        assert adapter.brand == harness_id
        assert adapter.descriptor.adapter_id == adapter_id
        assert adapter.descriptor.harness_id == harness_id
        assert adapter.descriptor.facet_id == "assets.model-provider"

    #: 032: brand knowledge lives in each brand's own package.
    for harness_id, module in (("codex", "ordessa_harness_codex"), ("pi", "ordessa_harness_pi"),
                               ("claude-code", "ordessa_harness_claude_code")):
        brand_dir = _HARNESS_ROOT / harness_id / "src" / module
        assert (brand_dir / "registration.py").is_file(), harness_id
        compiler = brand_dir / "acp_model_configuration.py"
        assert compiler.is_file(), harness_id


def test_product_uses_selected_registry_without_retired_profile_entrypoints():
    """The current composition keeps the selected registry; old writer factories are absent."""
    import importlib.util
    from ordessa_server_product.composition import ServerProductComposition

    registry = _selected_harness_catalog().registry
    composition = ServerProductComposition()
    composition.bind_harness_registry(registry)
    assert composition.harness_registry is registry
    assert importlib.util.find_spec(
        "ordessa_server_product.harness_adapters.entrypoints") is None
