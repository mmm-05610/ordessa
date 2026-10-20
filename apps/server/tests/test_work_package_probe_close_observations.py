"""Close diagnostics preserve the probe's exact-owner retry boundary."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ordessa_infrastructure.encoding.immutable_json import sealed_mapping


@pytest.fixture
def probe():
    path = Path(__file__).resolve().parents[3] / 'tooling/checks/server_product/probe-work-package-generation.py'
    spec = importlib.util.spec_from_file_location('work_package_close_observation_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _runtime(outcomes):
    authorization = object()
    calls = []

    def authorize():
        calls.append('authorize')
        return authorization

    def close(received):
        assert received is authorization
        calls.append('close')
        return outcomes.pop(0)

    unit = SimpleNamespace(close=close)
    runtime = SimpleNamespace(units=SimpleNamespace(list=lambda: (unit,)),
        unit_execution_owner=SimpleNamespace(authorization=authorize))
    return runtime, calls


def test_pending_close_preserves_safe_observations_and_same_authorization(probe):
    runtime, calls = _runtime([
        sealed_mapping({'state': 'pending', 'unresolved': True,
            'quiescence': {'reason': 'sdk_operations_active', 'active_native_operations': 1}}),
        sealed_mapping({'state': 'confirmed'}),
    ])
    observations = []
    assert probe.close_generated_units(runtime, (), timeout=1, observations=observations) == (['confirmed'], [2])
    assert calls == ['authorize', 'close', 'close']
    assert [item['state'] for item in observations] == ['pending', 'confirmed']
    assert observations[0]['quiescence'] == {'reason': 'sdk_operations_active', 'active_native_operations': 1}
    assert observations[0]['unresolved'] is True
    assert observations[1]['unresolved'] is False
    assert observations[0]['elapsed_seconds'] <= observations[1]['elapsed_seconds']
    assert observations[0]['observed_at_unix'] > 0
    json.dumps(observations)


@pytest.mark.parametrize('state', ['unknown', 'partial', 'refused', 'confirmed'])
def test_close_observation_never_retries_nonpending_outcome(probe, state):
    runtime, calls = _runtime([sealed_mapping({'state': state, 'unresolved': True})])
    observations = []
    assert probe.close_generated_units(runtime, (), timeout=1, observations=observations) == ([state], [1])
    assert calls == ['authorize', 'close']
    assert len(observations) == 1 and observations[0]['state'] == state
