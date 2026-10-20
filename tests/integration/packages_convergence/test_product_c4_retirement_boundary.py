"""Enforce product retirement with an implanted executable counterexample."""
import ast
from pathlib import Path


def legacy_edges(text):
    result=[]
    for node in ast.walk(ast.parse(text)):
        if isinstance(node,(ast.Import,ast.ImportFrom)):
            modules=[n.name for n in node.names] if isinstance(node,ast.Import) else [node.module or '']
            if any('operation_journal' in module or module.endswith(('action_execution','native_action_executor','live_context','live_runtime'))
                    for module in modules):result.append(node.lineno)
        if isinstance(node,ast.Name) and node.id in {'OperationJournal','UnitRecords','ActionGrant','ConfigurationApplicationService','NativeSessionActionExecutor'}:
            result.append(node.lineno)
    return result


def test_product_no_legacy_executor_or_journal_and_probe_is_not_vacuous():
    root=Path('apps/server/deployment/default-product/src/ordessa_server_product')
    composition=Path('apps/server/src/ordessa_server/composition')
    assert root.is_dir() and composition.is_dir()
    assert tuple(root.rglob('*.py')) and tuple(composition.rglob('*.py'))
    assert legacy_edges('from ordessa_execution_agents.harness.records.operation_journal import OperationJournal\nx=OperationJournal("x")')
    assert legacy_edges('from .live_runtime import NativeLiveModelRuntime')
    offenders={str(p):legacy_edges(p.read_text())
               for owner in (root,composition) for p in owner.rglob('*.py')}
    assert not {p:lines for p,lines in offenders.items() if lines}
    for name in ('acp_channel/native_action_executor.py','acp_channel/pi_action_executor.py',
            'harness_adapters/application/action_execution.py',
            'harness_adapters/configuration/model/live_runtime.py','harness_adapters/configuration/model/live_context.py'):
        assert not (root/name).exists()
