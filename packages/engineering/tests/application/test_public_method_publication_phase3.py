"""Public original snapshot/ref/adoption chain; management is controlled."""
import hashlib
import json

import pytest

from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.method_control import SQLiteMethodControl
from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.application.api.method_publication import publish_method
from ordessa_engineering.application.assembly import build_method_management
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.methods import compile_method, load_method
from ordessa_engineering.methods.definitions.models import CompilationCapabilities, MethodSource

from test_method_control_admission import TestManagement, context
from test_method_profile_policy_phase2 import frozen_policy
from test_proposal_usecases import SyntheticAccess


class ControlledHostCatalog:
    """Empty-operation test method only, not the product's 2.6 catalogue."""
    def read_current(self):
        return CompilationCapabilities((), trust_class='host')


def _compile(source):
    loaded = load_method(MethodSource(source), reader=FileResourceReader())
    assert loaded.ok, loaded.error
    compiled = compile_method(loaded.value, ControlledHostCatalog().read_current(),
                              'test.public-method-publication/1')
    assert compiled.ok, compiled.error
    return compiled.value


def test_public_publication_returns_stored_ref_and_requires_original_adoption(
        frozen_policy, tmp_path):
    source, _, _, _ = frozen_policy
    library = EngineeringLibrary.create((tmp_path/'public-method.sqlite').resolve(),
        library_id='public-method-publication', schema_version=10)
    try:
        snapshots = SQLiteSnapshotStore(library)
        factory = SQLiteUoWFactory(library)
        controls = SQLiteMethodControl(factory, snapshots)
        compiled = _compile(source)
        published = publish_method(compiled, snapshots,
                                   capability_catalog=ControlledHostCatalog())
        assert published.ok, published.error
        ref = published.value
        assert snapshots.get_digest(ref.method_id, ref.release_version) == ref.snapshot_digest.hex
        assert controls.read_snapshot(ref).ref.snapshot_digest == ref.snapshot_digest.hex
        with pytest.raises(ApplicationError, match='METHOD_SELECTION_UNAVAILABLE'):
            with controls.guard_selected(context('unselected')):
                pytest.fail('snapshot publication cannot select a project method')
        missing = build_method_management(factory, access=SyntheticAccess(),
            snapshots=snapshots, management=None)
        with pytest.raises(ApplicationError, match='METHOD_MANAGEMENT_UNAVAILABLE'):
            missing.adopt(ref, context('denied-adopt'), expected_version=0)
        owner = build_method_management(factory, access=SyntheticAccess(),
            snapshots=snapshots, management=TestManagement())
        result = owner.adopt(ref, context('public-adopt'), expected_version=0)
        assert result.status == 'completed'
        assert result.result['version'] == 1
        assert owner.adopt(ref, context('public-adopt'), expected_version=0) == result
        with controls.guard_selected(context('selected')) as exact:
            assert exact.ref.snapshot_digest == ref.snapshot_digest.hex

        # Same identity cannot be replaced by altered captured source bytes.
        workflow = json.loads((source/'workflow.yaml').read_text())
        workflow['steps'][0]['outcome'] = 'different'
        workflow['stop_outcomes'] = ['different']
        raw = json.dumps(workflow).encode()
        (source/'workflow.yaml').write_bytes(raw)
        manifest = json.loads((source/'method.yaml').read_text())
        manifest['resources'][0]['sha256'] = hashlib.sha256(raw).hexdigest()
        (source/'method.yaml').write_text(json.dumps(manifest))
        conflict = publish_method(_compile(source), snapshots,
                                  capability_catalog=ControlledHostCatalog())
        assert not conflict.ok and conflict.error.code == 'RELEASE_IDENTITY_CONFLICT'
        assert controls.read_snapshot(ref).ref.snapshot_digest == ref.snapshot_digest.hex
    finally:
        library.close()


def test_public_publication_refuses_missing_host_catalog(frozen_policy):
    source, _, controls, _ = frozen_policy
    result = publish_method(_compile(source), controls.snapshots,
                            capability_catalog=None)
    assert not result.ok and result.error.code == 'CAPABILITY_AUTHORITY_UNAVAILABLE'
