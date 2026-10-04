"""Independent wire observers share the production Agent authority, not a UI singleton."""
import pytest
from server_plugin_api import WireError
from ordessa_server_product.composition import create_composition

@pytest.mark.parametrize('include_profile', [True, False])
def test_two_independent_wire_observers_follow_one_owner_and_isolate_other_target(tmp_path, include_profile):
    runtime = create_composition().default_runtime(tmp_path/'data', include_profile=include_profile)
    try:
        runtime.start()
        location = {'kind':'draft','connectionId':'controlled-connection','draftId':'shared-draft'}
        binding = runtime.wire.dispatch('agent.session.resolve', {'location':location})
        target, generation = binding['target'], binding['generation']
        runtime.wire.dispatch('agent.config.read', {'target':target})
        params = {'target':target, 'location':location, 'generation':generation, 'credits':1, 'cursor':None}
        observers = [runtime.wire.dispatch('agent.config.observe', params) for _ in range(2)]
        assert observers[0]['subscription_id'] != observers[1]['subscription_id']
        assert [batch['frames'][0]['value']['revision'] for batch in observers] == [0, 0]
        other_location = {**location, 'draftId':'other-draft'}
        other = runtime.wire.dispatch('agent.session.resolve', {'location':other_location})
        runtime.wire.dispatch('agent.config.read', {'target':other['target']})
        for patch, expected in [({'model':'M1','prompt':'A'}, {'model':'M1','prompt':'A'}),
                                ({'model':'M2'}, {'model':'M2','prompt':'A'}),
                                ({'prompt':'B'}, {'model':'M2','prompt':'B'}),
                                ({'model':'M1','prompt':'A'}, {'model':'M1','prompt':'A'})]:
            runtime.wire.dispatch('agent.config.submitOperation', {'target':target,'patch':patch})
            observers = [runtime.wire.dispatch('agent.config.observe', {**params,
                'subscriptionId':batch['subscription_id'], 'cursor':batch['cursor']}) for batch in observers]
            values = [batch['frames'][0]['value'] for batch in observers]
            assert values[0] == values[1]
            assert values[0]['resolved'] == expected
            assert values[0]['observedEvidence'] == 'unset' # intent is never native confirmation
            assert runtime.wire.dispatch('agent.config.read', {'target':other['target']})['revision'] == 0
        for batch in observers:
            released = runtime.wire.dispatch('agent.config.release', {**{k:v for k,v in params.items() if k not in ('credits','cursor')},
                'subscriptionId':batch['subscription_id']})
            assert released == {'released':True}
            with pytest.raises(WireError):
                runtime.wire.dispatch('agent.config.observe', {**params,'subscriptionId':batch['subscription_id'],'cursor':batch['cursor']})
    finally:
        runtime.stop()

def test_observation_generation_mismatch_refuses_before_creating_a_subscription(tmp_path):
    runtime = create_composition().default_runtime(tmp_path/'data')
    try:
        runtime.start()
        location = {'kind':'draft','draftId':'D'}
        binding = runtime.wire.dispatch('agent.session.resolve', {'location':location})
        with pytest.raises(WireError) as refused:
            runtime.wire.dispatch('agent.config.observe', {'target':binding['target'],
                'location':location, 'generation':binding['generation']+1, 'credits':1})
        assert refused.value.family == 'CONFLICT_VERSION'
    finally:
        runtime.stop()

def test_release_uses_captured_subscription_when_generation_is_stale(tmp_path):
    runtime = create_composition().default_runtime(tmp_path/'data')
    try:
        runtime.start()
        location = {'kind':'draft','draftId':'D'}
        binding = runtime.wire.dispatch('agent.session.resolve', {'location':location})
        params = {'target':binding['target'], 'location':location,
                  'generation':binding['generation'], 'credits':1}
        batch = runtime.wire.dispatch('agent.config.observe', params)
        release = {k:v for k,v in params.items() if k != 'credits'}
        release['generation'] += 1
        release['subscriptionId'] = batch['subscription_id']
        assert runtime.wire.dispatch('agent.config.release', release) == {'released':True}
        with pytest.raises(WireError):
            runtime.wire.dispatch('agent.config.observe', {**params,
                'subscriptionId':batch['subscription_id']})
    finally:
        runtime.stop()
