#!/usr/bin/env python3
"""Serial offline acceptance with explicit per-scenario receipts and no live model."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import time

ROOT=Path(__file__).resolve().parents[4]
PACKAGE=ROOT/'packages/backend/decision'
TEMP=ROOT/'.decision-tmp'
BASELINE='e4714eba00a78ba04c5b53318830a0d409e76bbe'

def run(args, *, env=None):
    value=subprocess.run([str(a) for a in args],cwd=ROOT,env=env,text=True,capture_output=True)
    return value

def prepare():
    TEMP.mkdir(exist_ok=True)
    build=run([sys.executable,'-m','build','--wheel','--no-isolation','--outdir',TEMP/'dist',PACKAGE])
    (TEMP/'acceptance-build.txt').write_text(build.stdout+build.stderr)
    if build.returncode: raise RuntimeError('wheel build failed; see .decision-tmp/acceptance-build.txt')
    if not (TEMP/'wheels').exists(): raise RuntimeError('offline wheel cache absent; install prerequisites explicitly before acceptance')
    executable=TEMP/'wheel-env/bin/python'
    if not executable.exists():
        v=run([sys.executable,'-m','venv',TEMP/'wheel-env'])
        if v.returncode: raise RuntimeError('wheel env creation failed')
    install=run([executable,'-m','pip','install','--no-index','--find-links',TEMP/'wheels','--force-reinstall',TEMP/'dist/ordessa_decision-0.1.0-py3-none-any.whl'])
    (TEMP/'acceptance-wheel-install.txt').write_text(install.stdout+install.stderr)
    if install.returncode: raise RuntimeError('offline wheel install failed')
    archive=run(['git','rev-parse',BASELINE])
    if archive.returncode or archive.stdout.strip()!=BASELINE: raise RuntimeError('fixed baseline unavailable')
    baseline=TEMP/'baseline';baseline.mkdir(exist_ok=True)
    data=subprocess.run(['git','archive',BASELINE,'packages/backend/pacthold','packages/backend/environment-api','plugins/runtime-compat','scripts/artifact_presence.py'],cwd=ROOT,capture_output=True)
    if data.returncode: raise RuntimeError('baseline archive failed')
    with tarfile.open(fileobj=io.BytesIO(data.stdout)) as tf:
        tf.extractall(baseline,filter='data')
    cases=['packages/backend/pacthold/tests/platform/test_t009_direction_guard.py','packages/backend/pacthold/tests/platform/test_public_contract.py','packages/backend/pacthold/tests/environment/test_lifecycle.py','packages/backend/pacthold/tests/environment/test_store_port_seam.py']
    for label in ('baseline','current'):
        env=dict(os.environ)
        if label=='baseline':
            env['PYTHONPATH']=os.pathsep.join(str(baseline/x) for x in ('packages/backend/pacthold/src','packages/backend/environment-api/src'))
        result=run([sys.executable,'-m','pytest',*[str(baseline/c) if label=='baseline' else c for c in cases],'-q','--junitxml='+str(TEMP/(label+'-core.xml'))],env=env)
        (TEMP/(label+'-core.txt')).write_text(result.stdout+result.stderr)
        if result.returncode: raise RuntimeError(label+' regression failed; receipts retained, no scenarios promoted')

parser=argparse.ArgumentParser()
parser.add_argument('--scenario',choices=[f'T{i:02}' for i in range(1,69)])
parser.add_argument('--output',type=Path,default=TEMP/'acceptance-run')
args=parser.parse_args()
try: prepare()
except (RuntimeError,ValueError) as exc:
    print(str(exc),file=sys.stderr);sys.exit(1)
collected=run([sys.executable,'-m','pytest',PACKAGE/'tests','--collect-only','-q'])
if collected.returncode: print(collected.stdout+collected.stderr);sys.exit(1)
nodes=[str(PACKAGE/line.strip()) for line in collected.stdout.splitlines() if '::' in line and not line.startswith(' ')]
args.output.mkdir(parents=True,exist_ok=True)
sha=run(['git','rev-parse','HEAD']).stdout.strip()
source_hash=hashlib.sha256()
for p in sorted((PACKAGE/'src').rglob('*')):
    if p.suffix in ('.py','.json'): source_hash.update(str(p.relative_to(PACKAGE)).encode()+b'\0'+p.read_bytes())
receipt={'baseline':BASELINE,'head':sha,'source_digest':'sha256:'+source_hash.hexdigest(),
    'python':sys.version,'mode':'offline','model_http':'fake_transport_only','real_model_requests':0,
    'credential_reads':0,'scope':'local POSIX + temporary real core/fake owner; no live services',
    'inherited_scope':'57 targeted Pacthold baseline IDs; full server/Harness registered reds not rerun',
    'scenarios':[]}
failed=False
if not args.scenario:
    command=[sys.executable,'-m','pytest',str(PACKAGE/'tests'),'-q','--junitxml='+str(args.output/'full-suite.xml')]
    result=run(command)
    (args.output/'full-suite.txt').write_text(result.stdout+result.stderr)
    ok=result.returncode==0 and not re.search(r'\b\d+ skipped\b',result.stdout)
    failed|=not ok
    receipt['full_suite']={'status':'PASSED' if ok else 'FAILED','command':command,'exit_code':result.returncode,
        'summary':next((x for x in reversed(result.stdout.splitlines()) if 'passed' in x or 'failed' in x),''),
        'evidence':str(args.output/'full-suite.txt')}
    print('full suite',receipt['full_suite']['status'],receipt['full_suite']['summary'],flush=True)
for i in range(1,69):
    scenario=f'T{i:02}'
    if args.scenario and scenario!=args.scenario: continue
    if scenario=='T60':
        receipt['scenarios'].append({'id':scenario,'status':'NOT_RUN','reason':'separate live authorization, credential and cost scope required'});continue
    selected=[node for node in nodes if scenario in ['T'+x for x in re.findall(r'(?i)T(\d{2})(?!\d)',node)]]
    if not selected:
        failed=True;receipt['scenarios'].append({'id':scenario,'status':'FAILED','reason':'no scene tests collected'});continue
    start=time.monotonic()
    command=[sys.executable,'-m','pytest',*selected,'-q','--junitxml='+str(args.output/(scenario+'.xml'))]
    result=run(command)
    (args.output/(scenario+'.txt')).write_text(result.stdout+result.stderr)
    ok=result.returncode==0 and not re.search(r'\b\d+ skipped\b',result.stdout)
    failed|=not ok
    receipt['scenarios'].append({'id':scenario,'status':'PASSED' if ok else 'FAILED','command':command,
        'exit_code':result.returncode,'duration_seconds':round(time.monotonic()-start,3),'test_ids':selected,
        'summary':next((x for x in reversed(result.stdout.splitlines()) if 'passed' in x or 'failed' in x),''),
        'evidence':str(args.output/(scenario+'.txt'))})
    print(scenario,receipt['scenarios'][-1]['status'],receipt['scenarios'][-1]['summary'],flush=True)
    (args.output/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
receipt['offline_result']='FAILED' if failed else 'PASSED'
receipt['live_jev']='NOT_RUN'
(args.output/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
print('offline:',receipt['offline_result'],'live Jev: NOT_RUN','receipt:',args.output/'receipt.json',flush=True)
sys.exit(1 if failed else 0)
