"""Fresh local provider-wheel closure. No indexes, SDK install or native launch."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[4]
PROJECTS=('packages/backend/environment-api','packages/backend/pacthold',
 'packages/backend/harness-transport','plugins/harness/pi','plugins/harness/codex','plugins/harness/claude-code')


def exercise():
 records=[]
 with tempfile.TemporaryDirectory(prefix='.acceptance-',dir=ROOT/'packages/backend/harness-transport') as directory:
  scratch=Path(directory); wheels=scratch/'wheels'; wheels.mkdir()
  home=scratch/'home'; home.mkdir()
  env={key:value for key,value in os.environ.items() if key in {'PATH','LANG','LC_ALL','SYSTEMROOT'}}
  env.update(HOME=str(home),XDG_CONFIG_HOME=str(home/'config'),PIP_CONFIG_FILE=os.devnull,
             PIP_NO_INDEX='1',PIP_DISABLE_PIP_VERSION_CHECK='1')
  def run(label,command):
   started=time.monotonic()
   result=subprocess.run(command,cwd=scratch,env=env,capture_output=True,text=True,timeout=90)
   records.append({'label':label,'command':command,'exitCode':result.returncode,
      'seconds':round(time.monotonic()-started,3)})
   if result.returncode:
    raise RuntimeError(label+' failed: '+result.stdout+result.stderr)
   return result.stdout
  for project in PROJECTS:
   run('build '+project,[sys.executable,'-m','pip','wheel','--no-index','--no-build-isolation',
       '--no-deps','--wheel-dir',str(wheels),str(ROOT/project)])
  run('create fresh venv',[sys.executable,'-m','venv',str(scratch/'venv')])
  python=str(scratch/'venv/bin/python')
  paths=sorted(wheels.glob('*.whl'))
  assert len(paths)==len(PROJECTS),'local wheel closure incomplete'
  run('install six local wheels',[python,'-m','pip','install','--no-index','--no-deps',*[str(path) for path in paths]])
  run('pip check',[python,'-m','pip','check'])
  for module,class_name in (('ordessa_harness_pi','PiRuntimeProvider'),
     ('ordessa_harness_codex','CodexRuntimeProvider'),('ordessa_harness_claude_code','ClaudeCodeRuntimeProvider')):
   script=f'''
import importlib,importlib.util,sys
from pacthold.public import Environment,InstallationRecord
from pacthold.agents.public import AgentContributionSet
class Policy:
 def admit_object_access(self,*args): return True
 def admit_invoke(self,*args): return True
provider=getattr(importlib.import_module({module!r}),{class_name!r})(definition_ref={{'environmentNamespace':'fresh','definitionId':'selected','revision':'1'}},implementation_digest='sha256:'+'a'*64)
env=Environment('fresh',policy=Policy())
env.install(InstallationRecord('selected','a'*64));env.enable('selected')
receipt=env.activate('selected',AgentContributionSet(agent_runtime_providers=(provider,)))
assert env.agent_runtime_contribution(provider.descriptor.definition_ref).owner_activation==receipt.activation
assert 'start' not in provider.descriptor.supported_methods
for forbidden in ('ordessa_server','ordessa_harness','ordessa_agent_tools','claude_agent_sdk'):
 assert importlib.util.find_spec(forbidden) is None,forbidden+' unexpectedly installed'
for other in ('ordessa_harness_pi','ordessa_harness_codex','ordessa_harness_claude_code'):
 if other!={module!r}: assert other not in sys.modules,'unselected family imported'
env.close()
'''
   run('fresh isolated registry '+module,[python,'-I','-c',script])
 result={'sourceHead':'77a1d8a92c plus AU003 local provider/transport sources',
  'evidenceLevel':'localDistributionAndControlledRegistry','records':records,
  'nativeHarnessProcesses':0,'modelCalls':0,'thirdPartyInstalls':0,
  'temporaryEnvironmentRemoved':not scratch.exists(),'productReady':False}
 output=ROOT/'docs/implementation/agent-tools/evidence/agent-unit-model/au003-fresh-provider-install.json'
 output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'records':len(records),'allExitZero':True,'temporaryEnvironmentRemoved':not scratch.exists(),'productReady':False}))


if __name__=='__main__': exercise()
