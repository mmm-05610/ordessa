"""Explicit host budgets reach admission and execution without raising defaults."""
import asyncio
from types import SimpleNamespace

import pytest

from ordessa_decision import DecisionError, DecisionRunner, FilesystemEvidenceStore, RulesOutcome, default_host_limits
from ordessa_decision.capability import build_capability
from ordessa_decision.evidence import EvidenceScope
from ordessa_decision.settings import DecisionsSettings


class _Engine:
    engine_id = 'controlled-budget-check'

    def __init__(self, size=1):
        self.size = size
        self.calls = 0

    def validate(self, payload):
        assert payload == {}

    def evaluate(self, payload, facts):
        self.calls += 1
        return RulesOutcome(values={'text': 'x' * self.size})

    def close(self):
        pass


def _job(**limits):
    return {'spec_version': 'decision-job/1', 'job_id': 'configured-budget', 'version': 1,
            'input': {}, 'limits': {**default_host_limits(), 'max_model_calls': 0, **limits},
            'steps': [{'id': 'check', 'type': 'rules', 'engine': None,
                       'when': {'fact': 'input', 'op': 'eq', 'value': {}}, 'payload': {}}],
            'result': {'from': 'check', 'path': ['values', 'text']}}


def _capability(tmp_path, *, host_limits=None, engine=None):
    calls = []
    def factory(**arguments):
        calls.append(arguments)
        return DecisionRunner(**arguments)
    config = DecisionsSettings(factory, FilesystemEvidenceStore(tmp_path),
                               default_engine=engine or _Engine(), host_limits=host_limits)
    capability = build_capability(config, invocation_resolver=lambda context: context,
        evidence_scope_resolver=lambda *_: EvidenceScope('principal', 'controlled-budget-test'))
    return capability, config, calls


@pytest.mark.parametrize('override', [{'timeout_seconds': 240.0}, {'max_value_bytes': 131072}])
def test_default_budgets_still_refuse_before_claim_and_runner(tmp_path, override):
    engine = _Engine()
    capability, config, calls = _capability(tmp_path, engine=engine)
    context = SimpleNamespace(request_id='default-refusal')
    for operation in ('decisions.validate', 'decisions.run'):
        result = asyncio.run(capability.handlers[operation]({'job': _job(**override)}, context))
        assert result.status == 'refused'
        assert result.error.code == 'INVALID_INPUT'
    assert calls == [] and engine.calls == 0
    assert list(tmp_path.rglob('.run-[0-9a-f]*.json')) == []
    assert config.host_limits is None
    assert default_host_limits()['timeout_seconds'] == 30.0
    assert default_host_limits()['max_value_bytes'] == 65536


def test_explicit_240_seconds_reaches_preflight_and_real_durable_runner(tmp_path):
    configured = {**default_host_limits(), 'timeout_seconds': 240.0}
    capability, config, calls = _capability(tmp_path, host_limits=configured)
    # Caller mutation cannot silently alter trusted host configuration.
    configured['timeout_seconds'] = 600.0
    with pytest.raises(TypeError):
        config.host_limits['timeout_seconds'] = 600.0
    context = SimpleNamespace(request_id='explicit-budget')
    job = _job(timeout_seconds=240.0)
    admitted = asyncio.run(capability.handlers['decisions.validate']({'job': job}, context))
    completed = asyncio.run(capability.handlers['decisions.run']({'job': job}, context))
    assert admitted.status == completed.status == 'completed'
    assert completed.data['result'] == 'x'
    assert len(calls) == 1 and calls[0]['host_limits'] == config.host_limits
    assert calls[0]['host_limits'] is not config.host_limits
    assert config.host_limits['timeout_seconds'] == 240.0
    assert len(list(tmp_path.rglob('.run-[0-9a-f]*.json'))) == 1
    assert len(list(tmp_path.rglob('.run-result-*.json'))) == 1


def test_explicit_output_budget_is_enforced_by_real_runner(tmp_path):
    configured = {**default_host_limits(), 'max_value_bytes': 131072}
    capability, _, calls = _capability(tmp_path, host_limits=configured, engine=_Engine(70000))
    context = SimpleNamespace(request_id='explicit-output')
    completed = asyncio.run(capability.handlers['decisions.run'](
        {'job': _job(max_value_bytes=131072)}, context))
    assert completed.status == 'completed'
    assert len(completed.data['result']) == 70000
    assert calls[0]['host_limits']['max_value_bytes'] == 131072


@pytest.mark.parametrize('override', [{'timeout_seconds': 240.1}, {'max_value_bytes': 65537},
                                      {'max_model_calls': 9}, {'max_steps': 33}])
def test_explicit_host_budget_cannot_be_raised_by_request(tmp_path, override):
    configured = {**default_host_limits(), 'timeout_seconds': 240.0}
    engine = _Engine()
    capability, _, calls = _capability(tmp_path, host_limits=configured, engine=engine)
    context = SimpleNamespace(request_id='configured-refusal')
    for operation in ('decisions.validate', 'decisions.run'):
        result = asyncio.run(capability.handlers[operation]({'job': _job(**override)}, context))
        assert result.status == 'refused'
    assert calls == [] and engine.calls == 0
    assert list(tmp_path.rglob('.run-[0-9a-f]*.json')) == []


def test_default_settings_preserve_original_factory_arguments(tmp_path):
    capability, _, calls = _capability(tmp_path)
    result = asyncio.run(capability.handlers['decisions.run'](
        {'job': _job()}, SimpleNamespace(request_id='default-positive')))
    assert result.status == 'completed'
    assert len(calls) == 1 and 'host_limits' not in calls[0]


@pytest.mark.parametrize('override', [{'timeout_seconds': True}, {'timeout_seconds': float('nan')},
                                      {'timeout_seconds': 601.0}, {'max_steps': 257},
                                      {'max_value_bytes': 1048577}, {'max_model_calls': -1}])
def test_explicit_host_configuration_keeps_original_absolute_bounds(tmp_path, override):
    with pytest.raises(DecisionError, match='invalid_settings'):
        _capability(tmp_path, host_limits={**default_host_limits(), **override})


def test_host_configuration_rejects_missing_or_unknown_budget_keys(tmp_path):
    for invalid in ({'timeout_seconds': 240.0}, {**default_host_limits(), 'price': 1}, []):
        with pytest.raises(DecisionError, match='invalid_settings'):
            _capability(tmp_path, host_limits=invalid)
