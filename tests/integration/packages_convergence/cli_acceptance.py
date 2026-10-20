"""Real CLI baseline; module mode is explicitly distinct from installed gate."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--state')
    parser.add_argument('--entrypoint',choices=['installed','module'],default='installed')
    parser.add_argument('--receipt')
    args=parser.parse_args()
    workspace=Path(__file__).resolve().parents[3]
    own_temp=tempfile.TemporaryDirectory(prefix='ordessa-convergence-cli-') if args.state is None else None
    state=Path(args.state or own_temp.name)
    env=dict(os.environ)
    if args.entrypoint=='module':
        env['PYTHONPATH']=os.pathsep.join(str(workspace/p) for p in [
            'apps/cli/src','packages/interfaces/src','packages/interfaces/contracts/src',
            'packages/interfaces/system-access/src','packages/interfaces/channels/src',
            'packages/interfaces/channels/cli/src','packages/interfaces/transport/server/src',
            'packages/execution/agents/src','packages/execution/environments/src',
            'packages/execution/decision/src','packages/infrastructure/src',
            'packages/interfaces/transport/client/python/src',
            'plugins/environments/local/src','plugins/decision/rules-cel/src'])
    else:
        # An installed-entry test must consume installed metadata/import paths.
        # Source fallback here could hide a broken installer or wrong checkout.
        env.pop('PYTHONPATH',None)
    env['PYTHONNOUSERSITE']='1';env['PYTHONDONTWRITEBYTECODE']='1'
    command=([sys.executable,'-m','ordessa_agent_tools'] if args.entrypoint=='module'
             else [str(Path(sys.executable).parent/'ordessa')])
    cases=[]
    def run(name,argv,code=0,stdin=None,exact=None,contains=None,exact_stderr=None):
        result=subprocess.run(command+['--state',str(state)]+argv,input=stdin,text=True,capture_output=True,env=env,timeout=15)
        okay=(result.returncode==code and (exact is None or result.stdout==exact)
              and (contains is None or contains in result.stdout)
              and (exact_stderr is None or result.stderr==exact_stderr))
        case={'name':name,'argv':argv,'expectedExit':code,'actualExit':result.returncode,
              'stdout':result.stdout,'stderr':result.stderr,'status':'PASS' if okay else 'FAIL'}
        if exact is not None:case['expectedStdout']=exact
        if exact_stderr is not None:case['expectedStderr']=exact_stderr
        cases.append(case)
        return result
    try:
        run('providers',['--json','environments','providers'])
        run('create',['environments','create','local','--root',str(state/'work'),'--alias','baseline'])
        run('list',['--json','environments','list'])
        run('inspect',['--json','environments','inspect','baseline'])
        run('echo',['environments','exec','baseline','--','/bin/echo','cli-positive'],exact='cli-positive\n')
        run('stdin-pipe',['environments','exec','baseline','--','/bin/cat'],stdin='pipe-positive\n',exact='pipe-positive\n')
        run('child-exit',['environments','exec','baseline','--','/bin/false'],code=1)
        run('no-command',['environments','exec','baseline'],code=2)
        run('write',['environments','files','baseline','write','kept.txt','kept'])
        run('read',['environments','files','baseline','cat','kept.txt'],contains='kept')
        run('stop-refusal',['environments','stop','baseline'],code=2)
        run('delete-refusal',['environments','delete','baseline'],code=2)
        run('timeout',['environments','exec','baseline','--timeout','0.05','--','/bin/sleep','3'],code=7)
        backend=state/'registered-work';backend.mkdir()
        run('register',['environments','register','local',str(backend),'--alias','registered'])
        run('register-conflict',['environments','register','local',str(backend),'--alias','duplicate'],code=5)
        run('stdout-stderr',['environments','exec','baseline','--','/bin/sh','-c','printf stdout; printf stderr >&2; exit 3'],code=3,exact='stdout',exact_stderr='stderr')
        run('operation-list',['--json','list'],contains='environments.exec')
        run('operation-describe',['--json','describe','environments.exec'],contains='environments.exec')
        run('generic-call-exec',['call','environments.exec','--input','-'],stdin=json.dumps({'reference':'baseline','argv':['/bin/echo','generic-positive']}),exact='generic-positive\n')
        run('one-shot-acquire-unavailable',['call','environments.acquire','--input','-'],stdin=json.dumps({'reference':'baseline','sharing':False}),code=4)
        after=run('retention',['--json','environments','inspect','baseline'])
        try:
            assert json.loads(after.stdout)['data']['activeUses']==0
            assert (state/'work/kept.txt').read_text()=='kept'
        except (AssertionError,ValueError,KeyError,OSError):cases[-1]['status']='FAIL'
        failures=[case['name'] for case in cases if case['status']=='FAIL']
        receipt={'entrypoint':args.entrypoint,'commandPrefix':command,'python':sys.executable,
                 'sourcePathFallback':args.entrypoint=='module',
                 'source':str(workspace),'scope':'one-shot local environment CLI + declarative generic calls; not all-domain installed acceptance',
                 'unsupportedInOneShot':['environments.acquire','environments.launch','environments.export-endpoint'],
                 'cases':cases,'passed':len(cases)-len(failures),
                 'failed':len(failures),'failures':failures,'status':'FAIL' if failures else 'PASS'}
        if args.receipt:Path(args.receipt).write_text(json.dumps(receipt,indent=2)+'\n')
        print(json.dumps({k:receipt[k] for k in ['entrypoint','passed','failed','failures','status']}))
        return 1 if failures else 0
    finally:
        if own_temp:own_temp.cleanup()


if __name__=='__main__':raise SystemExit(main())
