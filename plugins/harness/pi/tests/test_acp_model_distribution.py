"""Fresh own-wheel closure for pure Pi ACP planning, no native/model calls."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]

def _brand_wheelhouse():
    """Offline wheelhouse for third-party brand deps, prepared from the configured trusted source."""
    configured = os.environ.get('ORDESSA_BRAND_WHEELHOUSE')
    candidates = ([Path(configured)] if configured else []) + [ROOT / '.nightly-cache' / 'brand-yaml-wheel-root']
    for path in candidates:
        if path.is_dir() and any(path.glob('pyyaml-*.whl')):
            return str(path)
    raise AssertionError('offline brand wheelhouse (PyYAML) unavailable; prepare it from the configured trusted source')

def _acp_wheelhouse():
    configured = os.environ.get('ORDESSA_ACP_WHEELHOUSE')
    assert configured, 'official ACP SDK offline wheelhouse must be explicitly supplied'
    directory = Path(configured)
    wheel = directory / 'agent_client_protocol-0.12.1-py3-none-any.whl'
    import hashlib
    assert wheel.is_file() and hashlib.sha256(wheel.read_bytes()).hexdigest() == 'aaf3cc301ed87d9e2c4ccb91adfe1cd58784355f6ce7e513f50e7ca2391862ef'
    return str(directory)

def test_independent_pi_model_wheel_without_server_monolith_product(tmp_path):
    packages = ('packages/interfaces/execution/c1-api', 'packages/execution/agents',
                'packages/execution/environments', 'packages/execution/units',
                'packages/infrastructure', 'plugins/harness/pi')
    sources = []
    for index, relative in enumerate(packages):
        source = ROOT / relative; clean = tmp_path / ('source-' + str(index)); clean.mkdir()
        shutil.copy2(source / 'pyproject.toml', clean / 'pyproject.toml')
        if (source / 'setup.py').exists(): shutil.copy2(source / 'setup.py', clean / 'setup.py')
        if (source / 'README.md').exists(): shutil.copy2(source / 'README.md', clean / 'README.md')
        shutil.copytree(source / 'src', clean / 'src', ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '*.egg-info'))
        sources.append(str(clean))
    wheels = tmp_path / 'wheels'
    env = {key: value for key, value in os.environ.items() if key not in {'PYTHONPATH','PYTHONHOME','VIRTUAL_ENV'}}
    home = tmp_path / 'home'; home.mkdir()
    env.update(HOME=str(home), PIP_CONFIG_FILE=os.devnull, PIP_NO_INDEX='1', PIP_DISABLE_PIP_VERSION_CHECK='1')
    def run(command):
        result = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stdout + result.stderr
        return result
    run([sys.executable, '-m', 'pip', 'wheel', '--no-index', '--no-build-isolation', '--no-deps',
         '--wheel-dir', str(wheels), *sources])
    own = sorted(wheels.glob('*.whl'))
    assert [p.name.split('-')[0] for p in own] == ['ordessa_environments', 'ordessa_execution_agents', 'ordessa_execution_api', 'ordessa_harness_pi', 'ordessa_infrastructure', 'ordessa_units']
    artifacts = sorted(wheels.glob('*.whl')); assert len(artifacts) == len(packages)
    isolated = tmp_path / 'isolated'; run([sys.executable, '-m', 'venv', str(isolated)])
    python = str(isolated / 'bin/python')
    run([python, '-m', 'pip', 'install', '--no-index', '--find-links', str(wheels), '--find-links', _brand_wheelhouse(), '--find-links', _acp_wheelhouse(), *map(str, artifacts)])
    run([python, '-m', 'pip', 'check'])
    program = """
import importlib.util
assert importlib.util.find_spec('pydantic_graph') is None
assert all(importlib.util.find_spec(name) is None for name in ('pacthold', 'ordessa_harness', 'ordessa_server',
    'ordessa_agent_tools', 'server_plugin_api', 'ordessa_harness_codex', 'ordessa_harness_claude_code'))
from importlib.metadata import PackageNotFoundError, distribution
try:
    distribution('pacthold')
except PackageNotFoundError:
    pass
else:
    raise AssertionError('retired pacthold distribution must be absent')
