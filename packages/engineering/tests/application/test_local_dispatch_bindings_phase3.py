"""Local dispatch bindings use the same live Unit owner and its read issuer."""
from dataclasses import replace
import os
from pathlib import Path
import runpy
import sys
import time
from threading import RLock
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'execution/units/tests'))
pytest_plugins = ('test_local_owner',)

from ordessa_engineering.adapters.native_records.local_bindings import (
    build_local_dispatch_bindings,
)
from ordessa_engineering.adapters.native_records.recorded_dispatch import NativeDispatchSources
from ordessa_engineering.adapters.native_records.selection import OriginalDispatchSelection
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.execution_dispatch import EXECUTION_DISPATCH
from ordessa_engineering.application.contracts.implementation_routes import IMPLEMENTATION_COMMANDS
from ordessa_engineering.domain.approvals.refs import ApprovalRef
from ordessa_engineering.domain.approvals.scope import EnvironmentRef
from ordessa_engineering.domain.changes.dispatch import DispatchBinding
from ordessa_engineering.domain.common.models.identity import Scope as EngineeringScope
from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.packages.models import ImplementationPackage
from ordessa_interfaces.system_access.contracts.refs import Scope as AccessScope
from ordessa_system_access_bindings.engineering import EngineeringCommandAccess
from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_infrastructure.encoding.immutable_json import safe_json
from ordessa_execution_agents.profiles import encode_revision_ref


@pytest.fixture(autouse=True)
def _grant_dispatch_to_the_same_local_authority(monkeypatch):
    import test_local_owner

    original = test_local_owner._access_authority

    def make_authority(*, capabilities=test_local_owner.CAPABILITIES,
                       token=test_local_owner.BEARER):
        expanded = tuple(dict.fromkeys((*capabilities, EXECUTION_DISPATCH,
                                        IMPLEMENTATION_COMMANDS[0])))
        return original(capabilities=expanded, token=token)

    monkeypatch.setattr(test_local_owner, '_access_authority', make_authority)


