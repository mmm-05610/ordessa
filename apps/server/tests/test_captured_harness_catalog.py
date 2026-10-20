"""Actual brand resources, immutable byte capture and typed composition refusals."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json

import pytest

from ordessa_server.composition.harness_catalog import capture_harness_catalog
from ordessa_server.composition import selected_harness_catalog as selected


def test_selected_public_pi_port_captures_once_without_selecting_other_brands(monkeypatch):
    calls = []
    port = selected.pi
    def counted():
        calls.append('pi')
        return port()
    monkeypatch.setattr(selected, 'pi', counted)
    captured = selected.capture_selected_harness_catalog()
    assert calls == ['pi']
    assert tuple(item.harness_type for item in captured.registry.all()) == ('pi',)
    assert captured.registry.digest == 'sha256:' + hashlib.sha256(captured.registry_bytes).hexdigest()
    # Preserve immutable producer bytes and exact paired registry/launch IDs.
    expected = capture_harness_catalog((port(),), launch_declarations=(port(),))
    assert captured.registry_bytes == expected.registry_bytes
    assert captured.launch_descriptor_bytes == expected.launch_descriptor_bytes


def test_duplicate_brand_selection_refuses_instead_of_overwriting():
    declaration = selected.pi()
    with pytest.raises(ValueError, match="duplicate harness_type"):
        capture_harness_catalog((declaration, declaration), launch_declarations=(declaration,))


def test_wrong_capture_type_refuses_before_parsing():
    with pytest.raises(TypeError, match="RegistrationDeclarations"):
        capture_harness_catalog((object(),), launch_declarations=())


def test_missing_launch_declaration_refuses_canonical_id_drift():
    declaration = selected.pi()
    launch = json.loads(declaration.launch_json)
    launch['id'] = 'unselected'
    launch['launch']['profile_id'] = 'unselected'
    changed = replace(declaration, launch_json=json.dumps(launch).encode())
    with pytest.raises(ValueError, match="canonical IDs drift"):
        capture_harness_catalog((declaration,), launch_declarations=(changed,))


def test_launch_identity_version_drift_refuses():
    declaration = selected.pi()
    launch = json.loads(declaration.launch_json)
    launch["registry_version"] = "unreviewed-version"
    changed = replace(declaration, launch_json=json.dumps(launch).encode())
    with pytest.raises(ValueError, match="registry version drift"):
        capture_harness_catalog((declaration,), launch_declarations=(changed,))


def test_captured_bytes_survive_later_resource_port_changes(monkeypatch):
    captured = selected.capture_selected_harness_catalog()
    original_registry = captured.registry
    original_bytes = captured.registry_bytes
    def unavailable():
        raise AssertionError("captured values must not reread ports")
    monkeypatch.setattr(selected, "pi", unavailable)
    assert captured.registry is original_registry
    assert captured.registry_bytes == original_bytes
    assert captured.registry.get("pi").harness_type == "pi"
    assert captured.registry.registry_identity_version_matches("claude", "anything") is False
