"""Boundary guard: the generic host has no concrete owner imports (AST scan)."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def _generic_file(relative):
    if relative.startswith('system_access/'):
        return ROOT / 'system-access/src/ordessa_interfaces' / relative
    if relative == 'channels/cli.py':
        return ROOT / 'channels/cli/src/ordessa_interfaces/channels/cli/__init__.py'
    if relative == 'channels/mcp.py':
        return ROOT / 'channels/mcp/src/ordessa_interfaces/channels/mcp/__init__.py'
    return ROOT / 'src/ordessa_interfaces' / relative
GENERIC = (
    'system_access/registry.py', 'system_access/discovery.py',
    'system_access/operations.py', 'system_access/queries.py',
    'system_access/projections.py', 'system_access/assembly.py',
    'channels/cli.py', 'channels/mcp.py',
    'transport/__init__.py', 'transport/loopback.py',
)
FORBIDDEN = (
    'ordessa_environments', 'ordessa_engineering', 'ordessa_server',
    'ordessa_execution_agents', 'ordessa_units', 'plugins',
)


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                names.add(node.module)
    return names


def test_generic_host_imports_no_concrete_owner():
    violations: list[str] = []
    for relative in GENERIC:
        path = _generic_file(relative)
        assert path.is_file(), relative
        for name in _imported_modules(path):
            head = name.split('.')[0]
            if head in FORBIDDEN:
                violations.append(f'{relative}: {name}')
    assert violations == []


def test_contracts_distribution_is_standard_library_only():
    contracts = Path(__file__).resolve().parents[1] / 'contracts' / 'src' / 'ordessa_interfaces_contracts'
    tree = ast.parse((contracts / 'capability.py').read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split('.')[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split('.')[0])
    assert imported <= set(sys.stdlib_module_names) | {'__future__'}