def _make_live_owner(tmp_path, assembly_style):
    """Build one isolated owner through an existing public assembly route."""
    import test_local_owner as helpers
    from ordessa_environments import EnvironmentManager, SQLiteEnvironmentStore
    from ordessa_environments_local import LocalEnvironmentResourceProvider
    from ordessa_execution_agents.profiles import ProfileService
    from ordessa_units.admission.context import UnitAdmissionContext
    from ordessa_units.admission.fingerprint import ProtectedFingerprintHmac
    from ordessa_units.admission.material_registration import MaterialCatalog
    from ordessa_units.bindings.profile_admission import UnitProfileAdmission
    from ordessa_units.records import OperationJournal
    from ordessa_units.assembly.local_owner import build_local_unit_owner
    from ordessa_units.assembly import assemble_unit_owner

    access = helpers._access_authority()
    principal = access.authenticate('Bearer ' + helpers.BEARER)
    store = helpers.SqliteUnitStore(tmp_path / 'unit-store.sqlite')
    policy = helpers.ProfileSetupPolicy()
    lock = RLock()
    context_ref = {}
    catalog = helpers.HarnessCatalog(
        'env', policy=policy, principal_scope=helpers.PRINCIPAL_ID,
        admission_lock=lock,
        retirement_guard=lambda owner_id, generation: context_ref['context'].harness_provider_retirement_guard(
            owner_id, generation))
    materials = MaterialCatalog('env', admission_lock=lock)
    admission = UnitAdmissionContext(
        'env', store=store, policy=policy,
        fingerprint_port=ProtectedFingerprintHmac(
            {'fixture': b'local-unit-owner-profile-fixture'}, active_key_id='fixture'),
        harness_catalog=catalog, material_catalog=materials,
        principal_scope=helpers.PRINCIPAL_ID, admission_lock=lock)
    context_ref['context'] = admission

    definition = helpers.HarnessDefinitionDescriptor(
        'local-acp',
        {'environmentNamespace': 'env', 'definitionId': 'local-acp', 'revision': '1'},
        'sha256:' + 'b' * 64, 'acp/v1', 'local-process-fixture/1')
    declaration = helpers.HarnessDefinitionDeclaration(definition, lambda _installation: None)
    catalog.stage('local-acp-owner', 1, 'local-installation', 'c' * 64,
                  (declaration,)).commit()
    profiles = ProfileService(UnitProfileAdmission(admission))
    profile = profiles.create(
        profile_id='profile', name='Local Unit fixture',
        content={'schemaVersion': '1', 'harnessDefinitionRef': dict(definition.definition_ref),
                 'declarations': [], 'metadata': {'fixture': 'local-process'}},
        request=profiles.request_key('create-local-profile'))

    environment_root = tmp_path / 'environment-root'
    environment_root.mkdir()
    (environment_root / 'units').mkdir()
    environment_provider = LocalEnvironmentResourceProvider(default_root=str(environment_root))
    environment_manager = EnvironmentManager(
        store=SQLiteEnvironmentStore(tmp_path / 'environment-store.sqlite'),
        providers={'local': environment_provider})
    environment = environment_manager.create(
        'local', {'isolation': 'none', 'root': str(environment_root)})
    permission = helpers._run_permission(
        access, principal, environment_root / 'units', profile_ref=profile.current_revision,
        environment_identity=environment.identity, expires_at=time.time() + 120)
    preparation = helpers.Preparation()
    owner = build_local_unit_owner(
        admission_context=admission, permission=permission,
        environment_instance=environment, preparation=preparation,
        materializer=helpers._materializer, environment_sharing=True, timeout=5,
        acp_turn_opt_in=True, clock=time.time)

    journal_path = tmp_path / 'operation-journal.sqlite'
    descriptor_fd = os.open(journal_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor_fd)
    journal = OperationJournal(journal_path, acp_turn_opt_in=True)
    if assembly_style == 'local-assemble':
        manager = owner.assemble(journal=journal)
        assembled = owner.assembled_owner
    else:
        assembled = assemble_unit_owner(admission, owner.owner_inputs, journal=journal)
        admission.owner_ports = assembled.ports
        manager = owner.bind(assembled.ports)
        assert owner.assembled_owner is None
    assert manager is owner.manager and assembled.journal is journal
    world = SimpleNamespace(access=access, principal=principal, owner=owner,
        permission=permission, admission=admission, catalog=catalog,
        materials=materials, store=store, environment=environment,
        environment_manager=environment_manager, journal=journal, assembled=assembled,
        ports=assembled.ports, assembly_style=assembly_style,
        records=assembled.records, preparation=preparation)
    return world


def _close_live_owner(world):
    owner = world.owner
    try:
        if owner.manager is not None:
            owner.manager.close(owner.authorization())
    finally:
        try:
            world.assembled.revoke()
        finally:
            try:
                world.catalog.drain('local-acp-owner', 1)
                world.catalog.retire('local-acp-owner', 1)
            finally:
                try:
                    world.admission.close()
                finally:
                    world.catalog.close()
                    world.materials.close()
                    world.store.close()


@pytest.fixture(params=('local-assemble', 'product-bind'))
def assembled_live_owner(tmp_path, request):
    """Create one original LocalUnitOwner through its public assemble route."""
    world = _make_live_owner(tmp_path, request.param)
    try:
        yield world
    finally:
        _close_live_owner(world)


