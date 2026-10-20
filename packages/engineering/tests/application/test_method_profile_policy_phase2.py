"""Original SQLite frozen-method policy; synthetic management is explicit.

No model, Unit process, production human authority or product assembly.
"""
from dataclasses import replace
import hashlib
import json

import pytest

from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.method_control import SQLiteMethodControl
from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.adapters.profile_method import read_method_profile_selection_policy
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.usecases.publish_snapshot import freeze_method
from ordessa_engineering.application.usecases.support.methods import MethodUseCases
from ordessa_engineering.domain.artifacts.method_binding import MethodRef
from ordessa_engineering.domain.common.models.identity import Scope
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.methods import compile_method, load_method
from ordessa_engineering.methods.definitions.models import CompilationCapabilities, MethodSource
from test_method_control_admission import TestManagement, context
from test_proposal_usecases import SyntheticAccess


POLICY = dict(schema_version=1, question_id='test.task-profile',
    question_text='Choose an offered fixed Profile for this task or decline.',
    candidate_limit=2, decline_option_id='decline', decline_option_text='None is suitable.')


@pytest.fixture
def frozen_policy(tmp_path):
    source = tmp_path / 'method'
    source.mkdir()
    raw = json.dumps(dict(schema_version=1, entry='done',
        steps=[dict(id='done', kind='stop', outcome='finished')],
        stop_outcomes=['finished'], wait_kinds=[], context_slots=[])).encode()
    (source / 'workflow.yaml').write_bytes(raw)
    manifest = dict(schema_version=1, method_id='test.profile-policy',
        release_version='1.0.0', compiler_contract='ordessa.methods/v1',
        entry={'resource': 'workflow.main'}, documents=[], requires=[],
        resources=[dict(id='workflow.main', kind='workflow', path='workflow.yaml',
            media_type='application/yaml', sha256=hashlib.sha256(raw).hexdigest())],
        metadata={'agent_profile_selection': POLICY})
    (source / 'method.yaml').write_text(json.dumps(manifest))
    capabilities = CompilationCapabilities((), trust_class='host')
    loaded = load_method(MethodSource(source), reader=FileResourceReader())
    assert loaded.ok, loaded.error
    compiled = compile_method(loaded.value, capabilities, 'test.profile-policy/1')
    assert compiled.ok, compiled.error
    class SyntheticCatalog:
        def read_current(self):
            return capabilities
    library = EngineeringLibrary.create((tmp_path / 'policy.sqlite').resolve(),
        library_id='profile-policy-tests', schema_version=10)
    try:
        snapshots = SQLiteSnapshotStore(library)
        frozen = freeze_method(compiled.value, snapshots, snapshots,
                              capability_catalog=SyntheticCatalog())
        assert frozen.ok, frozen.error
        ref = frozen.value.ref
        method_ref = MethodRef(ref.method_id, ref.release_version, ref.schema_version,
                               Digest('sha256', ref.snapshot_digest))
        factory = SQLiteUoWFactory(library)
        control = SQLiteMethodControl(factory, snapshots)
        management = MethodUseCases(factory, SyntheticAccess(), snapshots, TestManagement())
        management.adopt(method_ref, context('adopt-profile-method'), expected_version=0)
        yield source, method_ref, control, management
    finally:
        library.close()


def test_reader_uses_frozen_manifest_not_mutated_source_or_latest(frozen_policy):
    source, method_ref, control, _ = frozen_policy
    (source / 'method.yaml').write_text('{"metadata":{"agent_profile_selection":null}}')
    policy, ref = read_method_profile_selection_policy(control, context('read-policy'), method_ref)
    assert policy == POLICY
    assert (ref.policy_id, ref.version, ref.content_digest) == (
        method_ref.method_id, method_ref.release_version,
        'sha256:' + method_ref.snapshot_digest.hex)


def test_reader_retains_original_disable_and_foreign_scope_refusals(frozen_policy):
    _, method_ref, control, management = frozen_policy
    with pytest.raises(ApplicationError):
        read_method_profile_selection_policy(control,
            replace(context('foreign-policy'), scope=Scope('other', 'project')), method_ref)
    management.control(method_ref, context('disable-profile-method'), expected_version=0,
                       enabled=False, reason='Explicit fixture stop')
    with pytest.raises(ApplicationError, match='METHOD_DISABLED'):
        read_method_profile_selection_policy(control, context('disabled-policy'), method_ref)
