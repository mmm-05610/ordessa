"""Import-boundary purity: the extensions package imports nothing it
must not (AGENTS.md rule 3 — plugins consume published contracts, never
host internals)."""
from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "ordessa_extensions"

ALLOWED_TOP_LEVEL = {
    # stdlib
    "dataclasses", "typing", "hashlib", "json", "re", "types", "__future__",
    # published contracts (AGENTS.md rule 3: plugins import platform
    # contracts, never host internals)
    "server_plugin_api", "ordessa_harness_api",
    # own package
    "ordessa_extensions",
}

FORBIDDEN_PREFIXES = (
    "ordessa_server", "ordessa_harness.", "ordessa_skills",
    "ordessa_prompts", "ordessa_subagents", "pacthold",
    "ordessa_profile", "ordessa_permissions",
)


def _imports(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                yield node.module


def test_no_module_imports_a_forbidden_root():
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for module in _imports(tree):
            root = module.split(".")[0]
            if root not in ALLOWED_TOP_LEVEL:
                offenders.append(f"{path.name}: {module}")
            for prefix in FORBIDDEN_PREFIXES:
                if module == prefix or module.startswith(prefix):
                    offenders.append(f"{path.name}: {module}")
    assert offenders == []


def test_expected_modules_exist():
    modules = {path.relative_to(SRC).as_posix()
               for path in SRC.rglob("*.py")}
    for expected in ("__init__.py", "definitions.py", "security.py",
                     "approval.py", "loader.py", "capabilities.py",
                     "blocking.py", "plugin.py", "wire.py",
                     "error_families.py",
                     "adapters/contribution.py"):
        assert expected in modules


def test_the_sweep_actually_detects_a_forbidden_import():
    # self-test of the sweep: a synthetic module importing a host
    # internal is flagged (guards the guard, review round 4)
    import textwrap
    bad = ast.parse(textwrap.dedent("""
        import ordessa_harness.registry
        from ordessa_server import something
    """))
    caught = [m for m in _imports(bad)
              if m.startswith(FORBIDDEN_PREFIXES)
              or m.split(".")[0] not in ALLOWED_TOP_LEVEL]
    assert set(caught) == {"ordessa_harness.registry", "ordessa_server"}
