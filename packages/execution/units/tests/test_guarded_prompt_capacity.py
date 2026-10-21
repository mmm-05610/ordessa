"""Large guarded ACP prompts use the original finite receipt capacity."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import sys
from threading import Event
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

# Initialize the public Units surface before importing contracts whose package
# initializers revisit the API/reservation modules.
from ordessa_units.public import decode_node_ref
from ordessa_agents.harness.transport import EffectWriteGuard, EffectWriteRefused
from ordessa_infrastructure.identifiers import RequestKey
from ordessa_units.definitions.operations import OperationIntent, StepIntent
from ordessa_units.records import AcpEvidenceCapacityRefused, OperationJournal, UnitRecords
from ordessa_units.records import acp_turns


def _joint_owner_fixture():
    support = Path(__file__).resolve().parents[2] / 'agents' / 'tests' / 'support'
    if str(support) not in sys.path:
        sys.path.insert(0, str(support))
    from agent_tools_fixtures.manager_joint import build_joint_owner
    import test_unit_instance
    return build_joint_owner, test_unit_instance


def _prepare(joint):
    request = RequestKey('env', 'principal', 'large-prompt-prepare')
    operation = joint.services.assembly.prepare(request, joint.profile, {}, {})
    assert operation.status == 'published'
    node = decode_node_ref(operation.intent.node_ref)
    ref = joint.services.nodes.read(node)['binding']['harnessUnitRef']
    return operation, ref, joint.manager.find(ref)


def _cold_authorized_read(joint, operation, unit_ref, operation_ref, prompt_digest):
    query_digest = UnitRecords.acp_turn_query_digest(unit_ref, operation_ref, prompt_digest)
    request = RequestKey('env', 'principal', 'large-prompt-cold-read')
    context = dict(operation.intent.context_ref)
    context['invocationBindings'] = {'read': {
        'action': 'query', 'targetRef': dict(operation.intent.node_ref),
        'delegationRef': None, 'cleanup': False}}
    intent = OperationIntent('large-prompt-cold-read-operation', 'unit-acp-query',
        operation.intent.profile_snapshot_ref, context,
        (StepIntent('read', operation.intent.steps[0].pinned_provider_ref,
                    query_digest, 'large-prompt-cold-read-step'),),
        dict(operation.intent.node_ref))
    joint.store.reserve_operation(request, query_digest, intent)
    invocation = joint.issuer.issue_query(request, query_digest, 'read')

    def forbidden(*_args, **_kwargs):
        raise AssertionError('cold read must not consult live Unit or ACP evidence')

    cold = UnitRecords(OperationJournal(joint.records.journal.path),
        scope_authority=joint.inputs.scope_authority,
        native_evidence=SimpleNamespace(verify_binding=forbidden),
        verifier=joint.view.verifier, epoch_port=joint.inputs.management_epoch)
    return cold.query_acp_turn(unit_ref, operation_ref, invocation,
        input_digest=query_digest, expected_prompt_input_digest=prompt_digest)


def test_original_guarded_unit_records_and_cold_reads_prompt_above_old_seal_limit(
        tmp_path, monkeypatch):
    build_joint_owner, fixture_helpers = _joint_owner_fixture()
    marker_suffix = '.allow-large-result'
    monkeypatch.setattr(fixture_helpers, 'PEER', fixture_helpers.PEER.replace(
        "elif method=='session/prompt':", """elif method=='session/prompt':
        import time
        while not os.path.exists(os.environ['FIXTURE_CONFIG']+'""" + marker_suffix + """'): time.sleep(.01)"""))
    released = Event()
    state = {'held': False, 'writes': 0, 'released': 0}

    @asynccontextmanager
    async def acquire(identity, deadline):
        assert identity['operationRef'] == 'large-guarded-turn'
        assert identity['inputDigest'].startswith('sha256:')
        state['held'] = True
        try:
            yield
        finally:
            state['held'] = False
            state['released'] += 1
            released.set()

    def guard_factory(unit_ref, operation_ref, input_digest, params):
        return EffectWriteGuard(unit_ref, operation_ref, input_digest, params, acquire)

    with build_joint_owner(tmp_path, acp_turn_opt_in=True,
                           effect_write_guard_factory=guard_factory) as joint:
        operation, unit_ref, unit = _prepare(joint)
        lease = unit.lease_port.grant(unit_ref)
        owned = unit.channel_factory.owned_record
        original_write = owned.process.write_stdin

        # The successful prompt is larger than the old immutable-mapping
        # default (256 KiB), but fits the ACP receipt's published finite budget.
        large_params = {'prompt': [{'type': 'text', 'text': 'P' * 536500}]}
        session = owned.entry.session_id
        full_params = {**large_params, 'sessionId': session}
        prompt_size = len(acp_turns._json(full_params).encode('utf-8'))
        assert 536518 <= prompt_size < acp_turns.MAX_PROMPT_BYTES
        expected_input_digest = UnitRecords.acp_prompt_input_digest(unit_ref, full_params)

        async def observed_write(data, *, timeout=None):
            assert state['held'] is True
            state['writes'] += 1
            return await original_write(data, timeout=timeout)

        owned.process.write_stdin = observed_write
        allow_result = Path(owned.prepared_agent.harness.launch_spec.env['FIXTURE_CONFIG'] + marker_suffix)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(unit.prompt, unit_ref, lease,
                operation_ref='large-guarded-turn', timeout=5, **large_params)
            try:
                assert released.wait(3)
                assert not pending.done()  # The original peer still withholds its response.
                assert state == {'held': False, 'writes': 1, 'released': 1}
            finally:
                allow_result.write_text('allow')
            receipt = pending.result(timeout=8)

        assert receipt['state'] == 'completed'
        assert receipt['inputDigest'] == expected_input_digest
        assert state == {'held': False, 'writes': 1, 'released': 1}
        with joint.records.journal._connect() as db:
            stored = db.execute(
                'SELECT body_json FROM harness_acp_turn_attempts WHERE operation_ref=?',
                ('large-guarded-turn',)).fetchone()
        assert stored is not None
        from ordessa_infrastructure.encoding.immutable_json import safe_json
        assert stored['body_json'] == safe_json(
            receipt, max_bytes=acp_turns.MAX_EVIDENCE_BYTES)
        assert _cold_authorized_read(joint, operation, unit_ref,
            'large-guarded-turn', expected_input_digest) == receipt

        oversized = {'prompt': [{'type': 'text',
                                 'text': 'O' * (acp_turns.MAX_PROMPT_BYTES + 1)}]}
        writes_before = state['writes']
        with pytest.raises(AcpEvidenceCapacityRefused):
            unit.prompt(unit_ref, lease, operation_ref='over-limit-turn', timeout=2,
                        **oversized)
        assert state['writes'] == writes_before
        with joint.records.journal._connect() as db:
            assert db.execute(
                'SELECT count(*) FROM harness_acp_turn_attempts WHERE operation_ref=?',
                ('over-limit-turn',)).fetchone()[0] == 0


def test_large_mismatched_frame_still_refuses_before_guard_acquisition_or_write():
    from unittest.mock import AsyncMock, MagicMock
    from types import SimpleNamespace
    from ordessa_environments import ProcessHandle
    from ordessa_units.sessions.environment_channel import EnvironmentProcessChannel

    async def exercise():
        large_params = {'sessionId': 'session',
                        'prompt': [{'type': 'text', 'text': 'Q' * 536500}]}
        digest = 'sha256:' + 'a' * 64
        calls = {'acquire': 0, 'write': 0}

        @asynccontextmanager
        async def acquire(_identity, _deadline):
            calls['acquire'] += 1
            yield

        async def write(_data, *, timeout=None):
            calls['write'] += 1
            return len(_data)

        process = MagicMock(spec=ProcessHandle)
        process.observe.return_value = SimpleNamespace(state='running')
        process.read_stderr = AsyncMock(return_value=b'')
        process.write_stdin = write
        transport = EnvironmentProcessChannel(process, name='large-controlled', managed=True)
        view = transport.bind_writer(transport.acquire_writer())
        unit_ref = {'environmentNamespace': 'env', 'unitId': 'unit',
                    'ownerProviderRef': {}, 'sourceRevision': 'rev'}
        guard = EffectWriteGuard(unit_ref, 'large-operation', digest,
                                 large_params, acquire)
        different = dict(large_params, prompt=[{'type': 'text',
                                                'text': 'R' * 536500}])
        frame = (('{' + '"jsonrpc":"2.0","id":1,"method":"session/prompt","params":' +
                  __import__('json').dumps(different, separators=(',', ':')) + '}\n').encode())
        with pytest.raises(EffectWriteRefused):
            await view.send_frame_async(frame, before_write=lambda: None,
                                        effect_write_guard=guard)
        assert calls == {'acquire': 0, 'write': 0}
        assert transport._unresolved
        if transport._stderr_task is not None:
            await transport._stderr_task

    asyncio.run(exercise())
