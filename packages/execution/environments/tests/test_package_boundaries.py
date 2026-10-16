"""Run this against source and installed wheel, including deliberate violations."""
import ast
from pathlib import Path
import ordessa_environments


FORBIDDEN = {'pacthold','ordessa_units','ordessa_execution_agents','ordessa_server',
    'ordessa_interfaces','ordessa_engineering','decision_runtime','ordessa_infrastructure'}


def violations(source):
    result=[]
    for node in ast.walk(ast.parse(source)):
        if isinstance(node,ast.Import):roots=[alias.name.split('.')[0] for alias in node.names]
        elif isinstance(node,ast.ImportFrom) and node.level==0:roots=[(node.module or '').split('.')[0]]
        else:continue
        result.extend(root for root in roots if root in FORBIDDEN or root.startswith(('ordessa_harness_','ordessa_environments_')))
    return result


def test_all_core_modules_are_independent_of_product_and_concrete_plugins():
    root=Path(ordessa_environments.__file__).parent
    assert list(root.rglob('*.py'))
    offenders={str(path):violations(path.read_text()) for path in root.rglob('*.py')}
    assert not {path:items for path,items in offenders.items() if items}


def test_injected_plugin_and_upper_layer_imports_are_detected():
    assert violations('from ordessa_environments_openshell.provider import OpenShellEnvironmentProvider') == ['ordessa_environments_openshell']
    assert violations('import ordessa_units.records\nfrom pacthold import Environment') == ['ordessa_units','pacthold']
    assert not violations('import sqlite3\nfrom .resources import EnvironmentManager')
