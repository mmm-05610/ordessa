import ast
from pathlib import Path
import subprocess
import sys

import pytest

from ordessa_infrastructure.security import windows_dpapi
from ordessa_infrastructure.database import migrations
from ordessa_infrastructure.security import secrets


BASELINE = Path(__file__).resolve().parents[3] / 'docs/implementation/nightly/evidence/infrastructure-kernel-retirement-20261012/source-baseline'


def definition(path, name, *, member=None):
    tree = ast.parse(Path(path).read_text())
    value = next(node for node in tree.body if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name == name)
    if member:
        value = next(node for node in value.body if isinstance(node, ast.FunctionDef) and node.name == member)
    return value


@pytest.mark.parametrize('member', ['import_file', 'read', 'delete', '_unprotect', '_protect_acl'])
def test_windows_original_method_bodies_and_error_bounds_are_unchanged(member):
    before = definition(BASELINE / 'bootstrap__security__windows_secret_store.py', 'WindowsDpapiSecretStore', member=member)
    after = definition(windows_dpapi.__file__, 'WindowsDpapiSecretStore', member=member)
    assert ast.dump(after) == ast.dump(before)


@pytest.mark.parametrize('name', ['_blob', '_dpapi_functions'])
def test_windows_native_blob_and_ctypes_binding_bodies_are_unchanged(name):
    before = definition(BASELINE / 'bootstrap__security__windows_secret_store.py', name)
    after = definition(windows_dpapi.__file__, name)
    assert ast.dump(after) == ast.dump(before)


def test_dpapi_protect_only_externalizes_description_and_method_receiver():
    before = definition(BASELINE / 'bootstrap__security__windows_secret_store.py', 'WindowsDpapiSecretStore', member='_protect')
    after = definition(windows_dpapi.__file__, 'WindowsDpapiSecretStore', member='_protect')
    class RestoreExplicitParameter(ast.NodeTransformer):
        def visit_Attribute(self, node):
            if isinstance(node.value, ast.Name) and node.value.id == 'self' and node.attr == '_protect_description':
                return ast.Constant(value='AgentBox Server credential')
            return self.generic_visit(node)
    after = RestoreExplicitParameter().visit(after)
    after.args.args.pop(0)
    after.decorator_list = [ast.Name(id='staticmethod', ctx=ast.Load())]
    assert ast.dump(after) == ast.dump(before)


@pytest.mark.parametrize('name', ['SecretStore', 'SecretLocatorUnavailable'])
def test_secret_contract_class_identity_has_one_original_definition(name):
    before = definition(BASELINE / 'bootstrap__security__secret_contracts.py', name)
    after = definition(secrets.__file__, name)
    assert ast.dump(after) == ast.dump(before)


def test_sql_runner_native_transaction_body_only_adds_source_metadata_validation():
    before = definition(BASELINE / 'bootstrap__migrations__runner.py', 'apply_migration_source')
    after = definition(migrations.__file__, 'apply_migration_source')
    validation = after.body.pop(0)
    assert isinstance(validation, ast.Expr) and validation.value.func.id == '_validate_source'
    assert ast.dump(after) == ast.dump(before)
    before = definition(BASELINE / 'bootstrap__migrations__runner.py', '_ensure_version_table')
    after = definition(migrations.__file__, '_ensure_version_table')
    assert ast.dump(after) == ast.dump(before)


def test_new_capability_imports_have_no_io_kernel_product_or_platform_loading():
    code = '''
import importlib.abc, sys, os, sqlite3, subprocess, socket, ctypes
class OnlyStdlibAndInfrastructure(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] not in sys.stdlib_module_names | {'ordessa_infrastructure'}:
            raise AssertionError('foreign import: ' + fullname)
sys.meta_path.insert(0, OnlyStdlibAndInfrastructure())
def forbidden(*args, **kwargs):
    raise AssertionError('import performed runtime IO or platform activation')
os.open = os.makedirs = os.mkdir = os.fsync = forbidden
sqlite3.connect = subprocess.Popen = socket.socket = forbidden
ctypes.WinDLL = forbidden
import ordessa_infrastructure.filesystem.blobs
import ordessa_infrastructure.security.secrets
import ordessa_infrastructure.security.windows_dpapi
import ordessa_infrastructure.database.migrations
'''
    result = subprocess.run([sys.executable, '-B', '-c', code], text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    for planted in ['import pacthold', 'import ordessa_server', 'ctypes.WinDLL("crypt32")']:
        result = subprocess.run([sys.executable, '-B', '-c', code + '\n' + planted], text=True, capture_output=True, timeout=10)
        assert result.returncode != 0 and 'AssertionError' in result.stderr


def test_sql_runner_has_no_default_source_or_global_database_authority():
    assert migrations.MigrationRegistry().registered() == ()
    for forbidden in ['get_conn', 'configure_database', 'CORE_MIGRATION_NAMESPACE', '_CORE_SOURCE', '_assembly_sources']:
        assert not hasattr(migrations, forbidden)
