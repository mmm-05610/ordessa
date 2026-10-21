#!/usr/bin/env python3
"""Read-only static retirement inventory; writes only the explicitly chosen receipt.

Not a test or proof of runtime reachability. No imports of product code, subprocess,
network, model call, service access, dependency installation or Git mutation.
"""
from __future__ import annotations
import argparse
import ast
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tokenize

SCHEMA = 'ordessa-retirement-scan/1'
RULES = {
    'unit_module': r'\bordessa_units(?:\.[A-Za-z_][\w]*)*\b|\bordessa-units\b',
    'unit_owner': r'\b(?:UnitServices|unit_services|UnitManager|UnitRecords|OperationJournal|UnitOwnerEvidence|UnitRuntimeProvider|[A-Za-z]*RuntimeProvider|LocalUnitInvocationAuthority|UnitExecutionConsumer|composed_profile_service|publish_preparation|publish_unit|resolve_unit_reference|authorize_acp_turn_query)\b',
    'unit_identity': r'\b(?:UnitRef|AgentUnitRef|unitRef|unit_ref|unit_ref_bytes|unitId|unit_id|harnessUnitRef|reviewer_unit_ref|author_unit_ref|ownerProviderRef|harness_unit_ref)\b',
    'legacy_agent_harness': r'\bordessa_agents\.harness(?:\.[A-Za-z_][\w]*)*\b',
    'legacy_execution_api': r'\bordessa_execution_api(?:\.[A-Za-z_][\w]*)*\b|\bordessa-execution-api\b',
    'environment_authority': r'\b(?:EnvironmentUse|EnvironmentRef|UseRef|ResourceUsePort|EnvironmentProfileStore|EnvironmentAdmission|environmentNamespace|environment_namespace)\b',
    'kernel_environment_runtime': r'\b(?:Environment|EnvironmentKernel|KernelEnvironment|create_environment|open_environment)\b',
    'legacy_decision_graph': r'\b(?:TrustedFlow|DecisionRuntime|DecisionManager|GraphRunner|pydantic_graph)\b|\bordessa_execution_decision\.runtime(?:\.[A-Za-z_][\w]*)*\b',
    'typed_environment_host': r'\bordessa_interfaces\.(?:environments|assembly\.environments|operations\.environments|queries\.environments|projections\.environments)(?:\.[A-Za-z_][\w]*)*\b',
    'legacy_dispatch_contract': r'\b(?:DispatchBinding|ExecutionRecordRef|decode_dispatch|encode_dispatch|_UNIT_REF|UnitExecutionObservationPort|RecordedUnitReviewerSource)\b',
    'borrowed_environment_authority': r'\b(?:_environment|environment_kernel|_admission|environment_admission|EnvironmentScope|EnvironmentRequest|_domain_store)\b',
    'agent_publication_seam': r'\b(?:publish_instance_binding|publish_started_instance|_launch_once|AgentInstanceRef)\b',
}
COMPILED = {key: re.compile(value) for key, value in RULES.items()}
# Names only. Every actually excluded path is inventoried in the receipt.
GENERATED_DIRS = {'.git', '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache',
                  'node_modules', 'dist', 'build', 'coverage', '.next', '.turbo',
                  'htmlcov', '.tox', '.nox', '.venv', 'venv', 'env'}
# Registered user data exceptions: never inspect credential/session contents.
USER_DATA = {'.c1-001-runtime', '.c1-001-secrets', 'runtime/native-pi-user'}
OUTPUTS = {'docs/implementation/packages-convergence-20261019/evidence/retirement-scan.json',
           'docs/implementation/packages-convergence-20261019/RETIREMENT-SCAN.md'}
HISTORY = {
    ('packages/engineering/src/ordessa_engineering/domain/changes/agent_dispatch_codec.py', 'read_historical_dispatch'),
}