from dataclasses import replace
from ordessa_execution_agents.harness.definitions.model_compilation import AdapterContext,ChoiceRequest,TargetHandle,BindSecret,CompileIntent,RequestParams
from ordessa_harness_pi.acp_model_configuration import PiAdapter
from ordessa_harness_pi import PiAcpHarnessPreparation
context = AdapterContext(TargetHandle('pi','instance','fixture'),'0.5.1',{'native_session_id':'original-session'})
choice = ChoiceRequest('provider','new-model','https://fixture.test','openai-chat','ref://fixture','acme',
                       {'provider_in_instance':True,'credential_changed':True})
plan = PiAdapter().compile(context,{},choice)
assert plan.reconfiguration=='restart-resume' and plan.resume_expectation=={'native_session_id':'original-session'}
assert any(isinstance(item,CompileIntent) and item.field_path==('session','model') and item.typed_value=='new-model' for item in plan.intents)
assert any(isinstance(item,BindSecret) and item.secret_ref=='ref://fixture' for item in plan.intents)
assert not any(isinstance(item,CompileIntent) and item.field_path==('providers','acme') for item in plan.intents)
before={'providers':{'acme':{'baseUrl':'https://fixture.test','models':[{'id':'new-model','maxTokens':4096},{'id':'sibling','maxTokens':2}]}}}
budget=PiAdapter().compile(context,before,replace(choice,params=RequestParams(max_tokens=1024)))
golden=next(item.typed_value for item in budget.intents if isinstance(item,CompileIntent) and item.field_path==('providers','acme'))
assert golden['models']==[{'id':'new-model','maxTokens':1024},{'id':'sibling','maxTokens':2}]
retry=RequestParams.from_record({'retry':{'enabled':True,'maxRetries':2,'provider':{'maxRetries':1,'maxRetryDelayMs':1000}}})
retry_plan=PiAdapter().compile(context,before,replace(choice,params=retry))
assert any(isinstance(item,CompileIntent) and item.field_path==('retry',) for item in retry_plan.intents)
assert not any(isinstance(item,CompileIntent) and item.field_path==('providers','acme') for item in retry_plan.intents)
assert PiAcpHarnessPreparation.harness_id=='pi'
from pathlib import Path
import ordessa_harness_pi
pi_root=Path(ordessa_harness_pi.__file__).resolve().parent
assert not (pi_root/'acp/launch_pi.mjs').exists()
assert not (pi_root/'acp/launch_pi.json').exists()
for name in ('provider','lifecycle','runtime_channel','projection','termination'):
    assert importlib.util.find_spec('ordessa_harness_pi.'+name) is None
assert not hasattr(__import__('ordessa_harness_pi'),'PiRuntimeProvider')

"""
    run([python, '-I', '-c', program])
    # The relocated native modules must resolve from the installed wheel peers,
    # even when the source snapshots and the checkout are unavailable to Node.
    import json
    paths = json.loads(run([python, '-I', '-c', "import json,ordessa_execution_agents,ordessa_harness_pi; from pathlib import Path; print(json.dumps([str(Path(ordessa_execution_agents.__file__).parent),str(Path(ordessa_harness_pi.__file__).parent)]))"]).stdout)
    agents, pi = map(Path, paths)
    for package in (agents, pi):
        for module in package.rglob('*'):
            if module.suffix in ('.js', '.mjs'):
                text = module.read_text()
                assert 'packages/execution/agents/src/ordessa_execution_agents/' not in text, module
                assert 'infrastructure/src/ordessa_infrastructure/' not in text, module
    run([python, '-I', '-c', "import importlib.util; from ordessa_units.sessions.sdk_client import SdkAcpClient; from acp.connection import Connection; from ordessa_units.management import UnitInstance; from ordessa_units.records import UnitRecords,OperationJournal; from ordessa_units.public import unit_services; assert importlib.util.find_spec('ordessa_execution_agents.units') is None; assert importlib.util.find_spec('ordessa_harness_pi.lease') is None; assert UnitInstance.__module__=='ordessa_units.management.instance'"])
    options = [{'id':'thinkingLevel','currentValue':'low','_meta':{'😀':'first','\ue000':'second','n':9007199254740991,'keep':[True,None]}}]
    expected = run([python, '-I', '-c', 'from ordessa_execution_agents.harness.configuration.compilation.native_digest import configuration_digest; print(configuration_digest('+repr(options)+'))']).stdout.strip()
    node_script = f"""
