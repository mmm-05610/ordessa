"""Fresh-interpreter import order: low-level units modules stay independent of the API surface.

Importing a low-level module must not execute ``ordessa_units.api`` and its eager
channel imports. Each check runs in a clean interpreter rooted explicitly at this
worktree's source packages so an installed copy cannot answer for it.
"""
import os
from pathlib import Path
import subprocess
import sys

UNITS_ROOT = Path(__file__).resolve().parents[1]
_SRC_ROOTS = [UNITS_ROOT / 'src']
for _candidate in (
    UNITS_ROOT.parent / 'agents' / 'src',
    UNITS_ROOT.parent / 'environments' / 'src',
    UNITS_ROOT.parent / 'decision' / 'src',
    UNITS_ROOT.parents[2] / 'infrastructure' / 'src',
    UNITS_ROOT.parents[2] / 'backend' / 'pacthold' / 'src',
):
    if _candidate.is_dir():
        _SRC_ROOTS.append(_candidate)

_ENV = dict(os.environ)
_ENV['PYTHONPATH'] = os.pathsep.join(str(root) for root in _SRC_ROOTS)
_ENV['PYTHONDONTWRITEBYTECODE'] = '1'

_LOW_LEVEL_IMPORT_CHECK = '''
import importlib.util

for module in (
    'ordessa_units.definitions.operations',
    'ordessa_units.admission.invocation',
    'ordessa_units.channels.reservations',
):
    __import__(module)

assert importlib.util.find_spec('ordessa_units.errors') is None, (
    'retired ordessa_units.errors is still importable')
assert importlib.util.find_spec('ordessa_units.errors') is not None
'''

_API_REEXPORT_CHECK = '''
from ordessa_units.api import UnitApiRefused, UnitReconnectUnavailable
from ordessa_units.errors import UnitApiRefused as LeafRefused
from ordessa_units.errors import UnitReconnectUnavailable as LeafReconnect

assert UnitApiRefused is LeafRefused
assert UnitReconnectUnavailable is LeafReconnect
'''


def _run_clean(code):
    return subprocess.run(
        [sys.executable, '-c', code],
        capture_output=True, text=True, cwd=str(UNITS_ROOT), env=_ENV,
    )


def test_low_level_modules_import_without_the_api_surface():
    result = _run_clean(_LOW_LEVEL_IMPORT_CHECK)
    assert result.returncode == 0, result.stderr


def test_api_still_reexports_refusals_from_the_leaf_module():
    result = _run_clean(_API_REEXPORT_CHECK)
    assert result.returncode == 0, result.stderr
