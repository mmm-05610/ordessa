"""Current decision-job/1 closure; independent of the frozen R1 101->102 replay."""
import copy
import importlib.metadata
import importlib.resources
from pathlib import Path

import pytest

from ordessa_engineering.adapters.registry import loading, source_integrity as si
from ordessa_engineering.domain.common.outcomes.library_failures import EngineeringError
from ordessa_engineering.application.api.service import EngineeringService
from ordessa_engineering.application.usecases.reviews.assignments import ASSIGN_REVIEWER, command_input_schema


def test_current_facts_pin_real_job_contract_metadata_and_complete_sources():
    from ordessa_decision.job import SPEC_VERSION
    facts = si.implementation_facts()
    assert facts['decision_contract_version'] == SPEC_VERSION == 'decision-job/1'
    assert facts['ordessa_decision_version'] == importlib.metadata.version('decision-runtime') == '0.2.0'
    assert facts['jsonschema_version'] == importlib.metadata.version('jsonschema')
    assert facts['referencing_version'] == importlib.metadata.version('referencing')
    assert 'pydantic_graph_version' not in facts
    assert set(facts) == {'engineering', 'ordessa_decision', 'ordessa_decision_version',
                         'decision_contract_version', 'jsonschema_version', 'referencing_version'}
    engineering = Path(si.__file__).parents[2]
    decision = Path(importlib.resources.files('ordessa_decision'))
    assert set(si.ENGINEERING_FILES) == {p.relative_to(engineering).as_posix() for p in engineering.rglob('*.py')}
    assert len(si.ENGINEERING_FILES) == len(set(si.ENGINEERING_FILES))
    assert set(si.DECISION_RUNTIME_FILES) == {p.relative_to(decision).as_posix() for p in decision.rglob('*.py')}
    assert len(si.DECISION_RUNTIME_FILES) == len(set(si.DECISION_RUNTIME_FILES))
    assert 'job.py' in facts['ordessa_decision'] and 'runner.py' in facts['ordessa_decision']
    assert 'historical/reader.py' in facts['ordessa_decision']
    assert 'runtime/flows.py' not in facts['ordessa_decision']
    assert 'validation/requests.py' not in facts['ordessa_decision']


@pytest.mark.parametrize('dependency', ['decision-runtime', 'jsonschema', 'referencing'])
def test_missing_actual_runtime_metadata_refuses_without_fallback(monkeypatch, dependency):
    original = importlib.metadata.version
    def missing(name):
        if name == dependency:
            raise importlib.metadata.PackageNotFoundError(name)
        return original(name)
    monkeypatch.setattr(si.importlib.metadata, 'version', missing)
    with pytest.raises(EngineeringError, match='operation_registry_dependency_unavailable'):
        si.implementation_facts()


@pytest.mark.parametrize('section,key', [
    ('ordessa_decision', 'job.py'), ('ordessa_decision', 'runner.py'),
    ('ordessa_decision', 'historical/reader.py'),
    ('engineering', 'adapters/decision/source_job.py'),
    ('engineering', 'ordessa_infrastructure:database/sqlite.py'),
])
def test_current_verifier_rejects_changed_and_omitted_source_pins(section, key):
    # Exercise current facts directly; no historical manifest is resealed or
    # treated as current approval. The active resource is tested separately.
    facts = si.implementation_facts()
    si.verify_implementation({'implementation': facts})
    for mutation in ('changed', 'omitted'):
        wrong = copy.deepcopy(facts)
        if mutation == 'changed':
            wrong[section][key] = 'sha256:' + '0' * 64
        else:
            del wrong[section][key]
        with pytest.raises(EngineeringError, match='operation_registry_source_drift'):
            si.verify_implementation({'implementation': wrong})


@pytest.mark.parametrize('key', ['ordessa_decision_version', 'decision_contract_version',
                                 'jsonschema_version', 'referencing_version'])
def test_current_verifier_rejects_dependency_or_contract_drift(key):
    facts = si.implementation_facts()
    facts[key] = 'unreviewed-change'
    with pytest.raises(EngineeringError, match='operation_registry_source_drift'):
        si.verify_implementation({'implementation': facts})


def test_active_current_registry_validates_current_facts_and_real_handlers():
    registry = loading.load_registry()
    assert registry['revision'] > 126
    assert registry['implementation'] == si.implementation_facts()
    current = {d.capability_id: {'version':d.interface_version,
        'inputs':d.contract['input_schema'], 'results':d.contract['workflow_outcomes']}
        for d in EngineeringService.operation_capabilities().capabilities}
    assert registry['operations'] == current
    assert registry['operations'][ASSIGN_REVIEWER]['version'] == '2'
    assert registry['operations'][ASSIGN_REVIEWER]['inputs'] == command_input_schema(ASSIGN_REVIEWER)
    # Native owner dispatch has its own explicitly bound v2 descriptor. It is
    # not silently added to this finite command registry or the old v1 set.
    assert 'engineering.executions.dispatch' not in registry['operations']


@pytest.mark.parametrize('dependency,version', [
    ('decision-runtime', '0.1.0'), ('jsonschema', '4.19.2'), ('referencing', '0.35.0'),
])
def test_real_loader_refuses_changed_dependency_metadata(monkeypatch, dependency, version):
    original = importlib.metadata.version
    monkeypatch.setattr(si.importlib.metadata, 'version',
                        lambda name: version if name == dependency else original(name))
    with pytest.raises(EngineeringError, match='operation_registry_source_drift'):
        loading.load_registry()


@pytest.mark.parametrize('relative', ['job.py', 'runner.py', 'historical/reader.py'])
def test_real_loader_refuses_changed_decision_source_bytes(monkeypatch, relative):
    target = Path(importlib.resources.files('ordessa_decision')) / relative
    original = si._sha256
    monkeypatch.setattr(si, '_sha256',
                        lambda path: 'sha256:' + '0'*64 if path == target else original(path))
    with pytest.raises(EngineeringError, match='operation_registry_source_drift'):
        loading.load_registry()


@pytest.mark.parametrize('mutation', ['reviewer-version', 'reviewer-input', 'extra-operation'])
def test_real_loader_refuses_operation_content_tamper(monkeypatch, mutation):
    registry = loading.load_registry()
    if mutation == 'reviewer-version':
        registry['operations'][ASSIGN_REVIEWER]['version'] = '1'
    elif mutation == 'reviewer-input':
        registry['operations'][ASSIGN_REVIEWER]['inputs'] = {'unreviewed': 'str'}
    else:
        registry['operations']['engineering.unreviewed'] = {'version':'1', 'inputs':{}, 'results':[]}
    # The packaged digest protects operation content; the explicit refresh
    # planner separately rejects resealed/unreviewed operation changes.
    monkeypatch.setattr(loading, '_manifest', lambda: registry)
    with pytest.raises(EngineeringError, match='operation_registry_digest_mismatch'):
        loading.load_registry()