def classify(path, family, syntax, context, symbol):
    parts = Path(path).parts
    if path == 'tests/integration/packages_convergence/retirement_scan.py':
        return 'scan_rule_self_reference', 'Inventory implementation, never product runtime.'
    if 'tests' in parts or 'test' in parts or Path(path).name.startswith('test_'):
        return 'test_assertion_or_unported_test', 'Tests are preserved; presence alone does not distinguish counterexample from unported execution.'
    if (path, context) in HISTORY:
        return 'historical_read_explicit_boundary', 'Exact read_historical_dispatch function seals original v1 bytes/digest; no blanket legacy-codec exemption.'
    if syntax in {'comment', 'docstring'}:
        return 'source_comment_not_execution', 'Text only; not an executable symbol edge.'
    if Path(path).suffix.lower() in {'.md', '.rst', '.txt', '.adoc'} or path.startswith(('docs/', 'specs/')):
        return 'documentation_or_evidence', 'Historical/current document or stored receipt; not executable proof.'
    if path.startswith(('.evidence/', 'evidence/')):
        return 'documentation_or_evidence', 'Stored evidence/source snapshot; inventoried, not mistaken for a current runtime module.'
    if path.startswith('packages/execution/units/src/'):
        return 'retired_runtime_source_still_present', 'Independent Units implementation still physically exists; not a historical-reader exemption.'
    if family == 'legacy_agent_harness' and symbol == 'ordessa_agents.harness.providers.catalog':
        return 'current_sdk_catalog_verified_source', 'Exact new SDK-only immutable HarnessCatalog inspected; the old-looking namespace is not itself a Unit runtime fallback.'
    if family == 'borrowed_environment_authority' and symbol == '_admission' and path == 'packages/execution/agents/src/ordessa_agents/profiles/management/service.py':
        return 'current_profile_external_admission_port', 'ProfileService explicit Profile admission port; this private field does not by itself borrow kernel Environment.'
    if family == 'agent_publication_seam':
        if path.startswith('packages/execution/agents/src/'):
            return 'current_agent_owner_or_publication_review', 'Original Agent source; manual publication/_launch_once surfaces require separate call-site review.'
        return 'agent_consumer_or_publication_review', 'Current identity or publication consumer; classify with enclosing call/import, not name alone.'
    if family in {'environment_authority', 'borrowed_environment_authority'}:
        if symbol in {'environmentNamespace', 'environment_namespace'}:
            return 'persisted_namespace_data_not_authority', 'Existing namespace partition/serialized key; it is not by itself Environment runtime authority.'
        if path.startswith(('packages/execution/environments/', 'plugins/environments/')):
            return 'environment_owner_authority', 'Environment/Use authority belongs here; ownership is not a retirement finding.'
        if path.startswith('packages/execution/agents/src/'):
            return 'agent_boundary_review_required', 'Namespace data may be retained; concrete Environment/Use authority must not enter agents.'
        if path.startswith('apps/server/src/ordessa_server/adapters/agents/'):
            return 'external_environment_endpoint_adapter', 'External adapter may own Environment/Use; Agent input must remain restricted endpoints.'
    if path.startswith(('tooling/', 'scripts/', 'packaging/')) or '/tooling/' in path or '/production.py' in path:
        return 'offline_tooling_or_template_review', 'May be explicitly invoked tooling; not automatically online, and not silently excluded.'
    if Path(path).suffix.lower() in {'.toml', '.json', '.yaml', '.yml', '.lock'}:
        return 'assembly_dependency_or_persisted_schema_review', 'Dependency/registration/persistence data may still activate old code; not a historical exemption.'
    return 'online_execution_or_contract_candidate', 'Executable/import/schema reference outside an explicit historical read boundary; runtime reachability not proven.'


def matches(value):
    for family, pattern in COMPILED.items():
        for match in pattern.finditer(value):
            yield family, match.group()


