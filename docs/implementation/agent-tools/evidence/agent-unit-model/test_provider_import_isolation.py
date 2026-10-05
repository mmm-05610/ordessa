"""Fresh interpreter imports, not evidence of native process/task readiness."""
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT=Path(__file__).resolve().parents[5]
FAMILIES=('ordessa_harness_pi','ordessa_harness_codex','ordessa_harness_claude_code')
SEARCH=[ROOT/'plugins/harness'/family/'src' for family in ('pi','codex','claude-code')]
SEARCH += [ROOT/'packages/backend/harness-transport/src',ROOT/'plugins/harness/src',ROOT/'plugins/harness/records/src',ROOT/'plugins/harness/api/src']


def probe(family,*,extra=None):
 script=f'''
import importlib,sys
from ordessa_harness_records.unit_records import UnitRecords
importlib.import_module({family!r})
extra={extra!r}
if extra: importlib.import_module(extra)
assert {family!r} in sys.modules,'selected package not imported'
for name in {FAMILIES!r}:
 if name!={family!r}:
  assert not any(module==name or module.startswith(name+'.') for module in sys.modules),'forbidden family imported: '+name
assert not any(module.startswith('ordessa_agent_tools.native_clients') for module in sys.modules),'product brand client imported'
assert not any(module.startswith(('ordessa_harness.pi','ordessa_harness.codex','ordessa_harness.claude','ordessa_harness.adapters')) for module in sys.modules),'legacy family imported'
'''
 env=dict(os.environ)
 env['PYTHONPATH']=os.pathsep.join(str(path) for path in SEARCH)
 env.pop('PYTHONHOME',None)
 return subprocess.run([sys.executable,'-c',script],cwd=ROOT,env=env,capture_output=True,text=True,timeout=20)


@pytest.mark.parametrize('family',FAMILIES)
def test_only_selected_family_imported_with_existing_unit_journal(family):
 result=probe(family)
 assert result.returncode==0,result.stdout+result.stderr


def test_import_guard_really_rejects_another_family():
 result=probe(FAMILIES[0],extra=FAMILIES[1])
 assert result.returncode==1 and 'forbidden family imported' in result.stderr
