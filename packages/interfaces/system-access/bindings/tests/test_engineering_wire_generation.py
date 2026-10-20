"""Trusted generation binding is independent of the retired compiled-run owner.

Only the transport and source selection are labelled doubles. The Service,
wire binding, SQLite factory, blob authority and generation owner are real.
"""
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_interfaces.system_access.access_control.authentication import InstanceAccessAuthority
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_system_access_bindings.engineering_wire import (
    EngineeringApplicationPorts, EngineeringWireBinding, _record)
from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader
from ordessa_engineering.application.contracts.commands import CommandContext
from ordessa_engineering.application.contracts.work_context import (
    WORK_CONTEXT_KIND, WORK_STABLE_ID_PREFIX, WorkBinding, work_binding_projection,
)
from ordessa_engineering.application.usecases.queries.works import WorkQueries, declared_actions
from ordessa_engineering.domain.artifacts.method_binding import MethodRef
from ordessa_engineering.domain.common.models.identity import ActorRef, Scope as WorkScope
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.methods import load_method, read_method_definition
from ordessa_engineering.methods.definitions.models import MethodSource


@pytest.fixture
def original(tmp_path):
    library = EngineeringLibrary.create((tmp_path / 'generation.sqlite').resolve(),
        library_id='wire-generation-test', schema_version=17)
    try:
        yield SQLiteUoWFactory(library), InstanceAccessAuthority(
            lambda: 'controlled-token', grants=()), Scope('realm', 'project')
    finally:
        library.close()


def test_generation_retains_one_owner_without_method_run_dispatch(original):
    factory, authority, scope = original
    blobs = SQLiteBlobStore(factory.library)
    sources = SimpleNamespace(factory=factory, read=lambda *_args: b'controlled-source')
    admission = SimpleNamespace(factory=factory, source_materials=sources,
        method_guard=SimpleNamespace(factory=factory, read_declaration=lambda *_args: None),
        guard_plan=lambda *_args: None, guard_trust=lambda *_args: None)
    transport = SimpleNamespace(freeze_input=lambda *_args: None,
        send=lambda *_args: None, capture=lambda *_args: None,
        guard_effect_handoff=lambda *_args: None)

    def bind(service):
        service.attach_declared_generation_handles(blobs=blobs, execution=transport,
            unit_ref_resolver=lambda *_args: None)
        return service.declared_generation_dispatch

    binding = EngineeringWireBinding(factory, authority, scope=scope,
        application_ports_factory=lambda *_args: EngineeringApplicationPorts(
            review_admission=admission, blobs=blobs, declared_generation_binder=bind))
    assert binding.declared_generation_dispatch is binding.service.declared_generation_dispatch
    assert binding.declared_generation_dispatch.factory is factory
    assert binding.declared_generation_dispatch.access is binding.access
    assert binding.service.declared_generation_ready is True
    assert binding.execution_dispatch is None
    assert binding.service._work.bindings is None
    assert binding.capabilities()['supports']['dispatch'] is False
    assert 'engineering.executions.dispatch' not in {row.method_id for row in binding.methods()}


def test_generation_cannot_return_an_unretained_owner(original):
    factory, authority, scope = original
    with pytest.raises(ApplicationError, match='DISPATCH_AUTHORITY_MISMATCH'):
        EngineeringWireBinding(factory, authority, scope=scope,
            application_ports_factory=lambda *_args: EngineeringApplicationPorts(
                declared_generation_binder=lambda _service: object()))


def test_generation_and_canonical_dispatch_are_explicit_alternatives(original):
    factory, authority, scope = original
    called = []
    def bind(_service):
        called.append(True)
    with pytest.raises(ApplicationError, match='DISPATCH_AUTHORITY_MISMATCH'):
        EngineeringWireBinding(factory, authority, scope=scope,
            application_ports_factory=lambda *_args: EngineeringApplicationPorts(
                declared_generation_binder=bind, execution_dispatch_binder=bind))
    assert called == []


