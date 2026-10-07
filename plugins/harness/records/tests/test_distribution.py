"""Fresh records wheels and original SQLite fences; no native/model process."""
import importlib.metadata
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[4]

KERNEL_DEP_DIST_TO_PACKAGE = {
    'pydantic-graph': 'pydantic_graph', 'pydantic': 'pydantic', 'pydantic-core': 'pydantic_core',
    'annotated-types': 'annotated_types', 'typing-inspection': 'typing_inspection',
    'typing-extensions': 'typing_extensions', 'anyio': 'anyio', 'idna': 'idna',
    'logfire-api': 'logfire_api',
}


def _repack_kernel_wheels(wheel_dir: Path) -> set:
    """Repack the pinned kernel dependency chain so the offline closure resolves."""
    wheel_dir.mkdir(parents=True, exist_ok=True)
    generated = set()
    for dist_name, package in KERNEL_DEP_DIST_TO_PACKAGE.items():
        dist = importlib.metadata.distribution(dist_name)
        package_dir = Path(dist.locate_file(package))
        wheel_path = wheel_dir / f'{package}-{dist.version}-py3-none-any.whl'
        generated.add(wheel_path.name)
        with zipfile.ZipFile(wheel_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(package_dir.rglob('*')):
                if path.is_file() and '__pycache__' not in path.parts:
                    zf.write(path, path.relative_to(package_dir.parent))
            dist_info = Path(dist._path)
            for path in sorted(dist_info.rglob('*')):
                if path.is_file():
                    zf.write(path, path.relative_to(package_dir.parent))
    return generated


def test_records_wheel_preserves_one_journal_owner_without_monolith(tmp_path):
    sources=[]
    packages=('packages/backend/environment-api','packages/backend/pacthold','plugins/harness/records')
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
    kernel_wheels=_repack_kernel_wheels(wheels)
    run([sys.executable,'-m','pip','wheel','--no-index','--no-build-isolation','--no-deps','--wheel-dir',str(wheels),*sources])
    artifacts=sorted(wheels.glob('*.whl'))
    own=[p for p in artifacts if p.name not in kernel_wheels]
    assert len(own)==len(packages) and len(artifacts)==len(packages)+len(KERNEL_DEP_DIST_TO_PACKAGE)
    isolated=tmp_path/'venv';run([sys.executable,'-m','venv',str(isolated)])
    python=str(isolated/'bin/python')
    run([python,'-m','pip','install','--no-index','--find-links',str(wheels),*map(str,artifacts)])
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
    'ordessa_agent_tools','server_plugin_api','ordessa_harness_pi','ordessa_harness_codex','ordessa_harness_claude_code'))
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
