"""Versioned Agent Work values and authored candidate; no live write grant."""
from dataclasses import fields, replace
from pathlib import Path
import json
import pytest
from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ordessa_engineering.domain.changes.agent_dispatch import AgentWorkDispatchBinding, WORK_SCHEMA_VERSION
from ordessa_engineering.domain.changes.agent_dispatch_codec import decode_agent_dispatch, encode_agent_dispatch
from ordessa_engineering.domain.changes.dispatch import package_ref_projection
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
from ordessa_engineering.application.contracts.dispatch_identity import work_dispatch_key
from ordessa_engineering.application.orchestration.owner_capabilities import agent_dispatch_capability, owner_capabilities
from ordessa_engineering.methods.definitions.models import MethodSource
from ordessa_engineering.methods.loading.loader import load_method
from ordessa_engineering.methods import read_method_definition, compile_method
from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader
import sys
SUPPORT=Path(__file__).parents[3]/'packages/engineering/tests/domain'
if str(SUPPORT) not in sys.path:sys.path.insert(0,str(SUPPORT))
from test_agent_dispatch_codec import agent_binding


def binding():
    old=agent_binding()
    key=work_dispatch_key('work-1','incremental.implement-package','implement')
    values={f.name:getattr(old,f.name) for f in fields(old) if f.init}
    values.update(run_id=key,step_id='implement')
    return AgentWorkDispatchBinding(**values,
        work={'work_id':'work-1','action_id':'incremental.implement-package',
              'step_id':'implement','dispatch_key':key},
        subject={'subject_kind':'frozen_package','subject_ref':package_ref_projection(old.package_ref)})


def test_explicit_agent_work_version_roundtrip_preserves_subject_work_and_turn():
    value=binding();raw=encode_agent_dispatch(value)
    assert decode_agent_dispatch(raw)==value
    assert decode_json(raw)['schemaVersion']==WORK_SCHEMA_VERSION
    assert value.binding_version==2 and value.work['dispatch_key']==value.run_id
    assert 'unit_ref_bytes' not in decode_json(raw)
    assert 'execution_operation_ref' not in decode_json(raw)
    old=agent_binding()
    assert encode_agent_dispatch(decode_agent_dispatch(encode_agent_dispatch(old)))==encode_agent_dispatch(old)
    assert old.projection()['schemaVersion']=='engineering-dispatch-binding/2.1'


@pytest.mark.parametrize('change',[
    {'turn_ref_bytes':None}, {'subject':{'subject_kind':'reviewed_change','subject_ref':{}}},
    {'work':{'work_id':'work-1','action_id':'a','step_id':'foreign','dispatch_key':'w1:a:b:c'}},
])
def test_agent_work_never_drops_missing_or_foreign_work_turn_checks(change):
    with pytest.raises(ReferenceError):replace(binding(),**change)


def test_latest_action_candidate_loads_original_schema_and_pins_v2_resource():
    root=Path(__file__).parents[3]/'methods/incremental-engineering/candidates/2.7.3'
    loaded=load_method(MethodSource(root,'method.json'),FileResourceReader())
    assert loaded.ok,loaded.error
    definition=read_method_definition(loaded.value)
    assert definition.ok,definition.error
    value=definition.value
    assert value.release_version=='2.7.3'
    action=next(a for a in value.actions if a.action_id=='incremental.implement-package')
    step=next(s for s in action.steps if s.step_id=='implement')
    assert any(i.source_kind=='resource' and i.source_name=='agent-dispatch-contract' for i in step.inputs)
    contract=json.loads((root/'schemas/agent-dispatch-contract.json').read_text())
    descriptor=agent_dispatch_capability()
    assert contract['x-ordessa-capability-binding']=={k:getattr(descriptor,k) for k in
        ('capability_id','kind','interface_version','contract_digest')}
    assert descriptor.interface_version=='2'
    assert contract['$id'].endswith(':input:2')
    assert descriptor.contract['input_schema']=={k:v for k,v in contract.items() if k not in ('$schema','$id','x-ordessa-capability-binding')}
    old=next(d for d in owner_capabilities() if d.capability_id==descriptor.capability_id)
    assert old.interface_version=='1' and old.contract_digest!=descriptor.contract_digest


def test_new_agent_work_bytes_reserve_on_original_work_relation_and_reject_substituted_subject():
    import sqlite3
    from types import SimpleNamespace
    from ordessa_engineering.adapters.persistence.sqlite.dispatch_repository import SQLiteWorkDispatchRepository
    from ordessa_engineering.application.contracts.errors import ApplicationError
    from ordessa_engineering.domain.common.models.values import Digest
    import hashlib
    persistence=Path(__file__).parents[3]/'packages/engineering/tests/persistence'
    if str(persistence) not in sys.path:sys.path.insert(0,str(persistence))
    from test_work_dispatch_repository import _database, _Access
    value=binding()
    connection,_old_access=_database()
    try:
        body=canonical_bytes({'work_id':'work-1','scope':{'realm_id':value.scope.realm_id,
            'project_id':value.scope.project_id},'method_ref':{'method_id':'m','release_version':'2.7.3',
            'snapshot_digest':'a'*64},'revision':1}).decode()
        connection.execute('UPDATE materials SET body_json=? WHERE stable_id=?',(body,'declarative-work:work-1'))
        repo=SQLiteWorkDispatchRepository(_Access(connection,value.scope))
        raw=encode_agent_dispatch(value)
        row=repo.reserve(value.run_id,value.step_id,value.attempt,value.scope,raw,
            Digest('sha256',hashlib.sha256(raw).hexdigest()),value.engineering_attempt_ref)
        assert row['binding_bytes']==raw
        assert repo.by_operation(value.engineering_attempt_ref,value.scope)['binding_bytes']==raw
        assert decode_agent_dispatch(row['binding_bytes'])==value
        changed=replace(value,attempt=2,subject={'subject_kind':'frozen_package','subject_ref':{'foreign':'package'}})
        bad=encode_agent_dispatch(changed)
        with pytest.raises(ApplicationError,match='DISPATCH_BINDING_INVALID'):
            repo.reserve(changed.run_id,changed.step_id,changed.attempt,changed.scope,bad,
                Digest('sha256',hashlib.sha256(bad).hexdigest()),'other-operation')
        assert connection.execute('SELECT count(*) FROM work_step_log').fetchone()[0]==1
        assert connection.execute('SELECT count(*) FROM step_log').fetchone()[0]==0
    finally:connection.close()
