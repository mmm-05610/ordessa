"""Pi Unit declaration is independent of the historical Step model receipt."""
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from ordessa_server.composition import product_native_configuration as configuration


def _runtime():
    context = SimpleNamespace(environment_namespace="pi-unit-test")
    return SimpleNamespace(unit_runtime=SimpleNamespace(context=context), started=False)


def _fake_binary_observation(monkeypatch):
    bridge = b"controlled Pi ACP bridge"
    pi = b"controlled Pi executable"
    bridge_digest = sha256(bridge).hexdigest()
    pi_digest = sha256(pi).hexdigest()
    monkeypatch.setattr(configuration, "_BRIDGE_SHA256", bridge_digest)
    monkeypatch.setattr(configuration, "_PI_EXECUTABLE_SHA256", pi_digest)
    monkeypatch.setattr(configuration, "_verify_bridge_executable", lambda value: Path(value))
    monkeypatch.setattr(configuration, "_verify_pi_executable", lambda value: Path(value))
    reads = []

    def read(path, *, expected_path, limit):
        reads.append((path, expected_path, limit))
        if expected_path == configuration._BRIDGE_EXECUTABLE:
            return bridge
        if expected_path == configuration._PI_EXECUTABLE_TARGET:
            return pi
        raise AssertionError("generic Pi declaration must not inspect model receipts")

    monkeypatch.setattr(configuration, "_read_pinned_file", read)
    return reads


def test_generic_pi_declaration_observes_only_the_pinned_binaries(monkeypatch):
    reads = _fake_binary_observation(monkeypatch)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("generic Pi declaration must not read Step model metadata")

    monkeypatch.setattr(configuration, "_repository_root", forbidden)
    monkeypatch.setattr(configuration, "read_step5_preview_free_model_facts", forbidden)

    declaration = configuration.construct_pi_harness_declaration(
        _runtime(), bridge_executable="/controlled/pi-bridge",
        pi_executable="/controlled/pi",
    )

    assert declaration.descriptor.provider_id == "pi"
    assert declaration.descriptor.definition_ref == {
        "environmentNamespace": "pi-unit-test", "definitionId": "pi", "revision": "2.0",
    }
    assert declaration.descriptor.protocol_id == "acp/v1"
    assert declaration.descriptor.capabilities == ("existingChannel",)
    observation = declaration.installation_observer(dict(declaration.descriptor.definition_ref))
    assert observation.state == "present"
    assert observation.version_verified is True
    assert len(reads) == 2

    mismatch = declaration.installation_observer({
        **declaration.descriptor.definition_ref, "revision": "other",
    })
    assert mismatch.state == "unknown"
    assert len(reads) == 2


def test_historical_step_wrapper_still_rejects_non_step_model_route(monkeypatch):
    _fake_binary_observation(monkeypatch)
    calls = []

    def wrong_historical_facts(**_kwargs):
        calls.append(True)
        return configuration.PiModelFacts(
            ("some-other-model",), {"provider": "another-provider"},
        )

    monkeypatch.setattr(configuration, "read_step5_preview_free_model_facts", wrong_historical_facts)
    monkeypatch.setattr(configuration, "construct_pi_harness_declaration", lambda *_a, **_kw:
                        pytest.fail("historical route mismatch must not fall back to generic declaration"))

    with pytest.raises(configuration.NativeConfigurationUnavailable, match="reviewed model route"):
        configuration.construct_step5_preview_free_harness_declaration(
            _runtime(), repository_root="/controlled/repository",
            bridge_executable="/controlled/pi-bridge", pi_executable="/controlled/pi",
        )
    assert calls == [True]


def test_explicit_reviewed_bridge_pin_is_reread_without_changing_default(tmp_path, monkeypatch):
    bridge = tmp_path / 'reviewed-bridge'
    bridge.write_bytes(b'reviewed-build')
    pinned = sha256(bridge.read_bytes()).hexdigest()
    old_pin = configuration._BRIDGE_SHA256
    pi = b'controlled-native-pi'
    monkeypatch.setattr(configuration, '_verify_pi_executable', lambda value: Path(value))
    monkeypatch.setattr(configuration, '_PI_EXECUTABLE_SHA256', sha256(pi).hexdigest())
    real_read = configuration._read_pinned_file
    def read(path, **kwargs):
        if path == configuration._PI_EXECUTABLE_TARGET:
            return pi
        return real_read(path, **kwargs)
    monkeypatch.setattr(configuration, '_read_pinned_file', read)
    declaration = configuration.construct_pi_harness_declaration(_runtime(),
        bridge_executable=bridge, pi_executable='/controlled/pi', reviewed_bridge_sha256=pinned)
    assert declaration.descriptor.implementation_digest == 'sha256:' + pinned
    assert declaration.installation_observer(dict(declaration.descriptor.definition_ref)).state == 'present'
    bridge.write_bytes(b'changed-build')
    assert declaration.installation_observer(dict(declaration.descriptor.definition_ref)).state == 'unknown'
    with pytest.raises(configuration.NativeConfigurationUnavailable, match='digest differs'):
        configuration.construct_pi_harness_declaration(_runtime(), bridge_executable=bridge,
            pi_executable='/controlled/pi', reviewed_bridge_sha256=pinned)
    assert configuration._BRIDGE_SHA256 == old_pin