def test_work_unknown_view_crosses_strict_wire_with_declaration_sequences():
    kind, record = _record({
        'work_id': 'generation-native-work',
        'declared_actions': ({'steps': ({'step_id': 'draft', 'inputs': ()},)},),
        'actions': (),
        'generation_dispatch': {'phase': 'unknown', 'retry_allowed': False,
                                'unknown_requires_reconciliation': True},
    }, 'engineering.work.get')
    restored = decode_json(canonical_bytes(record))
    assert kind == 'MethodWork'
    assert restored['declared_actions'][0]['steps'][0]['inputs'] == []
    assert restored['actions'] == []
    assert restored['generation_dispatch'] == {
        'phase': 'unknown', 'retry_allowed': False,
        'unknown_requires_reconciliation': True}


def test_real_272_work_get_projects_declaration_to_canonical_wire_bytes():
    repository = Path(__file__).resolve().parents[5]
    method_source = MethodSource(
        repository / 'methods/incremental-engineering/candidates/2.7.2', 'method.json')
    loaded = load_method(method_source, FileResourceReader())
    assert loaded.ok, loaded.error
    result = read_method_definition(loaded.value)
    assert result.ok, result.error
    declaration = result.value
    method_ref = MethodRef(
        declaration.method_ref.method_id,
        declaration.method_ref.release_version,
        declaration.method_ref.schema_version,
        Digest('sha256', declaration.method_ref.snapshot_digest),
    )
    scope = WorkScope('wire-method-realm', 'wire-method-project')
    binding = WorkBinding('wire-method-work', scope, method_ref, 1)
    head = SimpleNamespace(revision=1, digest='sha256:' + 'c' * 64)

    class Workflow:
        def head_ref(self, kind, stable_id):
            assert kind == WORK_CONTEXT_KIND
            assert stable_id == WORK_STABLE_ID_PREFIX + binding.work_id
            return head

        def read(self, _head):
            return work_binding_projection(binding)

    class WorkDispatch:
        def get(self, *_args):
            raise ApplicationError('NOT_FOUND')

    class Commands:
        def find_operation(self, *_args, **_kwargs):
            return None

    uow = SimpleNamespace(workflow=Workflow(), work_dispatch=WorkDispatch(), commands=Commands())

    class Factory:
        @contextmanager
        def begin(self, actual_scope, mode):
            assert actual_scope == scope and mode == 'read'
            yield uow

    class Access:
        def require(self, _context, operation):
            assert operation == 'engineering.work.get'

    class Methods:
        def read_declaration(self, _context, actual_method_ref):
            assert actual_method_ref == method_ref
            return declaration, 1

    context = CommandContext(scope, 'wire-method-principal',
        ActorRef('wire-method-actor', 'service', 'wire-method-issuer'),
        'wire-method-read', '2026-10-15T10:00:00.000000Z', 'wire-method-read')
    view = WorkQueries(Factory(), Access(), methods=Methods()).read(
        {'work_id': binding.work_id}, context)
    assert view['declared_actions'] == declared_actions(declaration)

    kind, record = _record(view, 'engineering.work.get')
    restored = decode_json(canonical_bytes(record))
    assert kind == 'MethodWork'
    actions = {item['action_id']: item for item in restored['declared_actions']}
    prepare = actions['incremental.prepare-packages']
    assert prepare['admission'] == [
        {'kind': 'same_scope', 'inputs': ['baseline', 'candidate', 'scope']},
        {'kind': 'exact_inputs', 'inputs': ['baseline', 'candidate', 'scope', 'review']},
        {'kind': 'method_pin', 'inputs': ['method', 'review']},
        {'kind': 'review_complete', 'inputs': ['review']},
        {'kind': 'review_passed', 'inputs': ['review']},
        {'kind': 'baseline_available', 'inputs': ['baseline']},
    ]
    assert prepare['outputs'] == [{
        'name': 'package', 'value_kind': 'package_ref',
        'step_id': 'draft', 'output': 'package_ref'}]
    implement = actions['incremental.implement-package']
    disposition = next(step for step in implement['steps'] if step['step_id'] == 'disposition')
    assert disposition['admission'] == [
        {'kind': 'review_complete', 'inputs': ['review']},
        {'kind': 'method_pin', 'inputs': ['method', 'review']},
        {'kind': 'reviewer_independent',
         'inputs': ['report', 'review', 'package', 'reviewer_profile', 'method']},
    ]
    assert all(type(step['outputs']) is list
               and all(type(output) is str for output in step['outputs'])
               for action in restored['declared_actions'] for step in action['steps'])
