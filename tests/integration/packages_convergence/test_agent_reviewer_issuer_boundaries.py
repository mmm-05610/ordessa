"""Original issuer negatives before business snapshot load; NOT full assembly."""
import contextvars
from dataclasses import replace
from types import SimpleNamespace
import pytest
from ordessa_interfaces.system_access.access_control.authentication import InstanceAccessAuthority,AccessGrant,AccessError
from ordessa_interfaces.system_access.contracts.refs import Scope as WireScope
from ordessa_system_access_bindings.engineering_access import EngineeringCommandAccess
from ordessa_engineering.application.usecases.reviews.assignments import ReviewerAssignmentUseCases,ASSIGN_REVIEWER
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.common.models.identity import Scope,ActorRef
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory


def test_original_reviewer_issuer_no_default_grant_and_no_attribution_self_sign(tmp_path):
    scope=Scope('realm','project');wire=WireScope('realm','project')
    library=EngineeringLibrary.create((tmp_path/'engineering.sqlite').resolve(),library_id='issuer-negatives',schema_version=15)
    factory=SQLiteUoWFactory(library)
    authority=InstanceAccessAuthority(lambda:'synthetic-test-token',principal_id='original-machine',legacy_principal=None,
        grants=(AccessGrant(wire,(ASSIGN_REVIEWER,)),))
    access=EngineeringCommandAccess(authority)
    # Explicit ports never reached by these negatives; they must not return
    # fabricated identity/roles or approve a missing business method snapshot.
    def unreachable(*args,**kwargs):raise AssertionError('business/Agent source reached before issuer check')
    methods=SimpleNamespace(factory=factory,guard_method=unreachable)
    usecase=ReviewerAssignmentUseCases(factory,methods,SimpleNamespace(read_agent_reference=unreachable),
        expected_access=access,expected_scope=scope,agent_query_factory=unreachable)
    caller=authority.authenticate('Bearer synthetic-test-token')
    try:
        with access.admit(caller,wire,ASSIGN_REVIEWER,request_id='assignment',trace_id='trace') as ctx:
            for forged in (replace(ctx,principal_id='human'),replace(ctx,authenticated_actor=ActorRef('human','human','caller')),
                    replace(ctx,scope=Scope('realm','foreign'))):
                with pytest.raises(ApplicationError):usecase._authorize(forged,ASSIGN_REVIEWER)
            copied=contextvars.copy_context()
            with usecase._authorize(ctx,ASSIGN_REVIEWER) as selected:
                assert selected.principal_id=='original-machine' and selected.credential_epoch==0
                with pytest.raises(AccessError):authority.revoke()
        with pytest.raises(ApplicationError):copied.run(usecase._authorize,ctx,ASSIGN_REVIEWER)
        authority.revoke()
        with pytest.raises(AccessError):
            with access.admit(caller,wire,ASSIGN_REVIEWER,request_id='stale',trace_id='trace'):pass
        no_grants=InstanceAccessAuthority(lambda:'synthetic-no-grants',principal_id='same-machine',legacy_principal=None,grants=())
        unprivileged=no_grants.authenticate('Bearer synthetic-no-grants')
        with pytest.raises(AccessError):
            with EngineeringCommandAccess(no_grants).admit(unprivileged,wire,ASSIGN_REVIEWER,request_id='none',trace_id='trace'):pass
        assert library._connection.execute('SELECT count(*) FROM eng_unit_reviewer_assignments').fetchone()==(0,)
        assert library._connection.execute('SELECT count(*) FROM eng_action_consumptions').fetchone()==(0,)
    finally:library.close()
