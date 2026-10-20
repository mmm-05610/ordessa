"""Prior generation input uses the original, exact dispatch admission lease."""
from contextvars import copy_context

import pytest

from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.orchestration.steps.declared_generation_dispatch import (
    DeclaredGenerationDispatch)
from ordessa_interfaces.system_access.access_control.authentication import (
    AccessGrant, InstanceAccessAuthority)
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_system_access_bindings.engineering import EngineeringCommandAccess


SCOPE = Scope('generation-rework-realm', 'generation-rework-project')
INVOKE = 'engineering.work.invoke'
DISPATCH = 'engineering.executions.dispatch'
GET = 'engineering.work.get'


class _ReadReached(Exception):
    pass


class _Factory:
    """Storage marker: these tests isolate the production access boundary."""
    def __init__(self):
        self.reads = []

    def begin(self, scope, mode):
        self.reads.append((scope, mode))
        raise _ReadReached


def _case():
    authority = InstanceAccessAuthority(lambda: 'controlled-rework-token',
        principal_id='generation-rework-caller', legacy_principal=None,
        grants=(AccessGrant(SCOPE, (INVOKE, GET, DISPATCH)),))
    caller = authority.authenticate('Bearer controlled-rework-token')
    access = EngineeringCommandAccess(authority)
    factory = _Factory()
    owner = DeclaredGenerationDispatch(factory, access, blobs=None, execution=None,
                                       review_admission=None, method_guard=None)
    return caller, access, factory, owner


def _read(owner, context):
    return owner.read_completed_generation('prior-completed-operation', context,
        current_work_id='fresh-work', change_ref=None, review_ref=None,
        method_ref=None, baseline=None, candidate=None)


def test_completed_input_reader_reaches_storage_under_exact_dispatch_child():
    caller, access, factory, owner = _case()
    with access.admit(caller, SCOPE, INVOKE, request_id='parent', trace_id='rework') as parent:
        with access.admit_work_step(parent, DISPATCH, request_id='child') as child:
            with pytest.raises(_ReadReached):
                _read(owner, child)
    assert len(factory.reads) == 1 and factory.reads[0][1] == 'read'


@pytest.mark.parametrize('operation', [INVOKE, GET])
def test_other_operation_context_cannot_read_prior_generation(operation):
    caller, access, factory, owner = _case()
    with access.admit(caller, SCOPE, operation, request_id='other', trace_id='rework') as context:
        with pytest.raises(ApplicationError, match='ACCESS_AUTHORITY_UNAVAILABLE'):
            _read(owner, context)
    assert factory.reads == []


def test_copied_or_expired_dispatch_context_cannot_read_prior_generation():
    caller, access, factory, owner = _case()
    with access.admit(caller, SCOPE, INVOKE, request_id='parent', trace_id='rework') as parent:
        with access.admit_work_step(parent, DISPATCH, request_id='child') as child:
            copied = copy_context()
            forged = type(child)(child.scope, child.principal_id, child.authenticated_actor,
                child.request_id, child.received_at, child.trace_id)
            with pytest.raises(ApplicationError, match='ACCESS_AUTHORITY_UNAVAILABLE'):
                _read(owner, forged)
        with pytest.raises(ApplicationError, match='ACCESS_AUTHORITY_UNAVAILABLE'):
            copied.run(_read, owner, child)
    assert factory.reads == []
