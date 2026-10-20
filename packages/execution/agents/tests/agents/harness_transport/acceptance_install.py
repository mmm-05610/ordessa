"""Fresh local provider-wheel closure with offline dependencies and no native launch."""
import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import textwrap

ROOT=Path(__file__).resolve().parents[6]
PROJECTS=('packages/execution/agents','packages/execution/units',
 'packages/execution/environments','packages/infrastructure',
 'plugins/harness/pi','plugins/harness/codex','plugins/harness/claude-code')

def _brand_wheelhouse():
 configured=os.environ.get('ORDESSA_BRAND_WHEELHOUSE')
 candidates=([Path(configured)] if configured else [])+[ROOT/'.nightly-cache'/'brand-yaml-wheel-root']
 for path in candidates:
  if path.is_dir() and any(path.glob('pyyaml-*.whl')) and any(path.glob('tomli_w-*.whl')):
   return str(path)
 raise AssertionError('offline PyYAML and tomli-w wheelhouse unavailable')

def _acp_wheelhouse():
 configured=os.environ.get('ORDESSA_ACP_WHEELHOUSE')
 if not configured:
  raise AssertionError('official ACP SDK offline wheelhouse must be explicitly supplied')
 path=Path(configured)
 if not path.is_dir() or not any(path.glob('agent_client_protocol-0.12.1-*.whl')):
  raise AssertionError('verified ACP SDK 0.12.1 offline wheelhouse unavailable')
 return str(path)


