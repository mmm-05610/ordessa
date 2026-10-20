"""Exact original Unit V1/V2 stored readback; no Unit runtime or send revival."""
from dataclasses import asdict, replace
import hashlib
from pathlib import Path
import pytest
from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.application.contracts.dispatch_identity import work_dispatch_key
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.work_context import WORK_CONTEXT_KIND, WORK_STABLE_ID_PREFIX
from ordessa_engineering.domain.changes.dispatch import package_ref_projection
from ordessa_engineering.domain.changes.dispatch_codec import decode_dispatch, encode_dispatch
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_interfaces.system_access.access_control.authentication import InstanceAccessAuthority, AccessGrant
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_system_access_bindings.engineering_access import EngineeringCommandAccess
from ordessa_server.composition.engineering_bindings.dispatch_routes import EngineeringDispatchRoutes, _stored_binding_kind

ROOT = Path(__file__).parents[3]
READ = 'engineering.implementation.get_dispatch'
RECONCILE = 'engineering.implementation.reconcile'


@pytest.mark.parametrize('version', [1, 2])
def test_original_historical_read_entry_preserves_old_rows_without_unit_runtime(tmp_path, monkeypatch, version):
    raw = (ROOT/'packages/engineering/tests/domain/fixtures/dispatch-v1-baseline.json').read_bytes()
    binding = decode_dispatch(raw)
    if version == 2:
        key = work_dispatch_key('historical-work','historical-action',binding.step_id)
        binding = replace(binding, run_id=key, binding_version=2,
            work={'work_id':'historical-work','action_id':'historical-action','step_id':binding.step_id,'dispatch_key':key},
            subject={'subject_kind':'frozen_package','subject_ref':package_ref_projection(binding.package_ref)})
        raw = encode_dispatch(binding)
    library = EngineeringLibrary.create((tmp_path/'history.sqlite').resolve(), library_id='original-history',schema_version=17)
    factory = SQLiteUoWFactory(library)
    try:
        # Historical storage fixture seed, not a current Work creation path.
        # The real current write_work authority is deliberately not reconstructed.
        with library.transaction() as db:
            if version == 1:
                db.execute('INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?)',
                    (binding.run_id,'{}','{}','{}','RUNNING',0,None,'now','now'))
            else:
                body = canonical_bytes({'work_id':'historical-work','scope':asdict(binding.scope)})
                db.execute('INSERT INTO materials VALUES (?,?,?,?,?,?)',
                    (WORK_CONTEXT_KIND,WORK_STABLE_ID_PREFIX+'historical-work',1,
                     hashlib.sha256(body).hexdigest(),body.decode(),0))
        with factory.begin(binding.scope) as uow:
            repo = uow.dispatch if version == 1 else uow.work_dispatch
            repo.reserve(binding.run_id,binding.step_id,binding.attempt,binding.scope,raw,
                Digest('sha256',hashlib.sha256(raw).hexdigest()),binding.execution_operation_ref)
            repo.transition(binding.run_id,binding.step_id,binding.attempt,binding.scope,
                expected_version=0,fence=binding.fence,phase='possibly_written')
            repo.transition(binding.run_id,binding.step_id,binding.attempt,binding.scope,
                expected_version=1,fence=binding.fence,phase='unknown')
            uow.commit()
        scope = Scope(binding.scope.realm_id,binding.scope.project_id)
        issuer = InstanceAccessAuthority(lambda:'synthetic-history-token',principal_id='historical-reader',
            grants=(AccessGrant(scope,(READ,RECONCILE)),),legacy_principal=None)
        access = EngineeringCommandAccess(issuer)
        caller = issuer.authenticate('Bearer synthetic-history-token')
        routes = EngineeringDispatchRoutes(factory,access)
        def no_process(*args,**kwargs):
            raise AssertionError('historical read constructed a runtime/process')
        monkeypatch.setattr('subprocess.Popen', no_process)
        before = library._connection.total_changes
        params = {'run_id':binding.run_id,'step_id':binding.step_id,'attempt':binding.attempt}
        with access.admit(caller,scope,READ,request_id='history-read',trace_id='trace') as context:
            value = routes.invoke(READ,params,context)
        assert value['historical'] is True and value['phase'] == 'unknown'
        assert value['binding'] == binding.projection()
        assert not value['accepted'] and not value['engineering_completed']
        with access.admit(caller,scope,RECONCILE,request_id='history-reconcile',trace_id='trace') as context:
            with pytest.raises(ApplicationError,match='HISTORICAL_DISPATCH_READ_AUTHORITY_UNBOUND'):
                routes.invoke(RECONCILE,params,context)
        assert library._connection.total_changes == before
        with factory.begin(binding.scope,'read') as uow:
            repo = uow.dispatch if version == 1 else uow.work_dispatch
            stored = repo.get(binding.run_id,binding.step_id,binding.attempt,binding.scope)
        assert stored['binding_bytes'] == raw and stored['dispatch_phase'] == 'unknown'
        assert stored['dispatch_version'] == 2
    finally:
        library.close()


def test_unknown_or_broken_agent_schema_never_falls_back_to_unit_history():
    for value in ({'schemaVersion':'foreign','unit_ref_bytes':{}},
                  {'schemaVersion':'engineering-dispatch-binding/2.1','unit_ref_bytes':{}}):
        if value['schemaVersion'] == 'foreign':
            with pytest.raises(ApplicationError):
                _stored_binding_kind(canonical_bytes(value))
        else:
            assert _stored_binding_kind(canonical_bytes(value)) == 'agent'
