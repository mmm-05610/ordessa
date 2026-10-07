"""Fresh records wheels and original SQLite fences; no native/model process."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[4]


def test_records_wheel_preserves_one_journal_owner_without_monolith(tmp_path):
    sources=[]
    packages=('packages/backend/environment-api','plugins/harness/api','plugins/harness/records')
    for index,relative in enumerate(packages):
        source=ROOT/relative;clean=tmp_path/('source-'+str(index));clean.mkdir()
        shutil.copy2(source/'pyproject.toml',clean/'pyproject.toml')
        if (source/'README.md').exists():shutil.copy2(source/'README.md',clean/'README.md')
        shutil.copytree(source/'src',clean/'src',ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.egg-info'))
        sources.append(str(clean))
    home=tmp_path/'home';home.mkdir()
    env={key:value for key,value in os.environ.items() if key not in {'PYTHONPATH','PYTHONHOME','VIRTUAL_ENV'}}
    env.update(HOME=str(home),PIP_CONFIG_FILE=os.devnull,PIP_NO_INDEX='1',PIP_DISABLE_PIP_VERSION_CHECK='1')
    def run(command):
        result=subprocess.run(command,cwd=tmp_path,env=env,capture_output=True,text=True,timeout=60)
        assert result.returncode==0,result.stdout+result.stderr
        return result
    wheels=tmp_path/'wheels'
    run([sys.executable,'-m','pip','wheel','--no-index','--no-build-isolation','--no-deps','--wheel-dir',str(wheels),*sources])
    artifacts=sorted(wheels.glob('*.whl'));assert len(artifacts)==len(packages)
    isolated=tmp_path/'venv';run([sys.executable,'-m','venv',str(isolated)])
    python=str(isolated/'bin/python')
    run([python,'-m','pip','install','--no-index','--no-deps',*map(str,artifacts)])
    run([python,'-m','pip','check'])
    program='''
import importlib.util,sqlite3
from pathlib import Path
from datetime import datetime,timedelta,timezone
old_connect=sqlite3.connect
def no_import_io(*args,**kwargs):raise AssertionError('records import opened database')
sqlite3.connect=no_import_io
from ordessa_harness_records import OperationJournal,UnitRecords,UnitRecordsRefused,FenceObservation
from ordessa_harness_records.unit_records import OperationJournal as UnitJournal
assert UnitJournal is OperationJournal
sqlite3.connect=old_connect
assert all(importlib.util.find_spec(name) is None for name in ('ordessa_harness','ordessa_server',
    'ordessa_agent_tools','server_plugin_api','pacthold','ordessa_harness_pi','ordessa_harness_codex','ordessa_harness_claude_code'))
from pacthold.harness_contracts import ApplicationTarget,Plan,Refused,ErrorCode
now=datetime.now(timezone.utc)
target=ApplicationTarget('fixture-server','fixture-session','fixture-channel',7)
plan=Plan('fixture-plan',target,'a'*64,'before-1','native-1',3,'auth-1','ref-revision-1',(now+timedelta(minutes=5)).isoformat())
path=Path('original-journal.sqlite')
journal=OperationJournal(path);journal.register_plan('alice',plan)
observation=FenceObservation.from_plan(plan)
first=journal.reserve('alice',plan.plan_id,'original-request',observation,now=now)
assert first.result.kind=='unknown'
reopened=OperationJournal(path)
assert reopened.query('alice',target,'original-request')==first
assert reopened.reserve('alice',plan.plan_id,'original-request',observation,now=now)==first
busy=reopened.reserve('alice',plan.plan_id,'different-request',observation,now=now)
assert isinstance(busy,Refused) and busy.code is ErrorCode.BUSY
assert reopened.reconcile('alice',target,'original-request')==first.result
try:UnitRecords(journal,scope_authority=None,native_evidence=None,verifier=None,epoch_port=None)
except UnitRecordsRefused:pass
else:raise AssertionError('missing owner authorities silently accepted')
assert list(Path('.').glob('*.sqlite'))==[path]
'''
    run([python,'-I','-c',program])