def exercise(output):
 output=Path(output)
 if output.exists(): raise FileExistsError('evidence already exists')
 head=subprocess.check_output(['git','--no-optional-locks','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
 dirty=subprocess.check_output(['git','--no-optional-locks','status','--short'],cwd=ROOT,text=True).splitlines()
 records=[]
 scratch=None; hashes={}; status='failed'; failure=None
 try:
  with tempfile.TemporaryDirectory(prefix='.acceptance-',dir=ROOT/'packages/execution/agents') as directory:
   scratch=Path(directory); wheels=scratch/'wheels'; wheels.mkdir()
   home=scratch/'home'; home.mkdir()
   env={key:value for key,value in os.environ.items() if key in {'PATH','LANG','LC_ALL','SYSTEMROOT'}}
   env.update(HOME=str(home),XDG_CONFIG_HOME=str(home/'config'),PIP_CONFIG_FILE=os.devnull,
              PIP_NO_INDEX='1',PIP_DISABLE_PIP_VERSION_CHECK='1')
   def run(label,command):
    started=time.monotonic()
    try:
     result=subprocess.run(command,cwd=scratch,env=env,capture_output=True,text=True,timeout=90)
    except subprocess.TimeoutExpired:
     records.append({'label':label,'command':command,'exitCode':None,'timedOut':True,
        'seconds':round(time.monotonic()-started,3)})
     raise
    records.append({'label':label,'command':command,'exitCode':result.returncode,
       'seconds':round(time.monotonic()-started,3)})
    if result.returncode:
     raise RuntimeError(label+' failed: '+result.stdout+result.stderr)
    return result.stdout
   for index,project in enumerate(PROJECTS):
    clean=scratch/('source-'+str(index));clean.mkdir()
    shutil.copy2(ROOT/project/'pyproject.toml',clean/'pyproject.toml')
    if (ROOT/project/'README.md').exists(): shutil.copy2(ROOT/project/'README.md',clean/'README.md')
    shutil.copytree(ROOT/project/'src',clean/'src',ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.egg-info'))
    run('build '+project,[sys.executable,'-m','pip','wheel','--no-index','--no-build-isolation',
        '--no-deps','--wheel-dir',str(wheels),str(clean)])
   run('create fresh venv',[sys.executable,'-m','venv',str(scratch/'venv')])
   python=str(scratch/'venv/bin/python')
   paths=sorted(wheels.glob('*.whl'))
   assert len(paths)==len(PROJECTS),'local wheel closure incomplete'
   hashes={path.name:hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}
   run('install local wheel closure',[python,'-m','pip','install','--no-index','--find-links',_brand_wheelhouse(),
       '--find-links',_acp_wheelhouse(),*[str(path) for path in paths]])
   run('pip check',[python,'-m','pip','check'])
   for module,class_name in (('ordessa_harness_codex','CodexRuntimeProvider'),('ordessa_harness_claude_code','ClaudeCodeRuntimeProvider')):
    script=textwrap.dedent(f'''
 import importlib,importlib.util,sys
 from contextlib import nullcontext
 from types import SimpleNamespace
 from ordessa_execution_agents.harness.providers.registry import (
  HarnessAdmission,HarnessCatalog,HarnessDefinitionDeclaration,HarnessDefinitionDescriptor)
 provider=getattr(importlib.import_module({module!r}),{class_name!r})(definition_ref={{'environmentNamespace':'fresh','definitionId':{('codex' if module == 'ordessa_harness_codex' else 'claude')!r},'revision':'1'}},implementation_digest='sha256:'+'a'*64)
 class Policy:
  def admit_object_access(self,*args): return True
  def admit_invoke(self,*args): raise AssertionError('definition catalog cannot issue invocation authority')
 catalog=HarnessCatalog('fresh',policy=Policy(),principal_scope='controlled',
  retirement_guard=lambda owner,generation:nullcontext())
 descriptor=provider.descriptor
 declaration=HarnessDefinitionDeclaration(HarnessDefinitionDescriptor(
  descriptor.provider_id,descriptor.definition_ref,descriptor.implementation_digest,
  'acp/v1','installed-wheel-fixture'),lambda installation_ref:None)
 admission=HarnessAdmission(SimpleNamespace(harness_catalog=catalog))
 staged=catalog.stage('selected',1,'selected-installation','a'*64,(declaration,))
 assert admission.list()==()
 committed=staged.commit()
 admitted=admission.describe(descriptor.definition_ref)
 assert committed==(admitted,)
 assert admitted.owner_activation.plugin_id=='selected' and admitted.owner_activation.generation==1
 assert admitted.descriptor.definition_ref==descriptor.definition_ref
 assert 'start' not in descriptor.supported_methods
 assert catalog.list()==(admitted,)
 catalog.drain('selected',1)
 assert admission.list()==()
 catalog.retire('selected',1)
 catalog.close()
 for forbidden in ('ordessa_server','pacthold','ordessa_agent_tools','claude_agent_sdk','server_plugin_api','ordessa_execution_api','ordessa_environment_api'):
  assert importlib.util.find_spec(forbidden) is None,forbidden+' unexpectedly installed'
 for other in ('ordessa_harness_pi','ordessa_harness_codex','ordessa_harness_claude_code'):
  if other!={module!r}: assert other not in sys.modules,'unselected family imported'
 # Optional Server binding stays unavailable when its public contract is absent.
 wrapper=getattr(importlib.import_module({module!r}+'.server_plugin'),{class_name!r}.replace('RuntimeProvider','ServerPlugin'))(declaration)
 try: wrapper.descriptor()
 except ModuleNotFoundError as error: assert error.name=='server_plugin_api'
 else: raise AssertionError('missing optional Server API silently accepted')
 ''')
    run('fresh isolated catalog '+module,[python,'-I','-c',script])
  status='passed'
 except Exception as error:
  failure=type(error).__name__
  raise
 finally:
  result={'sourceHead':head,'sourceDirtyPaths':dirty,'wheelSha256':hashes,
   'evidenceLevel':'localDistributionAndControlledRegistry' if status=='passed' else 'failedLocalDistributionAttempt','records':records,
   'nativeHarnessProcesses':0,'modelCalls':0,'thirdPartyInstalls':3,
   'temporaryEnvironmentRemoved':scratch is None or not scratch.exists(),
   'status':status,'failureType':failure,'productReady':False,
   'serverApiPresent':False,'coldRecoveryVerified':False}
  output.parent.mkdir(parents=True,exist_ok=True)
  with output.open('x') as stream: stream.write(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
  print(json.dumps({'records':len(records),'allExitZero':status=='passed' and bool(records) and all(row['exitCode']==0 for row in records),'temporaryEnvironmentRemoved':scratch is None or not scratch.exists(),
   'status':status,'failureType':failure,'productReady':False}))


if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--evidence',type=Path,required=True)
 exercise(parser.parse_args().evidence)
