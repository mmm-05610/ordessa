"""Native ACP command approval on a controlled original Unit, with no model."""
from contextlib import contextmanager
import hashlib
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from ordessa_units.api import UnitApiRefused

UNIT_TESTS = Path(__file__).resolve().parents[3] / 'packages/execution/units/tests'
sys.path.insert(0, str(UNIT_TESTS))
from test_local_owner import ACP_PEER, live_owner

PRODUCER_PATH = Path(__file__).resolve().parents[3] / 'tooling/checks/server_product/local_library_check_runtime.py'
SPEC = importlib.util.spec_from_file_location('native_catalog_check_runtime', PRODUCER_PATH)
producer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(producer)


class DeferredApproval:
    delegate = None

    def authorize(self, **request):
        assert self.delegate is not None
        return self.delegate.authorize(**request)


APPROVAL = DeferredApproval()
PEER = ACP_PEER.replace(
    "elif method=='session/prompt': r={'stopReason':'end_turn','observedPrompt':p.get('prompt'),'runtimeOptions':options}",
    """elif method=='session/prompt':
        for suffix in ('', ' --other'):
            command = p['prompt'][0]['text'] + suffix
            request = {'sessionId':session_id,'approval':'command','command':command,
                'toolCall':{'kind':'execute','rawInput':{'command':command}},
                'options':[{'kind':'allow_once','optionId':'once'},{'kind':'allow_always','optionId':'always'}]}
            print(json.dumps({'jsonrpc':'2.0','id':'check'+suffix,'method':'session/request_permission','params':request}),flush=True)
            reply=json.loads(sys.stdin.readline())
            if not suffix: first=reply
        r={'stopReason':'end_turn','exact':first,'different':reply}
""")


@pytest.mark.parametrize('live_owner', [{
    'acp_turn_opt_in': True, 'preparation_peer': PEER, 'callback_approval': APPROVAL,
}], indirect=True)
@pytest.mark.parametrize('revoked', [False, True])
def test_native_permission_callback_keeps_original_owner_and_live_business_scope(live_owner, revoked, tmp_path):
    world = live_owner
    authorization = world.owner.authorization()
    unit = world.public_manager.create(world.owner.spec, authorization)
    interaction = None
    seen = []
    @contextmanager
    def original_scope(**request):
        seen.append(request)
        if revoked:
            raise UnitApiRefused('Current original Grant refused')
        yield
    try:
        runtime_root = tmp_path / 'prepared-runtime'
        (runtime_root / 'bin').mkdir(parents=True)
        python = runtime_root / 'bin/python'
        python.write_text('controlled artifact; never executed')
        cfg = runtime_root / 'pyvenv.cfg'
        cfg.write_text('controlled runtime config')
        runner = tmp_path / 'runner.py'
        runner.write_text('controlled runner; never executed')
        command, callback_factory, verify = producer.fixed_catalog_check(
            python_executable=python, runner=runner, project_root=tmp_path,
            pinned_files={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in (python,cfg,runner,Path('/usr/bin/env').resolve())},
            runtime_tree_digest=producer.catalog_runtime_digest(runtime_root),
            allowed_paths=(str(tmp_path/'catalog/views.py'),), scope_guard=original_scope)
        assert verify() is True
        APPROVAL.delegate = callback_factory(
            runtime=SimpleNamespace(unit_execution_owner=world.owner, units=world.public_manager),
            permission=world.owner.permission, environment_instance=world.environment)
        interaction = unit.interaction(authorization)
        result = interaction.prompt({'prompt':[{'type':'text','text':command}]}, timeout=5)
        if revoked:
            assert result['exact']['error']['message'] == 'Callback refused or outcome unavailable; no replay'
            assert result['different']['error']['message'] == 'Callback refused or outcome unavailable; no replay'
        else:
            assert result['exact']['result'] == {'outcome':{'outcome':'selected','optionId':'once'}}
            assert result['different']['result'] == {'outcome':{'outcome':'cancelled'}}
        assert len(seen) == 2
        assert all(request['unit_ref'] == unit.identity for request in seen)
        assert all(request['session_id'] == unit.snapshot()['sessionId'] for request in seen)
    finally:
        if interaction is not None:
            interaction.disconnect()
        unit.close(authorization)
        APPROVAL.delegate = None