def test_local_builder_uses_owner_source_query_and_distinct_capture_read_key(
        assembled_live_owner, monkeypatch):
    world = assembled_live_owner
    owner = world.owner
    unit = owner.manager.create(owner.spec, owner.authorization())
    manager_create_calls = []
    monkeypatch.setattr(owner.manager, 'create',
                        lambda *args, **kwargs: manager_create_calls.append((args, kwargs)))
    interaction_calls = []
    monkeypatch.setattr(unit, 'interaction',
                        lambda *args, **kwargs: interaction_calls.append((args, kwargs)))

    access = EngineeringCommandAccess(world.access)
    caller = world.access.authenticate('Bearer ' + __import__(
        'test_local_owner').BEARER)
    request_ids = []
    original_authorize = owner.authorize_acp_turn_query

    def observed_authorize(authorization, request, unit_ref, operation_ref, *,
                           expected_prompt_input_digest):
        request_ids.append((request, operation_ref, expected_prompt_input_digest))
        return original_authorize(authorization, request, unit_ref, operation_ref,
            expected_prompt_input_digest=expected_prompt_input_digest)

    monkeypatch.setattr(owner, 'authorize_acp_turn_query', observed_authorize)
    prompt = [{'type': 'text', 'text': 'controlled native dispatch prompt'}]
    prompt_parameters = lambda _context, _package, _unit_ref: {'prompt': prompt}
    selection, sources, capture_query = build_local_dispatch_bindings(
        owner, access, prompt_parameters=prompt_parameters)
    assert type(selection) is OriginalDispatchSelection
    assert type(sources) is NativeDispatchSources
    assert callable(capture_query)

    with access.admit(caller, AccessScope('env', 'project'), EXECUTION_DISPATCH,
                      request_id='controlled-dispatch-request',
                      trace_id='controlled-dispatch-request') as context:
        helpers = runpy.run_path(str(Path(__file__).resolve().parents[1]
                                     / 'domain/test_implementation_package_binding.py'))
        helpers['_records'].__globals__['SCOPE'] = context.scope
        base_package = helpers['_records']()[2]
        package = replace(base_package, scope=context.scope,
            payload=replace(base_package.payload, execution_profile_ref=EnvironmentRef(
                owner.permission.profile_revision.environment_namespace,
                owner.permission.profile_revision.profile_id,
                Digest('sha256', owner.permission.profile_revision.digest.removeprefix('sha256:')))))
        assert type(package) is ImplementationPackage
        package_ref = package.ref

        # Each source consumer resolves the original owner independently. A
        # missing or unknown full Unit reference fails before an owner query.
        for bad_ref in (None, {
                'environmentNamespace': 'env', 'unitId': 'unknown-local-unit',
                'ownerProviderRef': dict(unit.identity['ownerProviderRef']),
                'sourceRevision': unit.identity['sourceRevision']}):
            with pytest.raises(ApplicationError,
                               match='DISPATCH_SELECTION_BINDING_INVALID'):
                with sources.guard_commit_snapshot(context, package, bad_ref):
                    pytest.fail('invalid Unit reference produced a source snapshot')

        with selection.guard_selection(context, package, unit.identity):
            pass

        # This is the same original source snapshot owner used around a dispatch
        # COMMIT. Its query is a Unit source read, not a query for a turn result.
        with sources.guard_commit_snapshot(context, package, unit.identity) as snapshot:
            assert snapshot['unitRef'] == dict(unit.identity)
            assert snapshot['profileRevision'] == encode_revision_ref(
                owner.permission.profile_revision)
            assert snapshot['currentThroughCommit'] is False
        with sources.guard_history_read(context, package, unit.identity):
            pass

        fixed = {'prompt': prompt, 'sessionId': unit.snapshot()['sessionId']}
        prompt_digest = Digest('sha256', owner.records.acp_prompt_input_digest(
            unit.identity, fixed).removeprefix('sha256:'))
        operation_ref = 'native-dispatch-capture-operation'
        expected_query = owner.records.acp_turn_query_digest(
            unit.identity, operation_ref, 'sha256:' + prompt_digest.hex)
        binding = DispatchBinding(context.scope, 'controlled-run', 'dispatch', 1, 1,
            package_ref,
            ApprovalRef('env', 'project', 'controlled-approval', Digest('sha256', 'a' * 64)),
            Digest('sha256', 'b' * 64), 0, (('edit_repository', 'controlled-action'),),
            safe_json(unit.identity).encode('utf-8'), operation_ref,
            BlobRef(Digest('sha256', 'c' * 64), 1, 'application/json', 'controlled-prompt'),
            prompt_digest, expected_query, ('submission',))
        invocation = capture_query(binding)
        assert invocation.facts['inputDigest'] == binding.expected_query_digest
        assert owner.records.resolve_unit_reference(unit.identity, invocation,
            input_digest=invocation.facts['inputDigest']).public_ref == dict(unit.identity)
        repeated = capture_query(binding)
        assert repeated.facts['inputDigest'] == invocation.facts['inputDigest']

    with access.admit(caller, AccessScope('env', 'project'), IMPLEMENTATION_COMMANDS[0],
                      request_id='controlled-reconcile-request',
                      trace_id='controlled-reconcile-request') as reconcile_context:
        historical = capture_query(binding)
        assert historical.facts['inputDigest'] == binding.expected_query_digest

    assert len(request_ids) == 6
    source_requests = [entry[0] for entry in request_ids[:3]]
    capture_requests = [entry[0] for entry in request_ids[3:5]]
    reconcile_request = request_ids[5][0]
    assert len({request.request_id for request in source_requests}) == 3
    assert all(request.request_id != context.request_id for request in source_requests)
    assert all(request.request_id == context.request_id for request in capture_requests)
    assert reconcile_request.request_id == reconcile_context.request_id
    assert all((request.environment_namespace, request.principal_scope) == (
        owner.admission.environment_namespace, owner.permission.principal_scope)
        for request in (*source_requests, *capture_requests, reconcile_request))
    assert all(entry[1] == context.request_id for entry in request_ids[:3])
    assert all(entry[1] == binding.execution_operation_ref for entry in request_ids[3:])
    assert all(entry[2] == 'sha256:' + binding.prompt_input_digest.hex
               for entry in request_ids[3:])
    assert manager_create_calls == []
    assert interaction_calls == []


