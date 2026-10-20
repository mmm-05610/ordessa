"""Reproduce the non-vacuous physical-source retirement inventory, without imports.

This is an inventory, not proof that dynamic entry points cannot reach a module.
Run from the checkout root with the existing workspace Python environment.
"""
import ast
import importlib.util
import json
from pathlib import Path


SYMBOLS = frozenset({'UnitRef', 'UnitManager', 'UnitRecords', 'UnitServices',
    'UnitSpec', 'LocalUnitOwner', 'EnvironmentUse', 'Environment',
    'OperationJournal', 'NativeSessionActionExecutor', 'ConfigurationApplicationService'})


def edges(text):
    result = []
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith('ordessa_units'):
                    result.append({'line': node.lineno, 'kind': 'unit-module', 'value': alias.name})
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ''
            if module.startswith('ordessa_units'):
                result.append({'line': node.lineno, 'kind': 'unit-module', 'value': module})
            for alias in node.names:
                if alias.name in SYMBOLS:
                    result.append({'line': node.lineno, 'kind': 'legacy-symbol', 'value': alias.name})
        elif isinstance(node, ast.Name) and node.id in SYMBOLS:
            result.append({'line': node.lineno, 'kind': 'legacy-symbol', 'value': node.id})
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in {
                'harnessUnitRef', 'unitRef', 'environmentUse', 'unit_manager', 'unit_records'}:
            result.append({'line': node.lineno, 'kind': 'legacy-field', 'value': node.value})
    return sorted({(e['line'], e['kind'], e['value']) for e in result})


def main():
    root = Path.cwd()
    spec = importlib.util.spec_from_file_location('workspace_inventory', root/'tooling/workspace/python_workspace.py')
    workspace = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(workspace)
    projects, sources = workspace._validated_workspace(root)
    files = sorted({p for source in sources for p in source.rglob('*.py')})
    assert files and len(projects) == 53
    assert edges('from ordessa_units.api import UnitManager\nfrom x import EnvironmentUse\nx=OperationJournal("x")')
    findings, errors = {}, {}
    for path in files:
        try:
            found = edges(path.read_text(encoding='utf-8'))
        except (SyntaxError, UnicodeError) as error:
            errors[str(path.relative_to(root))] = type(error).__name__
            continue
        if found:
            findings[str(path.relative_to(root))] = [
                {'line': line, 'kind': kind, 'value': value} for line, kind, value in found]
    host = {path: found for path, found in findings.items() if path.startswith((
        'apps/server/src/', 'apps/server/deployment/default-product/src/',
        'packages/interfaces/channels/cli/src/'))}
    selected = [
        'apps/server/src/ordessa_server/__main__.py',
        'apps/server/src/ordessa_server/entrypoints/http.py',
        'apps/server/src/ordessa_server/entrypoints/cli.py',
        'apps/server/src/ordessa_server/composition/agent_owner.py',
        'apps/server/src/ordessa_server/composition/packages_convergence.py',
        'apps/server/deployment/default-product/src/ordessa_server_product/composition.py',
        'packages/interfaces/channels/cli/src/ordessa_cli_runtime/runtime.py',
    ]
    assert all((root/path).is_file() for path in selected)
    output = {'projects': len(projects), 'pythonFiles': len(files), 'parseErrors': errors,
        'implantedCounterexampleDetected': True, 'hostFindings': host,
        'allDistributionFindings': findings,
        'selectedEntryDirectFindings': {path: findings[path] for path in selected if path in findings},
        'verdict': 'INVENTORY_ONLY_AUTHORITY_EXIT_UNDETERMINED',
        'symbolPresence': 'PRESENT' if findings else 'NO_STATIC_FINDINGS',
        'classification': 'retirement-classification.json',
        'qualification': 'All enumerated production Python source roots were scanned. Direct-entry findings do not establish transitive/dynamic reachability. Historical Unit codecs/stores and still-unmigrated online consumers are both retained in the full inventory; no exclusions manufacture a green verdict.'}
    destination = root/'docs/verification/main-consolidation-20261019/retirement-audit.json'
    destination.write_text(json.dumps(output, indent=2)+'\n')
    print(json.dumps({'projects': len(projects), 'files': len(files), 'hostModules': len(host),
        'distributionModulesWithFindings': len(findings), 'parseErrors': len(errors),
        'selectedEntryDirectFindings': len(output['selectedEntryDirectFindings']),
        'verdict': output['verdict']}))


if __name__ == '__main__':
    main()
