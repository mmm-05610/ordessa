"""V2 reference migration without grants/runtime or changes to business invariants."""
from dataclasses import fields, replace
from pathlib import Path
import hashlib

import pytest

from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.domain.changes.agent_dispatch import AgentDispatchBinding
from ordessa_engineering.domain.changes.agent_dispatch_codec import (
    encode_agent_dispatch, decode_agent_dispatch, read_historical_dispatch,
)
from ordessa_engineering.domain.changes.dispatch_codec import decode_dispatch, encode_dispatch
from ordessa_engineering.domain.common.models.execution_refs import agent_instance_ref_bytes
from ordessa_engineering.domain.common.models.identity import Scope
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError

BASELINE = Path(__file__).parent/'fixtures/dispatch-v1-baseline.json'


# This fixture is the frozen V1 historical input from a23, not a current Work
# dispatch projection. Current binding_version/work/subject remain UNMAPPED;
# these tests do not qualify that newer recipe or its business write checks.
FROZEN_V1_FIELDS = frozenset((
    'scope', 'run_id', 'step_id', 'attempt', 'fence', 'package_ref', 'approval_ref',
    'intent_digest', 'control_version', 'action_instances', 'unit_ref_bytes',
    'execution_operation_ref', 'prompt_ref', 'prompt_input_digest',
    'expected_query_digest', 'required_results', 'digest',
))



def old_binding():
    return decode_dispatch(BASELINE.read_bytes())


def agent_binding():
    old = old_binding()
    values = {f.name:getattr(old, f.name) for f in fields(old) if f.name in FROZEN_V1_FIELDS and f.init and f.name != 'unit_ref_bytes'}
    values['engineering_attempt_ref']=values.pop('execution_operation_ref')
    agent={'schemaVersion':'agent-instance/1','namespace':'namespace','instanceId':'agent-instance',
        'bindingDigest':'sha256:'+'c'*64}
    turn={'schemaVersion':'agent-turn-ref/1','instanceRef':agent,'turnId':'original-domain-fixture-turn'}
    query={'schemaVersion':'agent-turn-query/1','turnRef':turn,'expectedInputDigest':'sha256:'+old.prompt_input_digest.hex}
    values['expected_query_digest']='sha256:'+hashlib.sha256(canonical_bytes(query)).hexdigest()
    return AgentDispatchBinding(**values,turn_ref_bytes=canonical_bytes(turn),agent_ref_bytes=agent_instance_ref_bytes({
        'schemaVersion':'agent-instance/1','namespace':'namespace','instanceId':'agent-instance',
        'bindingDigest':'sha256:'+'c'*64}))


def test_baseline_v1_canonical_bytes_and_original_digest_remain_exact():
    raw = BASELINE.read_bytes()
    assert encode_dispatch(old_binding()) == raw
    assert old_binding().digest == Digest('sha256','bc304f269cbeea668b3baec2485992f438bcc2858275b6a67d908aacbe822082')
    historical = read_historical_dispatch(raw)
    assert historical.raw_bytes == raw
    assert historical.original_digest == old_binding().digest
    assert hashlib.sha256(historical.raw_bytes).digest() == hashlib.sha256(raw).digest()
    with pytest.raises(TypeError):
        historical.facts['unit_ref_bytes']['ownerProviderRef']['provider'] = 'replacement'
    with pytest.raises(ReferenceError):
        encode_agent_dispatch(historical)


def test_v2_roundtrip_preserves_all_business_facts_but_versions_identity_and_digest():
    old, new = old_binding(), agent_binding()
    assert decode_agent_dispatch(encode_agent_dispatch(new)) == new
    for f in fields(old):
        if f.name in FROZEN_V1_FIELDS and f.name not in ('unit_ref_bytes','digest','execution_operation_ref','expected_query_digest'):
            assert getattr(new,f.name) == getattr(old,f.name)
    assert new.engineering_attempt_ref == old.execution_operation_ref
    assert "execution_operation_ref" not in new.projection()
    assert new.digest != old.digest
    assert new.projection()['schemaVersion'] == 'engineering-dispatch-binding/2.1'
    from ordessa_infrastructure.encoding import decode_json
    query={'schemaVersion':'agent-turn-query/1','turnRef':decode_json(new.turn_ref_bytes),
        'expectedInputDigest':'sha256:'+new.prompt_input_digest.hex}
    assert new.expected_query_digest=='sha256:'+hashlib.sha256(canonical_bytes(query)).hexdigest()
    assert 'unit_ref_bytes' not in new.projection()
    assert 'grant' not in new.projection()['agent_ref_bytes']
    with pytest.raises(ReferenceError):decode_agent_dispatch(BASELINE.read_bytes())
    with pytest.raises(ReferenceError):decode_dispatch(encode_agent_dispatch(new))
    with pytest.raises(ReferenceError):read_historical_dispatch(encode_agent_dispatch(new))
    with pytest.raises(ReferenceError):replace(new,agent_ref_bytes=old.unit_ref_bytes)


