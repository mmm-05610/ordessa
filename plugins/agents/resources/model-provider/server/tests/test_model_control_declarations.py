"""Additional explicit model-control source and actual records freeze evidence."""
from dataclasses import FrozenInstanceError

import pytest

from ordessa_harness_codex.configuration import c2
from ordessa_model_provider.harness_declarations import ModelConfigurationCatalog
from ordessa_model_provider.testing import wire_body
from ordessa_server_plugin_api.internal_errors import ServerError


def _capture(controls):
    return ModelConfigurationCatalog([c2.descriptor()],
        protocol_ports={'codex': c2.declared_protocols}, model_control_ports=controls)


def test_model_control_mapping_is_required():
    with pytest.raises(TypeError, match='model_control_ports'):
        ModelConfigurationCatalog([c2.descriptor()],
            protocol_ports={'codex': c2.declared_protocols})


@pytest.mark.parametrize('controls', [None, [], (), 'model', 1])
@pytest.mark.parametrize('selected', [[], [c2.descriptor()]])
def test_model_control_nonmapping_rejected_even_for_empty_selection(controls, selected):
    with pytest.raises(ValueError, match='Explicit selected model-control declarations required'):
        ModelConfigurationCatalog(selected,
            protocol_ports={'codex': c2.declared_protocols}, model_control_ports=controls)


@pytest.mark.parametrize('controls', [{}, {'other': c2.declared_model_control},
                                      {'codex': None}, {'codex': 'model'}])
def test_selected_model_control_port_must_be_explicit_callable(controls):
    with pytest.raises(ValueError, match='Selected provider model-control declaration required'):
        _capture(controls)


@pytest.mark.parametrize('value', ['', ' model', 'model ', 'mo\x00del', 'mo\ndel',
                                   'x' * 129, 0, False, [], {}])
def test_model_control_identifier_rejects_invalid_values(value):
    with pytest.raises(ValueError, match='Bounded declared model-control id required'):
        _capture({'codex': lambda: value})


def test_protocol_error_priority_is_preserved_with_bad_control_source():
    with pytest.raises(ServerError) as caught:
        ModelConfigurationCatalog([c2.descriptor()],
            protocol_ports={'codex': lambda: {'martian-wire': 'declared'}},
            model_control_ports=None)
    assert caught.value.code == 'PROTOCOL_UNKNOWN'


def test_explicit_no_control_freeze_returns_none_without_record_resolution(catalog):
    selected = _capture({'codex': lambda: None})
    assert selected.get('codex').model_control_id is None
    catalog.harnesses = selected
    assert catalog.freeze_execution_configuration('codex', {}) is None
    assert catalog.freeze_execution_configuration('codex',
        {'model': {'providerId': 'missing-record', 'modelId': 'missing-model'}}) is None


def test_actual_control_is_captured_once_and_freezes_real_records(catalog):
    declared = c2.declared_model_control()
    source = {'port': c2.declared_model_control, 'calls': 0}

    def capture_control():
        source['calls'] += 1
        return source['port']()

    selected = _capture({'codex': capture_control})
    assert source['calls'] == 1
    assert selected.get('codex').model_control_id == declared
    with pytest.raises(FrozenInstanceError):
        selected.get('codex').model_control_id = 'mutated'
    source['port'] = lambda: 'other-control'
    assert selected.get('codex').model_control_id == declared
    assert source['calls'] == 1
    catalog.harnesses = selected
    record = catalog.create('captured-model-control-record',
        wire_body(harness=None, configuration=[]))
    reference = {'providerId': record['id'], 'modelId': 'm1'}
    frozen = catalog.freeze_execution_configuration('codex', {declared: reference})
    assert frozen['model'] == 'm1'
    assert frozen['providerModelId'] == record['id']
    assert set(frozen) == {'providerModelId', 'providerModelVersion', 'provider',
                           'model', 'credentialId', 'configuration'}
    assert source['calls'] == 1
    with pytest.raises(ServerError) as caught:
        catalog.freeze_execution_configuration('codex', {'other-control': reference})
    assert caught.value.code == 'PROFILE_CONFIGURATION_INVALID'
