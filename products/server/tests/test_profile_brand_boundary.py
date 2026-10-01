"""Profile integration must not contain native brand strategy."""
import ast
from pathlib import Path

import pytest


@pytest.mark.parametrize('name', ['profile_sessions.py', 'profile_preparation.py', 'profile_configuration.py'])
def test_profile_wiring_has_no_native_brand_literals_or_brand_imports(name):
    source = Path(__file__).parents[1] / 'src/ordessa_server_product' / name
    tree = ast.parse(source.read_text())
    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and node.value in ('pi', 'codex', 'claude-code', 'codex_account_directory'):
            violations.append((node.lineno, node.value))
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith('ordessa_harness.'):
            if any(part in node.module.split('.') for part in ('pi', 'codex', 'claude')):
                violations.append((node.lineno, node.module))
    assert not violations, f'Harness strategy leaked into {name}: {violations}'