@pytest.mark.parametrize('changes',[
    {'attempt':0}, {'attempt':True}, {'fence':0}, {'control_version':-1},
    {'run_id':''}, {'execution_operation_ref':'bad\noperation'},
    {'scope':Scope('other-realm','project')},
    {'action_instances':()},
    {'action_instances':(('edit_repository','same'),('run_checks','same'))},
    {'action_instances':(('run_checks','a'),('run_checks','b'))},
    {'action_instances':(('apply_change','forbidden'),)},
    {'action_instances':(('generate_package','forbidden'),)},
    {'required_results':()}, {'required_results':('same','same')},
    {'prompt_input_digest':'sha256:'+'a'*64},
])
def test_original_business_rejections_are_identical_for_both_versions(changes):
    for binding in (old_binding(),agent_binding()):
        version_changes=dict(changes)
        if type(binding) is AgentDispatchBinding and 'execution_operation_ref' in version_changes:
            version_changes['engineering_attempt_ref']=version_changes.pop('execution_operation_ref')
        with pytest.raises(ReferenceError):replace(binding,**version_changes)


@pytest.mark.parametrize('mutate',[
    lambda p:p.update(schemaVersion='engineering-dispatch-binding/1'),
    lambda p:p.update(unit_ref_bytes={}),
    lambda p:p['digest'].update(hex='0'*64),
    lambda p:p.update(engineering_attempt_ref='another-attempt'),
    lambda p:p['agent_ref_bytes'].update(instanceId='different-instance'),
    lambda p:p['agent_ref_bytes'].update(useRef='forbidden'),
])
def test_closed_v2_codec_rejects_cross_version_extra_fields_and_tampering(mutate):
    from ordessa_infrastructure.encoding import decode_json
    value=decode_json(encode_agent_dispatch(agent_binding()))
    mutate(value)
    with pytest.raises(ReferenceError):decode_agent_dispatch(canonical_bytes(value))


def test_noncanonical_duplicate_keys_and_oversized_records_fail_closed():
    raw=encode_agent_dispatch(agent_binding())
    for bad in (b'[]',b'null',b'0',b' '+raw, raw[:-1]+b',"schemaVersion":"engineering-dispatch-binding/2"}', b' '*262145):
        with pytest.raises(ReferenceError):decode_agent_dispatch(bad)


def test_binding_digest_cannot_be_mutated_and_history_does_not_become_online_authority():
    new=agent_binding()
    raw=encode_agent_dispatch(new)
    with pytest.raises((AttributeError,TypeError)):new.agent_ref_bytes=b'{}'
    with pytest.raises(ReferenceError):encode_agent_dispatch(old_binding())
    assert encode_agent_dispatch(new)==raw


def test_pre_f2_v2_retains_original_bytes_and_digest_but_has_no_cold_query_or_new_write_binding():
    raw=(BASELINE.parent/'dispatch-v2-pre-f2-baseline.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest()=='ed0b5179e3abcd09b02fbebe1cd03a5f4b084df98b80d43376d4b6f18e51f252'
    old=decode_agent_dispatch(raw)
    assert old.digest.hex=='5474cb98c0836952c5c9203cf919272d401b46353f880317ea5ee6352b927992'
    assert old.turn_ref_bytes is None and encode_agent_dispatch(old)==raw
    with pytest.raises(ReferenceError,match='AGENT_DISPATCH_TURN_REFERENCE_UNAVAILABLE'):old.require_turn_binding()


@pytest.mark.parametrize('change',[
    lambda v:v.pop('turn_ref_bytes'),lambda v:v.update(turn_ref_bytes=None),
    lambda v:v['turn_ref_bytes'].update(turnId='foreign'),
    lambda v:v['turn_ref_bytes']['instanceRef'].update(instanceId='foreign'),
    lambda v:v.update(prompt_input_digest={'algorithm':'sha256','hex':'f'*64}),
])
def test_f2_turn_instance_input_query_binding_rejects_missing_null_and_tampering(change):
    from ordessa_infrastructure.encoding import decode_json
    value=decode_json(encode_agent_dispatch(agent_binding()));change(value)
    with pytest.raises(ReferenceError):decode_agent_dispatch(canonical_bytes(value))