def python_nodes(tree):
    """Yield precise symbol locations and nearest lexical class/function context."""
    doc_ids = {id(owner.body[0].value) for owner in ast.walk(tree)
               if isinstance(owner, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
               and owner.body and isinstance(owner.body[0], ast.Expr)
               and isinstance(owner.body[0].value, ast.Constant)}
    def walk(node, parents=()):
        context = '.'.join(parents)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield node.lineno, node.name, 'definition', context or node.name
            parents = parents + (node.name,)
            context = '.'.join(parents)
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name, 'import', context
        elif isinstance(node, ast.ImportFrom):
            module = '.' * node.level + (node.module or '')
            yield node.lineno, module, 'import', context
            for alias in node.names:
                yield node.lineno, alias.name, 'imported_symbol', context
        elif isinstance(node, ast.Name):
            yield node.lineno, node.id, 'identifier', context
        elif isinstance(node, ast.Attribute):
            yield node.lineno, node.attr, 'attribute', context
        elif isinstance(node, ast.arg):
            yield node.lineno, node.arg, 'parameter', context
        elif isinstance(node, ast.keyword) and node.arg:
            yield node.lineno, node.arg, 'keyword', context
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            # Docstrings are classified separately, including multiline line offsets.
            is_doc = id(node) in doc_ids
            for offset, line in enumerate(node.value.splitlines()):
                yield node.lineno + offset, line, 'docstring' if is_doc else 'string_literal', context
        for child in ast.iter_child_nodes(node):
            yield from walk(child, parents)
    yield from walk(tree)


def module_name(relative):
    path = Path(relative)
    parts = list(path.with_suffix('').parts)
    if 'src' not in parts:
        return None
    parts = parts[parts.index('src') + 1:]
    if parts and parts[-1] == '__init__':
        parts.pop()
    return '.'.join(parts) or None


def scan(root):
    started = datetime.now(timezone.utc).isoformat()
    exclusions, files, findings, imports, failures, unstable = [], [], [], [], [], []
    module_files = defaultdict(list)
    for current, dirs, names in os.walk(root, followlinks=False):
        for name in list(dirs):
            path = Path(current) / name
            rel = path.relative_to(root).as_posix()
            reason = None
            if path.is_symlink():
                reason = 'symlink_directory_not_followed'
            elif name in GENERATED_DIRS or name.startswith(('.venv-', 'venv-')) or name.endswith(('.egg-info', '.dist-info')):
                reason = 'generated_dependency_environment_or_git'
            elif name in {'worktree', 'worktrees', '.worktrees', 'backup', 'backups'}:
                reason = 'nested_worktree_or_backup'
            elif rel in USER_DATA:
                reason = 'registered_user_data_not_source'
            if reason:
                dirs.remove(name)
                exclusions.append({'path': rel, 'reason': reason})
        for name in sorted(names):
            path = Path(current) / name
            rel = path.relative_to(root).as_posix()
            if rel == '.git':
                exclusions.append({'path': rel, 'reason': 'git_metadata_file'})
                continue
            if rel in OUTPUTS:
                exclusions.append({'path': rel, 'reason': 'scan_output_avoids_recursive_self_evidence'})
                continue
            if path.is_symlink():
                exclusions.append({'path': rel, 'reason': 'symlink_file_not_followed'})
                continue
            try:
                before = path.stat()
                raw = path.read_bytes()
                after = path.stat()
            except OSError as exc:
                failures.append({'path': rel, 'reason': type(exc).__name__})
                continue
            if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
                unstable.append(rel)
            receipt = {'path': rel, 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
            files.append(receipt)
            if b'\0' in raw:
                receipt['scan'] = 'binary_nul_not_text_scanned'
                continue
            try:
                source = raw.decode('utf-8')
            except UnicodeDecodeError:
                receipt['scan'] = 'non_utf8_not_text_scanned'
                continue
            receipt['scan'] = 'utf8_text'
            lines = source.splitlines()
            events = {}
            def add(line, value, syntax, context=''):
                for family, symbol in matches(value):
                    key = (line, family, symbol)
                    # AST evidence takes priority over lexical fallback.
                    if key not in events:
                        category, reason = classify(rel, family, syntax, context, symbol)
                        events[key] = {'path': rel, 'line': line, 'family': family,
                                       'symbol': symbol, 'syntax': syntax, 'context': context,
                                       'category': category, 'reason': reason,
                                       'excerpt': lines[line - 1].strip()[:240] if 0 < line <= len(lines) else ''}
            if path.suffix == '.py':
                try:
                    tree = ast.parse(source, filename=rel)
                except (SyntaxError, ValueError, RecursionError) as exc:
                    failures.append({'path': rel, 'reason': type(exc).__name__, 'line': getattr(exc, 'lineno', None),
                                     'fallback': 'lexical_scan_still_performed'})
                else:
                    receipt['scan'] = 'python_ast_and_text'
                    module = module_name(rel)
                    if module and rel.startswith(('apps/', 'products/', 'packages/', 'plugins/')) and 'tests' not in Path(rel).parts:
                        module_files[module].append(rel)
                    for line, value, syntax, context in python_nodes(tree):
                        add(line, value, syntax, context)
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Import):
                            for alias in node.names:
                                imports.append({'path': rel, 'line': node.lineno, 'module': alias.name, 'kind': 'import'})
                        elif isinstance(node, ast.ImportFrom):
                            imported = node.module or ''
                            if node.level and module:
                                package = module if path.name == '__init__.py' else module.rpartition('.')[0]
                                components = package.split('.')
                                imported = '.'.join(components[:len(components) - node.level + 1] + ([imported] if imported else []))
                            imports.append({'path': rel, 'line': node.lineno, 'module': imported,
                                            'names': [a.name for a in node.names], 'kind': 'from'})
                        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                              and node.func.attr == 'import_module') or (isinstance(node, ast.Call)
                              and isinstance(node.func, ast.Name) and node.func.id == '__import__'):
                            literal = node.args[0].value if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str) else None
                            imports.append({'path': rel, 'line': node.lineno, 'module': literal, 'kind': 'dynamic_literal' if literal else 'dynamic_unresolved'})
            if path.suffix == '.py':
                try:
                    for token in tokenize.generate_tokens(io.StringIO(source).readline):
                        if token.type == tokenize.COMMENT:
                            add(token.start[0], token.string, 'comment')
                except (tokenize.TokenError, IndentationError):
                    pass  # AST error already recorded; lexical fallback still covers file.
            for line, text in enumerate(lines, 1):
                add(line, text, 'comment' if path.suffix == '.py' and text.lstrip().startswith('#') else 'lexical_text')
            findings.extend(events.values())
    findings.sort(key=lambda item: (item['path'], item['line'], item['family'], item['symbol']))
    relevant_imports = []
    for item in imports:
        module = item['module'] or ''
        if any(matches(module)) or module.startswith('ordessa_') or item['kind'] == 'dynamic_unresolved':
            candidates = module_files.get(module, [])
            item['local_target'] = candidates[0] if len(candidates) == 1 else None
            if len(candidates) > 1:
                item['ambiguous_local_targets'] = candidates
            if not item['local_target'] and item['kind'] == 'from':
                item['local_member_targets'] = {name: module_files[module + '.' + name] for name in item.get('names', ()) if module + '.' + name in module_files}
            relevant_imports.append(item)
    production_categories = {'online_execution_or_contract_candidate', 'retired_runtime_source_still_present',
                             'agent_boundary_review_required', 'assembly_dependency_or_persisted_schema_review'}
    production = [item for item in findings if item['category'] in production_categories]
    grouped = defaultdict(list)
    for item in production:
        grouped[item['path']].append(item['line'])
    return {'schemaVersion': SCHEMA, 'root': str(root), 'startedAt': started,
            'finishedAt': datetime.now(timezone.utc).isoformat(), 'retirementComplete': False,
            'interpretation': 'Conservative static candidates, not test results or proof that every file is reachable. Retained live Units implementation and consumers prohibit a retirement-complete claim.',
            'rules': RULES, 'historicalAllowlist': [{'path': p, 'context': c} for p,c in sorted(HISTORY)],
            'limitations': ['No runtime imports, tests, dynamic tracing, dependency installation, network/model/service calls or Git mutation.',
                'All UTF-8 regular files walked; Python AST plus lexical scan. Other languages/config/documents receive lexical scan only.',
                'Binary/non-UTF8 files are hashed/inventoried but not searched; symlinks are not followed.',
                'Excluded paths are explicit below. Registered credential/run-data exceptions are not source and never read.',
                'AST dynamic import strings are recorded; computed imports, reflection, external packages, entrypoint execution and actual reachability require review.',
                'Names and serialized Unit fields may be legitimate historical data; only the exact historical function allowlist is classified read-only, never whole legacy modules.',
                'Concurrent writers make this a per-file hash snapshot, not atomic repository state. Re-run after integration changes.',
                'Source excerpts are bounded at 240 characters; hashes and line numbers identify full local evidence.'],
            'counts': {'files': len(files), 'findings': len(findings), 'categories': dict(Counter(i['category'] for i in findings)),
                       'families': dict(Counter(i['family'] for i in findings)), 'reviewCandidateFiles': len(grouped),
                       'excludedPaths': len(exclusions), 'readOrParseFailures': len(failures), 'unstableReads': len(unstable)},
            'reviewCandidateFiles': [{'path': p, 'lines': sorted(set(lines))} for p, lines in sorted(grouped.items())],
            'ambiguousLocalModules': {m:paths for m,paths in module_files.items() if len(paths)>1},
            'findings': findings, 'imports': relevant_imports, 'files': sorted(files, key=lambda item:item['path']),
            'excludedPaths': sorted(exclusions, key=lambda item:item['path']), 'failures': failures, 'unstableReads': unstable}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output.resolve()
    if not output.is_relative_to(root):
        parser.error('receipt must stay inside the selected source tree')
    result = scan(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'output': str(output), 'counts': result['counts'], 'retirementComplete': False}, ensure_ascii=False))

if __name__ == '__main__':
    main()
