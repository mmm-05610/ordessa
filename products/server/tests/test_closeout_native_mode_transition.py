"""A logical draft target keeps identity after trusted native creation."""
from test_closeout_submission_composition import ControlledNativeFixture, controlled_product_composition, _test_fingerprint_fixture


def test_mode_transition_is_declared_by_native_binding_not_guessed_from_ui_kind(tmp_path):
    native = ControlledNativeFixture(tmp_path / 'effects.sqlite', mode='createWithConfig')
    runtime = controlled_product_composition(native_submit_port=native,
        fingerprint_port=_test_fingerprint_fixture()).default_runtime(tmp_path / 'data', include_profile=False)
    location = {'kind': 'draft', 'draftId': 'editor-draft', 'connectionId': 'connector'}
    try:
        runtime.start()
        first = runtime.wire.dispatch('agent.session.resolve', {'location': location})
        native.bind_backend_target(first['target'])
        conditions = runtime.wire.dispatch('agent.submission.capture.read', {'target': first['target'], 'mode': 'createWithConfig'})
        accepted = runtime.wire.dispatch('agent.submitInput', {'target': first['target'], 'capture': {
            'submissionId': 'first-attempt', 'draft': {'draftId': 'editor-draft', 'draftRevision': 1,
                'text': 'first', 'attachmentIds': []}, 'configOperationIds': [],
            'schema': 'agent-input/v1', 'mode': 'createWithConfig', 'expectedConditions': conditions}})
        assert accepted['outcome'] == 'accepted'
        native.set_mode('existing')
        subsequent = runtime.wire.dispatch('agent.session.resolve', {'location': location})
        assert subsequent['target'] == first['target']
        assert subsequent['generation'] == first['generation']
        assert subsequent['submission']['mode'] == 'existing'
        assert subsequent['submission']['nativeBound'] is True
        assert set(native.all_effect_counts().values()) == {1}
    finally:
        runtime.stop()
