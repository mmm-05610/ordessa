import subprocess
import sys

import pytest


def _run(code: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)


def test_database_import_has_no_io_side_effects():
    code = (
        "import sqlite3\n"
        "def forbidden(*a, **k):\n"
        "    raise AssertionError('import opened a database')\n"
        "sqlite3.connect = forbidden\n"
        "import ordessa_infrastructure.database\n"
        "import ordessa_infrastructure.database.options\n"
        "import ordessa_infrastructure.database.sqlite\n"
    )
    completed = _run(code)
    assert completed.returncode == 0, completed.stderr


def test_filesystem_import_has_no_io_side_effects():
    code = (
        "import os\n"
        "def forbidden(*a, **k):\n"
        "    raise AssertionError('import performed filesystem IO')\n"
        "os.open = forbidden\n"
        "os.fsync = forbidden\n"
        "import ordessa_infrastructure.filesystem\n"
        "import ordessa_infrastructure.filesystem.directories\n"
        "import ordessa_infrastructure.filesystem.files\n"
        "import ordessa_infrastructure.filesystem.publication\n"
    )
    completed = _run(code)
    assert completed.returncode == 0, completed.stderr


def test_root_package_import_has_no_io_side_effects():
    code = (
        "import sqlite3, os\n"
        "def forbidden(*a, **k):\n"
        "    raise AssertionError('root import performed IO')\n"
        "sqlite3.connect = forbidden\n"
        "os.open = forbidden\n"
        "os.fsync = forbidden\n"
        "import ordessa_infrastructure\n"
    )
    completed = _run(code)
    assert completed.returncode == 0, completed.stderr


def test_all_public_modules_import_without_process_database_filesystem_or_network_io():
    completed = _run('''
import os, sqlite3, subprocess, socket

def forbidden(*a, **k):
    raise AssertionError('import performed runtime IO')

os.open = os.makedirs = os.mkdir = os.fsync = os.pipe = forbidden
sqlite3.connect = forbidden
subprocess.Popen = forbidden
socket.socket = forbidden
import ordessa_infrastructure.encoding
import ordessa_infrastructure.identifiers
import ordessa_infrastructure.database
import ordessa_infrastructure.filesystem
import ordessa_infrastructure.process
import ordessa_infrastructure.process.spawn
import ordessa_infrastructure.process.framing
''')
    assert completed.returncode == 0, completed.stderr


def _foreign_imports(source):
    import ast
    imports = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imports.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            imports.append(node.module or '')
    return [name for name in imports if name.split('.')[0] not in
            sys.stdlib_module_names | {'ordessa_infrastructure', '__future__'}]


def test_no_business_or_concrete_plugin_imports_in_ast():
    from pathlib import Path
    import ordessa_infrastructure

    root = Path(ordessa_infrastructure.__file__).parent
    for path in root.rglob('*.py'):
        assert not _foreign_imports(path.read_text()), path


@pytest.mark.parametrize('source', [
    'import ordessa_server', 'from pacthold import Environment',
    'def lazy():\n import ordessa_harness_dsh', 'import ordessa_infrastructure_fake',
])
def test_ast_guard_rejects_planted_business_imports(source):
    assert _foreign_imports(source)


def test_isolated_import_refuses_foreign_packages_and_detects_runtime_io_counterexample():
    code = '''
import importlib.abc, sys, os
class OnlyStdlibAndInfrastructure(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] not in sys.stdlib_module_names | {'ordessa_infrastructure'}:
            raise AssertionError('foreign import: ' + fullname)
sys.meta_path.insert(0, OnlyStdlibAndInfrastructure())
def forbidden(*a, **k):
    raise AssertionError('runtime filesystem IO')
os.open = forbidden
import ordessa_infrastructure.process
import ordessa_infrastructure.encoding
import ordessa_infrastructure.identifiers
import ordessa_infrastructure.filesystem
import ordessa_infrastructure.database
'''
    assert _run(code).returncode == 0
    foreign = _run(code + '\nimport ordessa_server\n')
    assert foreign.returncode != 0 and 'foreign import: ordessa_server' in foreign.stderr
    io = _run(code + '\nos.open("unused", os.O_RDONLY)\n')
    assert io.returncode != 0 and 'runtime filesystem IO' in io.stderr
