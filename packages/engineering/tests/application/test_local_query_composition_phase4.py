"""The canonical native query can be captured before method producer assembly."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'execution/units/tests'))
pytest_plugins = ('test_local_owner',)

from ordessa_engineering.adapters.native_records import (
    build_local_dispatch_bindings,
    build_local_dispatch_query_factory,
    build_local_method_dispatch_inputs,
)
from ordessa_engineering.adapters.native_records.recorded_dispatch import NativeDispatchSources
from ordessa_engineering.adapters.method_work import SQLitePersistedMethodWorkSource
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.adapters.registry import load_registry
from ordessa_engineering.application.assembly.method_runs import build_method_run_bindings
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_system_access_bindings.engineering import EngineeringCommandAccess
from test_local_dispatch_bindings_phase3 import (
    assembled_live_owner, _grant_dispatch_to_the_same_local_authority,
)
from test_method_work import env


def test_captured_query_is_reused_by_bindings_for_same_original_owner(
        assembled_live_owner):
    world = assembled_live_owner
    owner = world.owner
    access = EngineeringCommandAccess(world.access)
    query = build_local_dispatch_query_factory(owner, access)

    selection, sources, reused = build_local_dispatch_bindings(
        owner, access, prompt_parameters=lambda *_args: {'prompt': []},
        query_factory=query)

    assert reused is query
    assert callable(query)
    assert selection is not None
    assert sources is not None


def test_captured_query_rejects_foreign_owner_access_and_arbitrary_callable(
        assembled_live_owner, tmp_path):
    world = assembled_live_owner
    owner = world.owner
    access = EngineeringCommandAccess(world.access)
    query = build_local_dispatch_query_factory(owner, access)
    prompt_parameters = lambda *_args: {'prompt': []}

    with pytest.raises(ApplicationError,
                       match='DISPATCH_SOURCE_SNAPSHOT_AUTHORITY_UNAVAILABLE'):
        build_local_dispatch_bindings(
            owner, EngineeringCommandAccess(world.access),
            prompt_parameters=prompt_parameters, query_factory=query)

    from test_local_dispatch_bindings_phase3 import _make_live_owner, _close_live_owner
    foreign_root = tmp_path / 'foreign'
    foreign_root.mkdir()
    foreign = _make_live_owner(foreign_root, 'product-bind')
    try:
        with pytest.raises(ApplicationError,
                           match='DISPATCH_SOURCE_SNAPSHOT_AUTHORITY_UNAVAILABLE'):
            build_local_dispatch_bindings(
                foreign.owner, EngineeringCommandAccess(foreign.access),
                prompt_parameters=prompt_parameters, query_factory=query)
    finally:
        _close_live_owner(foreign)

    with pytest.raises(ApplicationError,
                       match='DISPATCH_SOURCE_SNAPSHOT_AUTHORITY_UNAVAILABLE'):
        build_local_dispatch_bindings(
            owner, access, prompt_parameters=prompt_parameters,
            query_factory=lambda _binding: object())


def test_q_first_composes_one_original_work_bindings_producer_and_dispatch_ports(
        env, assembled_live_owner):
    e, world = env, assembled_live_owner
    owner = world.owner
    access = EngineeringCommandAccess(world.access)
    blobs = SQLiteBlobStore(e['lib'])
    registry = load_registry()

    query = build_local_dispatch_query_factory(owner, access)
    source = SQLitePersistedMethodWorkSource(
        e['factory'], e['controls'], blobs=blobs,
        execution_records=owner.records, execution_query_factory=query)
    method_runs = build_method_run_bindings(
        e['factory'], method_control=e['controls'], work_condition_source=source,
        registry_loader=lambda: registry)
    producer = build_local_method_dispatch_inputs(method_runs, blobs, owner, access)
    selection, dispatch_sources, reused_query = build_local_dispatch_bindings(
        owner, access, prompt_parameters=producer.prompt_parameters,
        query_factory=query)

    assert source.factory is method_runs.factory is e['factory']
    assert source.methods is method_runs.methods is e['controls']
    assert source.blobs is blobs
    assert source.execution_records is owner.records
    assert source.execution_query_factory is query is reused_query
    assert method_runs.source is source
    assert producer.owner is owner and producer.access is access
    assert type(dispatch_sources) is NativeDispatchSources
    assert selection is not None


def test_q_first_query_keeps_original_namespace_principal_and_digest(
        assembled_live_owner, monkeypatch):
    from dataclasses import replace
    import runpy
    from pathlib import Path

    from ordessa_engineering.domain.approvals.refs import ApprovalRef
    from ordessa_engineering.domain.approvals.scope import EnvironmentRef
    from ordessa_engineering.domain.changes.dispatch import DispatchBinding
    from ordessa_engineering.domain.common.models.refs import BlobRef
    from ordessa_engineering.domain.common.models.values import Digest
    from ordessa_infrastructure.encoding.immutable_json import safe_json
    from ordessa_interfaces.system_access.contracts.refs import Scope
    from ordessa_execution_agents.profiles import encode_revision_ref
    from ordessa_engineering.application.contracts.execution_dispatch import EXECUTION_DISPATCH

    world = assembled_live_owner
    owner = world.owner
    unit = owner.manager.create(owner.spec, owner.authorization())
    access = EngineeringCommandAccess(world.access)
    query = build_local_dispatch_query_factory(owner, access)
    caller = world.access.authenticate('Bearer ' + __import__(
        'test_local_owner').BEARER)
    request_id = 'Work:Child:Draft:Attempt:' + 'A' * 96
    captured = []
    sends = []
    original_authorize = owner.authorize_acp_turn_query

    def observe(authorization, request, unit_ref, operation_ref, *,
                expected_prompt_input_digest):
        captured.append((request, dict(unit_ref), operation_ref, expected_prompt_input_digest))
        return original_authorize(authorization, request, unit_ref, operation_ref,
            expected_prompt_input_digest=expected_prompt_input_digest)

    monkeypatch.setattr(owner, 'authorize_acp_turn_query', observe)
    monkeypatch.setattr(unit, 'prompt', lambda *args, **kwargs: sends.append((args, kwargs)),
                        raising=False)
    with access.admit(caller, Scope('env', 'project'), EXECUTION_DISPATCH,
                      request_id=request_id, trace_id=request_id) as context:
        helper_path = Path(__file__).resolve().parents[1] / 'domain' / \
            'test_implementation_package_binding.py'
        helpers = runpy.run_path(str(helper_path))
        record_globals = helpers['_records'].__globals__
        old_scope = record_globals['SCOPE']
        record_globals['SCOPE'] = context.scope
        try:
            package = helpers['_records']()[2]
        finally:
            record_globals['SCOPE'] = old_scope
        package = replace(package, scope=context.scope,
            payload=replace(package.payload, execution_profile_ref=EnvironmentRef(
                owner.permission.profile_revision.environment_namespace,
                owner.permission.profile_revision.profile_id,
                Digest('sha256', owner.permission.profile_revision.digest.removeprefix('sha256:')))))
        fixed = {'prompt': [{'type': 'text', 'text': 'q-first prompt'}],
                 'sessionId': unit.snapshot()['sessionId']}
        prompt_digest = Digest('sha256', owner.records.acp_prompt_input_digest(
            unit.identity, fixed).removeprefix('sha256:'))
        operation_ref = 'phase4-q-first-operation'
        expected_query = owner.records.acp_turn_query_digest(
            unit.identity, operation_ref, 'sha256:' + prompt_digest.hex)
        binding = DispatchBinding(context.scope, 'phase4-run', 'dispatch', 1, 1,
            package.ref,
            ApprovalRef('env', 'project', 'phase4-approval', Digest('sha256', 'a' * 64)),
            Digest('sha256', 'b' * 64), 0, (('edit_repository', 'controlled-action'),),
            safe_json(unit.identity).encode('utf-8'), operation_ref,
            BlobRef(Digest('sha256', 'c' * 64), 1, 'application/json', 'controlled-prompt'),
            prompt_digest, expected_query, ('submission',))
        invocation = query(binding)
        assert invocation.facts['inputDigest'] == expected_query
        assert owner.records.resolve_unit_reference(unit.identity, invocation,
            input_digest=invocation.facts['inputDigest']).public_ref == dict(unit.identity)
        assert query(binding).facts['inputDigest'] == expected_query
    assert len(captured) == 2
    import base64
    import hashlib
    from ordessa_infrastructure.encoding import canonical_bytes, decode_json

    derived_request_id = 'query-' + base64.b32encode(hashlib.sha256(canonical_bytes({
        'request_id': request_id,
        'operation_ref': operation_ref,
        'unit_ref': decode_json(safe_json(unit.identity)),
        'prompt_digest': 'sha256:' + prompt_digest.hex,
    })).digest()).decode('ascii').rstrip('=').lower()
    assert len(derived_request_id) == 58
    assert all((request.environment_namespace, request.principal_scope,
                request.request_id) == (
                    owner.admission.environment_namespace,
                    owner.permission.principal_scope, derived_request_id)
               for request, _unit_ref, _operation, _digest in captured)
    assert all(unit_ref == unit.identity and operation == operation_ref
               and digest == 'sha256:' + prompt_digest.hex
               for _request, unit_ref, operation, digest in captured)
    assert sends == []
