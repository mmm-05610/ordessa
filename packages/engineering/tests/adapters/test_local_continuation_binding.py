"""Continuation-side adapters: historical query derivation and port injection.

Controlled peers only. The historical factory is exercised through its pure
request derivation (`_historical_query_request`), because the authorize call
itself needs a real LocalUnitOwner that this package's tests must not build.
"""
import hashlib

import pytest

from ordessa_engineering.adapters.native_records.local_bindings import (
    _historical_query_request, build_historical_dispatch_query_factory,
)
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.approvals.refs import ApprovalRef
from ordessa_engineering.domain.changes.dispatch import (
    DispatchBinding, package_ref_projection,
)
from ordessa_engineering.domain.common.models.identity import Scope
from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.packages.refs import ImplementationPackageRef
from ordessa_infrastructure.encoding import canonical_bytes

SCOPE = Scope('realm-a', 'project-a')
UNIT = {'environmentNamespace': 'env-a', 'unitId': 'unit-a',
        'ownerProviderRef': {'provider': 'owner-a'}, 'sourceRevision': 'rev-1'}
QUERY = 'sha256:' + 'q' * 64


def digest(text):
    return Digest('sha256', hashlib.sha256(text).hexdigest())


def binding(**overrides):
    package = ImplementationPackageRef(SCOPE.realm_id, SCOPE.project_id, 'package-a', digest(b'pkg'))
    values = dict(
        scope=SCOPE, run_id='w1:work-a', step_id='implement', attempt=1, fence=1,
        action_instances=(('edit_repository', 'inst-1'),), unit_ref_bytes=canonical_bytes(UNIT),
        execution_operation_ref='op-a',
        prompt_ref=BlobRef(digest(b'prompt'), 10, 'application/json', 'prompt'),
        prompt_input_digest=digest(b'prompt-input'), expected_query_digest=QUERY,
        required_results=('implementation_report',), package_ref=package,
        approval_ref=ApprovalRef(SCOPE.realm_id, SCOPE.project_id, 'approval-a', digest(b'grant')),
        intent_digest=digest(b'intent'), control_version=1, binding_version=2,
        work={'work_id': 'work-a', 'action_id': 'incremental.implement-package',
              'step_id': 'implement', 'dispatch_key': 'w1:work-a'},
        subject={'subject_kind': 'frozen_package',
                 'subject_ref': package_ref_projection(package)})
    values.update(overrides)
    return DispatchBinding(**values)


class _Records:
    def __init__(self, *, query=QUERY):
        self.query = query

    def acp_turn_query_digest(self, unit, operation_ref, expected_prompt):
        return self.query


def test_historical_request_is_derived_from_the_frozen_binding_only():
    value = binding()
    records = _Records()
    unit, request, query = _historical_query_request(
        value, records, environment_namespace='env-a', principal_scope='principal-scope-a')
    assert unit == UNIT
    assert query == QUERY
    assert request.environment_namespace == 'env-a'
    assert request.principal_scope == 'principal-scope-a'
    again = _historical_query_request(value, records, environment_namespace='env-a',
                                      principal_scope='principal-scope-a')[1]
    assert again == request  # deterministic: no live Unit, no clock, no uuid

    other = binding(execution_operation_ref='op-b')
    assert _historical_query_request(other, records, environment_namespace='env-a',
                                     principal_scope='principal-scope-a')[1] != request


def _v1_binding():
    package = ImplementationPackageRef(SCOPE.realm_id, SCOPE.project_id, 'package-a', digest(b'pkg'))
    return DispatchBinding(
        scope=SCOPE, run_id='run-a', step_id='implement', attempt=1, fence=1,
        action_instances=(('edit_repository', 'inst-1'),), unit_ref_bytes=canonical_bytes(UNIT),
        execution_operation_ref='op-a',
        prompt_ref=BlobRef(digest(b'prompt'), 10, 'application/json', 'prompt'),
        prompt_input_digest=digest(b'prompt-input'), expected_query_digest=QUERY,
        required_results=('implementation_report',), package_ref=package,
        approval_ref=ApprovalRef(SCOPE.realm_id, SCOPE.project_id, 'approval-a', digest(b'grant')),
        intent_digest=digest(b'intent'), control_version=1)


def test_a_v1_binding_is_never_eligible():
    with pytest.raises(ApplicationError) as refused:
        _historical_query_request(_v1_binding(), _Records(),
                                  environment_namespace='env-a', principal_scope='scope-a')
    assert refused.value.code == 'CONTINUATION_QUERY_BINDING_INVALID'


def test_query_digest_mismatch_is_refused():
    value = binding()
    with pytest.raises(ApplicationError) as refused:
        _historical_query_request(value, _Records(query='sha256:' + 'z' * 64),
                                  environment_namespace='env-a', principal_scope='scope-a')
    assert refused.value.code == 'CONTINUATION_QUERY_BINDING_INVALID'


def test_factory_requires_the_original_owner_and_access():
    with pytest.raises(ApplicationError) as refused:
        build_historical_dispatch_query_factory(object(), object())
    assert refused.value.code == 'DISPATCH_SOURCE_SNAPSHOT_AUTHORITY_UNAVAILABLE'