def test_local_builder_refuses_different_access_authority(assembled_live_owner):
    world = assembled_live_owner
    owner = world.owner
    wrong_access = SimpleNamespace(authority=object(), current_context=lambda: None,
                                   require=lambda *_: None)
    with pytest.raises(ApplicationError,
                       match='DISPATCH_SOURCE_SNAPSHOT_AUTHORITY_UNAVAILABLE'):
        build_local_dispatch_bindings(owner, wrong_access,
                                      prompt_parameters=lambda *_: {'prompt': []})


def test_local_builder_refuses_replaced_original_owner_ports(assembled_live_owner):
    from ordessa_units.admission.owner_ports import AgentOwnerPorts

    world = assembled_live_owner
    owner = world.owner
    assert type(world.ports) is AgentOwnerPorts
    owner.admission.owner_ports = replace(world.ports)
    with pytest.raises(ApplicationError,
                       match='DISPATCH_SOURCE_SNAPSHOT_AUTHORITY_UNAVAILABLE'):
        build_local_dispatch_bindings(
            owner, EngineeringCommandAccess(world.access),
            prompt_parameters=lambda *_: {'prompt': []})


def test_local_builder_refuses_ports_from_a_different_original_owner(
        assembled_live_owner, tmp_path):
    from ordessa_units.admission.owner_selection import AgentOwnerUnavailable

    world = assembled_live_owner
    owner = world.owner
    foreign_root = tmp_path / 'foreign-owner'
    foreign_root.mkdir()
    foreign = _make_live_owner(foreign_root, 'product-bind')
    try:
        assert foreign.owner is not owner
        assert foreign.admission is not owner.admission
        assert foreign.ports is not world.ports
        owner.admission.owner_ports = foreign.ports
        with pytest.raises(AgentOwnerUnavailable):
            owner.bind(foreign.ports)
        with pytest.raises(ApplicationError,
                           match='DISPATCH_SOURCE_SNAPSHOT_AUTHORITY_UNAVAILABLE'):
            build_local_dispatch_bindings(
                owner, EngineeringCommandAccess(world.access),
                prompt_parameters=lambda *_: {'prompt': []})
    finally:
        _close_live_owner(foreign)
