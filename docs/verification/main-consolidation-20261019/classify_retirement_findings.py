"""Classify symbol findings with bounded import witnesses, never delete history.

Static imports below include function bodies (possible configured paths). They
are not evidence that an operation executed or that a permission was granted.
"""
import ast
from collections import Counter, deque
import importlib.util
import json
from pathlib import Path
import subprocess

ROOT = Path.cwd()
BASE = ROOT/'docs/verification/main-consolidation-20261019'


def main():
    spec = importlib.util.spec_from_file_location('workspace_inventory', ROOT/'tooling/workspace/python_workspace.py')
    workspace = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(workspace)
    projects, sources = workspace._validated_workspace(ROOT)
    raw = json.loads((BASE/'retirement-audit.json').read_text())
    modules = {}; paths = {}
    for source in sources:
        for file in source.rglob('*.py'):
            parts = list(file.relative_to(source).with_suffix('').parts)
            if parts[-1] == '__init__': parts.pop()
            if not parts or not (parts[0].startswith('ordessa_') or parts[0] in ('decision_runtime','server_plugin_api')):
                continue
            name = '.'.join(parts)
            modules[name] = file
            paths[file.relative_to(ROOT).as_posix()] = name
    graph = {name:set() for name in modules}
    dynamic = {}
    for name, file in modules.items():
        package = name if file.name == '__init__.py' else name.rpartition('.')[0]
        tree = ast.parse(file.read_text())
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import): imports.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                target = node.module or ''
                if node.level:
                    try: target = importlib.util.resolve_name('.'*node.level+target, package)
                    except (ValueError, ImportError): continue
                imports.add(target)
                imports.update(target+'.'+a.name for a in node.names if a.name != '*')
            elif isinstance(node, ast.Call) and isinstance(node.func,(ast.Name,ast.Attribute)):
                label = node.func.id if isinstance(node.func,ast.Name) else node.func.attr
                if label in ('import_module','__import__'):
                    if node.args and isinstance(node.args[0],ast.Constant) and isinstance(node.args[0].value,str):
                        imports.add(node.args[0].value)
                    else: dynamic.setdefault(name,[]).append(node.lineno)
        for target in imports:
            if target in modules: graph[name].add(target)
            parts = target.split('.')
            for index in range(1,len(parts)):
                prefix = '.'.join(parts[:index])
                if prefix in modules: graph[name].add(prefix)
    roots = ['ordessa_server.__main__','ordessa_server.entrypoints.cli',
        'ordessa_server.composition.packages_convergence','ordessa_server_product.composition']
    assert all(name in graph for name in roots)
    witnesses = {name:[name] for name in roots}; pending = deque(roots)
    while pending:
        name = pending.popleft()
        for target in sorted(graph[name]):
            if target not in witnesses:
                witnesses[target] = witnesses[name]+[target]; pending.append(target)
    explicit_history = {
        'apps/server/src/ordessa_server/composition/profile_history_views.py':
            'Explicit historical Profile projection; current Profile ACL and fixed revision retained. Existing composed_profile_service import is a separate owner dependency to migrate.',
        'packages/interfaces/system-access/bindings/src/ordessa_system_access_bindings/decision.py':
            'Read-only current Profile/Harness observations encoded as historical Decision DTOs; Unit import is OwnerProposalInput data, no UnitServices assembly.',
    }
    legitimate_environment = {
        'packages/execution/environments/src/ordessa_environments/__init__.py',
        'packages/execution/environments/src/ordessa_environments/management/__init__.py',
        'packages/execution/environments/src/ordessa_environments/management/resources.py',
    }
    records = []
    for path, findings in raw['allDistributionFindings'].items():
        name = paths.get(path); witness = witnesses.get(name)
        if '/tests/' in path:
            category = 'packaged_test_artifact'
            reason = 'Test file found beneath a broad declared source root; not itself an online runtime authority. Packaging exclusion requires separate inspection.'
        elif path in explicit_history:
            category = 'historical_read_or_data_projection'; reason = explicit_history[path]
        elif path in legitimate_environment:
            category = 'legitimate_current_environment_owner'; reason = 'Environment/EnvironmentUse belongs to the Environment owner; its presence does not prove Agents retain it.'
        elif witness:
            category = 'reachable_old_runtime_or_mixed_adapter'
            reason = 'Static path exists from a named current composition/entry root, including conditional/lazy function imports. Requires branch/authority runtime qualification; presence does not prove execution.'
        else:
            category = 'retained_without_selected_root_import_path'
            reason = 'No path in this bounded static graph. Retained implementation candidate, not a proof of unreachability through arbitrary injected ports or dynamic plugins.'
        file = ROOT/path
        tree = ast.parse(file.read_text())
        calls = sorted({node.lineno for node in ast.walk(tree) if isinstance(node,ast.Call)
            and ((isinstance(node.func,ast.Name) and node.func.id in {'UnitRuntimeOwner','UnitManager','UnitRecords','UnitServices','LocalUnitOwner'})
                 or (isinstance(node.func,ast.Attribute) and node.func.attr in {'prompt_recorded','start','create','submit','send','acquire'}))})
        records.append({'path':path,'module':name,'classification':category,'reason':reason,
            'staticRootWitness':witness,'reviewCallLines':calls,'symbolFindings':findings})
    result = {'head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        'inputFindingModules':len(records),'counts':dict(Counter(x['classification'] for x in records)),
        'roots':roots,'modulesInGraph':len(graph),'staticReachableModules':len(witnesses),
        'unresolvedDynamicImports':dynamic,'records':records,
        'acceptanceCriterion':'Old runtime authority must exit active composed and installed execution paths. Historical codecs, storage namespace keys and legitimate Environment ownership remain. No lexical-zero gate.',
        'limitations':['Static graph over-approximates function/conditional imports and does not evaluate permission predicates.',
            'Modules without a selected-root path can still be reachable through injected capabilities, entrypoint plugins or nonliteral dynamic imports.',
            'Installed CLI/help import audits prove only their executed command paths, not all configured server runtime behavior.',
            'This classification authorizes no source deletion and does not close the main integration gate.']}
    (BASE/'retirement-classification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'counts':result['counts'],'modules':len(graph),'reachable':len(witnesses)}))


if __name__ == '__main__': main()
