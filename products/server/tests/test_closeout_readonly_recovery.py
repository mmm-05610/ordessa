"""Stored facts survive temporary loss of effect/comparison capabilities."""
import sys
from pathlib import Path
import pytest
from server_plugin_api import WireError
from ordessa_server_product.composition import create_composition

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts/packaging'))
from controlled_native_fixture import (
    ControlledNativeFixture, controlled_product_composition,
    test_protected_fingerprint as _fingerprint,
)

def test_original_results_remain_readable_without_native_or_fingerprint(tmp_path):
    root = tmp_path / 'data'
    native = ControlledNativeFixture(tmp_path/'effects.sqlite', mode='existing')
    first = controlled_product_composition(native_submit_port=native,
        fingerprint_port=_fingerprint()).default_runtime(root, include_profile=False)
    location = {'kind':'draft','connectionId':'fixture','draftId':'D'}
    capture = {'submissionId':'old-request', 'draft':{'draftId':'D',
        'draftRevision':1, 'text':'immutable text', 'attachmentIds':[]},
        'configOperationIds':[], 'schema':'agent-input/v1', 'mode':'existing'}
    try:
        first.start()
        target = first.wire.dispatch('agent.session.resolve', {'location':location})['target']
        native.bind_backend_target(target)
        accepted = first.wire.dispatch('agent.submitInput', {'target':target,
            'draftRevision':1, 'capture':capture})
        assert accepted['outcome'] == 'accepted'
    finally:
        first.stop()
    restarted = create_composition().default_runtime(root, include_profile=False)
    try:
        restarted.start()
        assert restarted.wire.dispatch('agent.session.resolve', {'location':location})['target'] == target
        result = restarted.wire.dispatch('agent.submission.query',
            {'target':target,'submissionId':'old-request'})
        assert result['request'] == accepted['request']
        assert result['configApply'] == accepted['configApply']
        assert result['inputAcceptance'] == accepted['inputAcceptance']
        assert result['runResult'] == accepted['runResult']
        assert result['outcome'] == 'unknown' # current native query capability absent
        assert result['resend'] is False
        with pytest.raises(WireError) as refused:
            restarted.wire.dispatch('agent.submitInput', {'target':target,
                'draftRevision':1,'capture':{**capture,'submissionId':'new-request'}})
        assert refused.value.family == 'CAPABILITY_UNSUPPORTED'
    finally:
        restarted.stop()
    assert len(native.dispatches) == 1
