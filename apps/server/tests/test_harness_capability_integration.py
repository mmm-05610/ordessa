"""Cross-layer capability integration: one vocabulary, three projections.

This file owns the seams no single lane can prove on its own: that the
registry TOML, the plugin's checked-in projection and the Server's canonical
contract agree; that a deployment may only declare canonical abilities; that
the profile view comes from the registry rather than a stored snapshot; that
the upward boundaries stay separate; and that an ACP harness and a native
driver with equivalent abilities produce the *same* canonical view.

Nothing here re-tests a lane's unit rules; it fails if the lanes drift apart.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from ordessa_agents.harness.definitions import harness_capabilities as caps
from ordessa_server.composition.selected_harness_catalog import capture_selected_harness_catalog


REPO = Path(__file__).resolve().parents[3]
PLUGIN = REPO / "plugins"  / "harness"
JS_PROJECTION = PLUGIN / "runtime" / "capability_declarations.json"
#: Files on the capability path of the Server: none of them may name a Harness.
#: 032 §5-exec: the four server-compat capability-path modules are deleted
#: with the package; the live capability path is the kernel contract plus the
#: host bootstrap. The gate keeps asserting the same property (the files exist
#: and name no Harness brand) on the surviving surface.
NEUTRAL_FILES = (
    "packages/execution/agents/src/ordessa_agents/harness/definitions/harness_capabilities.py",
    "apps/server/src/ordessa_server/composition/runtime.py",
)
BRAND_TOKEN = re.compile(r"\b(?:codex|claude|hermes|opencode|pi-acp|deepseek|omp)\b", re.I)


def test_the_canonical_vocabulary_is_the_locked_one():
    assert caps.CAPABILITY_SCHEMA_VERSION == 1
    assert tuple(caps.CANONICAL_CAPABILITY_IDS) == (
        "start", "observe", "finish", "attach", "steer", "stream", "permissions",
        "native_continuation",
    )
    assert set(caps.CAPABILITY_SCOPES) == set(caps.CANONICAL_CAPABILITY_IDS)
    implementation = set(caps.IMPLEMENTATION_LEVEL_CAPABILITIES)
    semantic = set(caps.SEMANTIC_CAPABILITIES)
    assert implementation | semantic == set(caps.CANONICAL_CAPABILITY_IDS)
    assert not implementation & semantic


def test_registry_and_the_checked_in_projection_agree_item_for_item():
    """The TOML is the static source; the JSON is its validated projection."""
    registry = capture_selected_harness_catalog().registry
    projection = json.loads(JS_PROJECTION.read_text(encoding="utf-8"))
    assert projection["schemaVersion"] == caps.CAPABILITY_SCHEMA_VERSION
    declared = {
        definition.harness_type: sorted(definition.capabilities)
        for definition in registry.all()
    }
    assert projection["harnessTypes"] == declared, (
        "the JS projection and the registry declarations drifted apart")
    for harness_type, abilities in declared.items():
        assert set(abilities) <= set(caps.CANONICAL_CAPABILITY_IDS), harness_type


def test_a_deployment_may_only_declare_canonical_boolean_abilities():
    """The deployment seat is validated by the same contract, not a free dict.

    The sidecar deployment assembly retired with server-compat (032 §5-exec);
    the live validation surface is `pacthold.harness_contracts.validate_claims`
    (consumed by the registry schema `definition_from_dict`), so this seam now
    asserts the contract directly: canonical spelling accepted, drift aliases
    and non-boolean values typed-refused.
    """
    from ordessa_agents.harness.definitions.harness_capabilities import validate_claims

    # The canonical spelling is accepted, including an explicit false.
    assert validate_claims(
        {"start": True, "stream": False, "native_continuation": True}
    ) == {"start": True, "stream": False, "native_continuation": True}
    for drifted in ({"streaming": True}, {"approvals": False}, {"attachments": True},
                    {"sessions": True}):
        with pytest.raises(Exception) as refused:
            validate_claims(drifted)
        assert "CAPABILITY" in type(refused.value).__name__.upper(), (drifted, refused.value)
    for malformed in ({"stream": "yes"}, {"stream": 1}, {"stream": None}, {"stream": []}):
        with pytest.raises(Exception) as refused:
            validate_claims(malformed)
        assert "CAPABILITY" in type(refused.value).__name__.upper(), (malformed, refused.value)
    with pytest.raises(Exception) as unknown:
        validate_claims({"teleport": True})
    assert "CAPABILITY" in type(unknown.value).__name__.upper()


def test_the_wire_hello_never_carries_harness_capabilities():
    """hello.capabilities is the wire-method namespace and stays that way."""
    handler_source = (REPO / "packages/interfaces/system-access/src/ordessa_interfaces/system_access/services/invocation.py").read_text(
        encoding="utf-8")
    ids = re.findall(r'"([a-z][A-Za-z]*\.[A-Za-z]+)"', handler_source)
    assert ids, "no wire capability ids found"
    assert not set(ids) & set(caps.CANONICAL_CAPABILITY_IDS), (
        "a Harness capability leaked into the wire method namespace")


def test_the_capability_path_of_the_server_names_no_harness():
    """No brand branch, and no brand literal, on the capability path."""
    for relative in NEUTRAL_FILES:
        path = REPO / relative
        assert path.is_file(), relative
        found = BRAND_TOKEN.findall(path.read_text(encoding="utf-8"))
        assert not found, f"{relative} names a Harness: {sorted(set(found))}"


def test_a_harness_definition_produces_the_canonical_declaration_view():
    """The static side of the view is derived, never hand-written twice."""
    registry = capture_selected_harness_catalog().registry
    for definition in registry.all():
        claims = caps.canonical_capabilities(dict.fromkeys(definition.capabilities, True))
        declarations = caps.merge_capabilities(claims, {})
        view = caps.capability_view(definition.harness_type, declarations)
        assert view["schemaVersion"] == caps.CAPABILITY_SCHEMA_VERSION
        assert view["harnessType"] == definition.harness_type
        by_id = {item["id"]: item for item in view["capabilities"]}
        assert set(by_id) == set(caps.CANONICAL_CAPABILITY_IDS)
        for capability_id, item in by_id.items():
            assert item["declared"] is (capability_id in definition.capabilities)
            assert item["scope"] == caps.CAPABILITY_SCOPES[capability_id]
            # No ability is promoted by its declaration alone: the static view
            # reports the declared ceiling and every unobserved entry as unsupported.
            assert item["observed"] is None
            assert item["supported"] is False
            expected = (caps.CAPABILITY_NOT_OBSERVED if item["declared"]
                        else caps.CAPABILITY_NOT_DECLARED)
            assert item["reason"] == expected, (capability_id, item)