import assert from 'node:assert/strict';
import {{ mkdtempSync, mkdirSync, writeFileSync, rmSync }} from 'node:fs';
import {{ tmpdir }} from 'node:os';
import path from 'node:path';
import {{ configurationDigest }} from {json.dumps((agents/'harness/configuration/acp/digest.mjs').as_uri())};
import {{ configurationReader }} from {json.dumps((pi/'acp/profile/configuration-query.mjs').as_uri())};
import {{ piCreation }} from {json.dumps((pi/'acp/profile/creation.mjs').as_uri())};
import * as registration from {json.dumps((pi/'acp/profile/provider-registration.mjs').as_uri())};
import {{ createPiHistoryLoader }} from {json.dumps((pi/'acp/vendor/pi-session-history.js').as_uri())};
const options={json.dumps(options,ensure_ascii=False)};
const session={{configOptions:()=>options}};
const read=configurationReader({{live:new Map([['installed',session]])}},m=>new Error(m));
const observation=read({{sessionId:'installed'}});
assert.deepEqual(observation.configOptions,options);
assert.equal(configurationDigest(observation),{json.dumps(expected)});
assert.equal(typeof piCreation,'function');
assert.ok(Object.keys(registration).length>0);
assert.throws(()=>configurationDigest({{configOptions:[{{_meta:{{epsilon:1e-7}}}}]}}),/safe integer/);
const historyRoot=mkdtempSync(path.join(tmpdir(),'ordessa-pi-history-'));
try {{
  const nested=path.join(historyRoot,'nested');
  mkdirSync(nested,{{recursive:true}});
  const records=[
    {{type:'session',id:'root',parentId:null}},
    {{type:'model_change',id:'model',parentId:'root',provider:'fixture-provider',modelId:'fixture-model'}},
    {{type:'thinking_level_change',id:'thinking',parentId:'model',thinkingLevel:'high'}},
    {{type:'message',id:'user-message',parentId:'thinking',timestamp:'2026-10-12T03:04:05.000Z',message:{{role:'user',content:'fixture prompt'}}}},
    {{type:'message',id:'assistant-message',parentId:'user-message',timestamp:'2026-10-12T03:04:06.000Z',message:{{role:'assistant',content:[{{type:'text',text:'fixture answer'}},{{type:'thinking',thinking:'fixture reasoning'}}]}}}}
  ];
  writeFileSync(path.join(nested,'pi_session_fixture-session.jsonl'),records.map(record=>JSON.stringify(record)).join('\\n')+'\\n');
  const historyLoader=createPiHistoryLoader(historyRoot);
  assert.equal(historyLoader.authoritativeHistory,true);
  assert.equal(historyLoader.claimOnLoad,true);
  const history=await historyLoader('fixture-session');
  const expectedHistory=[
    {{info:{{id:'user-message',role:'user',sessionID:'fixture-session',time:{{created:Date.parse('2026-10-12T03:04:05.000Z')}}}},parts:[{{id:'user-message:text:0',messageID:'user-message',type:'text',text:'fixture prompt'}}]}},
    {{info:{{id:'assistant-message',role:'assistant',sessionID:'fixture-session',time:{{created:Date.parse('2026-10-12T03:04:06.000Z')}}}},parts:[{{id:'assistant-message:text:0',messageID:'assistant-message',type:'text',text:'fixture answer'}},{{id:'assistant-message:reasoning:1',messageID:'assistant-message',type:'reasoning',text:'fixture reasoning'}}]}}
  ];
  assert.deepEqual(history,expectedHistory);
  assert.deepEqual(await historyLoader.page('fixture-session'),{{messages:expectedHistory,before:null,hasMore:false,model:{{providerID:'fixture-provider',modelID:'fixture-model',variant:'high'}}}});
}} finally {{
  rmSync(historyRoot,{{recursive:true,force:true}});
}}
console.log('installed wheel native digest/reader/history/provider/creation closure verified');
"""
    # Remove clean build inputs before executing installed native code. The
    # subprocess cwd remains tmp_path, never the source repository.
    for source in sources:
        shutil.rmtree(source)
    run(['node', '--input-type=module', '-e', node_script])
