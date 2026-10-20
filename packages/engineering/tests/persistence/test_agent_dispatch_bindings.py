"""Real original SQLite repository stores v2 facts without creating execution authority."""
from dataclasses import fields,replace
from pathlib import Path
import hashlib

import pytest
from ordessa_infrastructure.encoding import canonical_bytes

from test_dispatch_repository import _database, SCOPE
from ordessa_engineering.adapters.persistence.sqlite.dispatch_repository import SQLiteDispatchRepository
from ordessa_engineering.adapters.persistence.sqlite.agent_dispatch_bindings import AgentDispatchBindings
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.changes.agent_dispatch import AgentDispatchBinding
from ordessa_engineering.domain.changes.dispatch_codec import decode_dispatch
from ordessa_engineering.domain.common.models.execution_refs import agent_instance_ref_bytes
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.common.models.identity import Scope


# This fixture is the frozen V1 historical input from a23, not a current Work
# dispatch projection. Current binding_version/work/subject remain UNMAPPED;
# these tests do not qualify that newer recipe or its business write checks.
FROZEN_V1_FIELDS = frozenset((
    'scope', 'run_id', 'step_id', 'attempt', 'fence', 'package_ref', 'approval_ref',
    'intent_digest', 'control_version', 'action_instances', 'unit_ref_bytes',
    'execution_operation_ref', 'prompt_ref', 'prompt_input_digest',
    'expected_query_digest', 'required_results', 'digest',
))



def binding():
    old=decode_dispatch((Path(__file__).parents[1]/'domain/fixtures/dispatch-v1-baseline.json').read_bytes())
    values={f.name:getattr(old,f.name) for f in fields(old) if f.name in FROZEN_V1_FIELDS and f.init and f.name!='unit_ref_bytes'}
    values['engineering_attempt_ref']=values.pop('execution_operation_ref')
    agent={'schemaVersion':'agent-instance/1','namespace':'namespace','instanceId':'instance','bindingDigest':'sha256:'+'c'*64}
    turn={'schemaVersion':'agent-turn-ref/1','instanceRef':agent,'turnId':'original-storage-fixture-turn'}
    query={'schemaVersion':'agent-turn-query/1','turnRef':turn,'expectedInputDigest':'sha256:'+old.prompt_input_digest.hex}
    values['expected_query_digest']='sha256:'+hashlib.sha256(canonical_bytes(query)).hexdigest()
    values['turn_ref_bytes']=canonical_bytes(turn)
    return AgentDispatchBinding(**{**values,'scope':SCOPE,'run_id':'run-1','step_id':'step-1',
        'package_ref':replace(old.package_ref,realm_id=SCOPE.realm_id,project_id=SCOPE.project_id),
        'approval_ref':replace(old.approval_ref,realm_id=SCOPE.realm_id,project_id=SCOPE.project_id)},
        agent_ref_bytes=agent_instance_ref_bytes({'schemaVersion':'agent-instance/1','namespace':'namespace',
            'instanceId':'instance','bindingDigest':'sha256:'+'c'*64}))


def test_v2_binding_roundtrip_uses_original_step_log_and_retains_no_execution_authority():
    connection,access=_database();repo=SQLiteDispatchRepository(access)
    adapter=AgentDispatchBindings(repo);new=binding()
    row=adapter.reserve(new)
    loaded,decoded=adapter.read(new.run_id,new.step_id,new.attempt,SCOPE)
    assert decoded==new and loaded==row
    assert loaded['binding_digest']==Digest('sha256',hashlib.sha256(loaded['binding_bytes']).hexdigest())
    assert loaded['binding_digest']!=new.digest  # exact byte hash vs original domain tagged hash
    assert connection.execute('SELECT count(*) FROM step_log').fetchone()==(1,)
    assert not hasattr(adapter,'send') and not hasattr(adapter,'acquire')
    with pytest.raises(ApplicationError,match='DISPATCH_ATTEMPT_CONFLICT'):adapter.reserve(new)
    with pytest.raises(ApplicationError,match='NOT_FOUND'):
        adapter.read('run-1','absent',1,SCOPE)


def test_original_scope_and_active_transaction_guards_still_protect_v2():
    _,access=_database();adapter=AgentDispatchBindings(SQLiteDispatchRepository(access));new=binding()
    adapter.reserve(new)
    with pytest.raises(ApplicationError,match='SCOPE_MISMATCH'):
        adapter.read('run-1','step-1',1,Scope('foreign','project'))
    access.active=False
    with pytest.raises(ApplicationError,match='UOW_NOT_ACTIVE'):adapter.read('run-1','step-1',1,SCOPE)


def test_old_binding_is_never_admitted_as_v2_or_implicitly_converted():
    _,access=_database();repo=SQLiteDispatchRepository(access);adapter=AgentDispatchBindings(repo)
    old=decode_dispatch((Path(__file__).parents[1]/'domain/fixtures/dispatch-v1-baseline.json').read_bytes())
    with pytest.raises(ApplicationError,match='AGENT_DISPATCH_BINDING_REQUIRED'):adapter.reserve(old)
    from ordessa_engineering.domain.changes.dispatch_codec import encode_dispatch
    raw=encode_dispatch(old)
    repo.reserve('run-1','step-1',1,SCOPE,raw,Digest('sha256',hashlib.sha256(raw).hexdigest()),old.execution_operation_ref)
    with pytest.raises(ApplicationError,match='AGENT_DISPATCH_BINDING_INVALID'):adapter.read('run-1','step-1',1,SCOPE)


def test_original_repository_does_not_mask_v2_binding_identity_mismatch():
    _,access=_database();repo=SQLiteDispatchRepository(access);adapter=AgentDispatchBindings(repo)
    from ordessa_engineering.domain.changes.agent_dispatch_codec import encode_agent_dispatch
    raw=encode_agent_dispatch(binding())
    repo.reserve('run-1','different-step',1,SCOPE,raw,Digest('sha256',hashlib.sha256(raw).hexdigest()),'different-operation')
    with pytest.raises(ApplicationError,match='AGENT_DISPATCH_BINDING_MISMATCH'):
        adapter.read('run-1','different-step',1,SCOPE)


def test_pre_f2_missing_turn_record_stays_byte_exact_but_online_reserve_and_read_are_unavailable():
    connection,access=_database();repo=SQLiteDispatchRepository(access);adapter=AgentDispatchBindings(repo)
    old=replace(binding(),turn_ref_bytes=None)
    from ordessa_engineering.domain.changes.agent_dispatch_codec import encode_agent_dispatch
    raw=encode_agent_dispatch(old)
    with pytest.raises(ApplicationError,match='AGENT_DISPATCH_TURN_REFERENCE_UNAVAILABLE'):adapter.reserve(old)
    assert connection.execute('SELECT count(*) FROM step_log').fetchone()==(0,)
    # Explicit historical insertion in this temporary storage fixture only.
    repo.reserve('run-1','step-1',1,SCOPE,raw,Digest('sha256',hashlib.sha256(raw).hexdigest()),old.engineering_attempt_ref)
    with pytest.raises(ApplicationError,match='AGENT_DISPATCH_TURN_REFERENCE_UNAVAILABLE'):
        adapter.read('run-1','step-1',1,SCOPE)
    assert repo.get('run-1','step-1',1,SCOPE)['binding_bytes']==raw
