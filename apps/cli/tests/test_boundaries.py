"""The lower CLI closure imports no Unit, Engineering, Server or old runtime."""
from __future__ import annotations

import ast
from pathlib import Path

FORBIDDEN = ('ordessa_units', 'ordessa_engineering', 'ordessa_server', 'pacthold',
             'ordessa_kernel', 'ordessa_agent')
CLI = Path(__file__).resolve().parents[1] / 'src' / 'ordessa_agent_tools'
CAPABILITY = (Path(__file__).resolve().parents[3] / 'packages' / 'execution' / 'agents'
              / 'src' / 'ordessa_execution_agents' / 'capability')


def imported_modules(path):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module)
    return modules


def violations(source_root):
    found = []
    for path in Path(source_root).rglob('*.py'):
        for module in imported_modules(path):
            root = module.split('.')[0]
            if any(root == name or root.startswith(name + '_') for name in FORBIDDEN):
                found.append((str(path), module))
    return found


def test_cli_and_capability_adapters_have_no_upper_runtime_imports():
    assert violations(CLI) == []
    assert violations(CAPABILITY) == []


def test_the_same_check_detects_a_planted_old_import(tmp_path):
    planted = tmp_path / 'planted.py'
    planted.write_text('from ordessa_units.records import UnitRecords\n')
    assert violations(tmp_path) == [(str(planted), 'ordessa_units.records')]


def test_only_the_cli_distribution_registers_the_ordessa_console():
    import tomllib
    root = Path(__file__).resolve().parents[3]
    owners = []
    for path in root.rglob('pyproject.toml'):
        if any(part in ('.venv', 'node_modules', 'build') for part in path.parts):
            continue
        try:
            data = tomllib.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        scripts = data.get('project', {}).get('scripts', {})
        if 'ordessa' in scripts:
            owners.append((str(path.relative_to(root)), scripts['ordessa']))
    assert owners == [('apps/cli/pyproject.toml', 'ordessa_agent_tools.cli:main')]
