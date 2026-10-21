"""Boundary policy for ordessa_environments.

environments is an execution owner and may reuse business-neutral
infrastructure (encoding, identifiers, explicit SQLite connections,
entry-point discovery) because infrastructure carries no business policy.
It must still never depend on upper layers, other execution owners or
concrete providers.

``definitions/`` stays contract-only: its modules may import only the
standard library, relative modules and the pure infrastructure subpackages
``ordessa_infrastructure.encoding`` and ``ordessa_infrastructure.identifiers``.
Stateful or IO infrastructure (database/filesystem/process/security/
discovery) belongs outside the contract surface.

Run this against source and installed wheel, including deliberate violations.
"""
import ast
from pathlib import Path
import sys
import ordessa_environments


FORBIDDEN = {'pacthold','ordessa_units','ordessa_agents','ordessa_server',
    'ordessa_interfaces','ordessa_engineering','ordessa_decision'}
PURE_INFRASTRUCTURE = ('ordessa_infrastructure.encoding','ordessa_infrastructure.identifiers')
DEFINITIONS = Path(ordessa_environments.__file__).parent / 'definitions'


def violations(source):
    result=[]
    for node in ast.walk(ast.parse(source)):
        if isinstance(node,ast.Import):roots=[alias.name.split('.')[0] for alias in node.names]
        elif isinstance(node,ast.ImportFrom) and node.level==0:
            roots=[(node.module or '').split('.')[0]]
        else:continue
        result.extend(root for root in roots if root in FORBIDDEN or root.startswith(('ordessa_harness_','ordessa_environments_')))
    return result


def definition_violations(source):
    """Absolute import targets a definitions module may not reference, in order."""
    result=[]
    for node in ast.walk(ast.parse(source)):
        if isinstance(node,ast.Import):
            modules=[alias.name for alias in node.names]
        elif isinstance(node,ast.ImportFrom):
            if node.level:
                continue
            modules=[node.module or '<missing module>']
        else:
            continue
        for module in modules:
            if module.split('.')[0] in sys.stdlib_module_names:
                continue
            if any(module == allowed or module.startswith(allowed + '.') for allowed in PURE_INFRASTRUCTURE):
                continue
            result.append(module)
    return result


def test_all_core_modules_are_independent_of_product_and_concrete_plugins():
    root=Path(ordessa_environments.__file__).parent
    assert list(root.rglob('*.py'))
    offenders={str(path):violations(path.read_text()) for path in root.rglob('*.py')}
    assert not {path:items for path,items in offenders.items() if items}


def test_injected_plugin_and_upper_layer_imports_are_detected():
    assert violations('from ordessa_environments_openshell.provider import OpenShellEnvironmentProvider') == ['ordessa_environments_openshell']
    assert violations('import ordessa_units.records\nfrom pacthold import Environment') == ['ordessa_units','pacthold']
    assert violations('from ordessa_agents.sandbox import Sandbox') == ['ordessa_agents']
    assert not violations('import sqlite3\nfrom .resources import EnvironmentManager')
    assert not violations('from ordessa_infrastructure.database.sqlite import create_connection')


def test_definitions_import_only_stdlib_and_pure_infrastructure():
    assert list(DEFINITIONS.rglob('*.py'))
    offenders={str(path):definition_violations(path.read_text()) for path in DEFINITIONS.rglob('*.py')}
    assert not {path:items for path,items in offenders.items() if items}


def test_definitions_purity_guard_flags_stateful_infrastructure_and_upper_layers():
    assert definition_violations('from ordessa_infrastructure.encoding.content_identity import digest') == []
    assert not definition_violations('from ordessa_infrastructure.identifiers import stable_id')
    assert not definition_violations('import dataclasses\nfrom .models import BackendObservation')
    assert definition_violations('from ordessa_infrastructure.database import create_connection') == ['ordessa_infrastructure.database']
    assert definition_violations('from ordessa_infrastructure.database.sqlite import create_connection') == ['ordessa_infrastructure.database.sqlite']
    assert definition_violations('from ordessa_infrastructure.process import launch') == ['ordessa_infrastructure.process']
    assert definition_violations('import ordessa_infrastructure.discovery') == ['ordessa_infrastructure.discovery']
    assert definition_violations('from ordessa_infrastructure import filesystem') == ['ordessa_infrastructure']
    assert definition_violations('from ordessa_units.records import UnitRecord') == ['ordessa_units.records']
