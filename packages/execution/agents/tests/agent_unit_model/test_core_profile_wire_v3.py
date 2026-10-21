"""Public Server wire bindings for inline Profile prepare/apply (C only).

These tests use the real Pacthold SQLite, AgentAssembly/AgentConfiguration,
Profile catalog and Invocation issuer with controlled provider/owner ports.
No native harness process or model is started.
"""
from __future__ import annotations
from ordessa_agents.profiles import encode_revision_ref
from ordessa_agents.profiles import decode_revision_ref

import json
import hashlib
from dataclasses import replace

import pytest

from ordessa_infrastructure.identifiers import RequestKey
from ordessa_units.errors import UnitOperationUnknown
from ordessa_units.public import (
    AGENT_CONTRACT_VERSION,
    AGENT_MANAGEMENT_CONTRACT_VERSION,
    ApplicationPolicy,
    ProfileRevisionRef,
    unit_services,
    encode_node_ref,
)
from ordessa_agents.harness.providers.registry.contributions import RUNTIME_METHODS
from ordessa_infrastructure.encoding.immutable_json import safe_json
from ordessa_server_plugin_api import WireError

from agent_tools_fixtures.assembly import assembly as assembly_fixture
from agent_tools_fixtures.node_publication import Provider, setup as node_fixture  # register transitive fixture dependency
from agent_tools_fixtures.management import setup as management_setup


DECLARATION = {
    "declarationId": "model",
    "configurationKind": "model",
    "schemaVersion": "1",
    "action": "value",
    "requirement": "required",
    "payload": {"modelId": "new"},
}
DEFINITION = {
    "environmentNamespace": "env",
    "definitionId": "fixture",
    "revision": "1",
}


@pytest.fixture(autouse=True)
def explicit_provider_capabilities(monkeypatch):
    monkeypatch.setattr(
        Provider,
        "descriptor",
        replace(Provider.descriptor, supported_methods=RUNTIME_METHODS),
    )


def _handlers(env, version=AGENT_MANAGEMENT_CONTRACT_VERSION):
    from ordessa_system_access_bindings import agent_core_methods

    return {
        item.method_id: item.handler
        for item in agent_core_methods(lambda: env, contract_version=version)
    }


def _manifest(declaration=DECLARATION):
    return {
        "harnessDefinitionRef": dict(DEFINITION),
        "schemaVersion": "1",
        "declarations": [dict(declaration)],
    }


def _base_profile_ref(parts):
    node = parts[4]
    services = getattr(parts[1], "_agent_services", None)
    assert services is not None
    record = services.nodes.read(node)
    return decode_revision_ref(dict(record['lineage']['profileSnapshotRef']))


@pytest.fixture
def management_wire(management_setup):
    services = unit_services(
        management_setup[1], invocation_issuer=management_setup[-1]
    )
    return _handlers(management_setup[1]), services


@pytest.fixture
def preparation_wire(assembly_fixture):
    coordinator, request, profile_ref, provider, store, nodes, _authority, _current, context_owner, owner, env, _activation = assembly_fixture
    services = unit_services(
        env,
        invocation_issuer=provider.issuer,
        node_evidence_port=nodes._evidence_port,
        preparation_context_port=context_owner,
        preparation_observation_port=owner,
    )
    return _handlers(env), services, assembly_fixture


def test_prepare_accepts_one_inline_manifest_and_replay_dispatches_once(preparation_wire):
    handlers, _services, parts = preparation_wire
    coordinator, _request, _profile_ref, provider, store, _nodes, *_rest, env, _activation = parts
    manifest = {
        "harnessDefinitionRef": dict(provider.descriptor.definition_ref),
        "schemaVersion": "1",
        "declarations": [],
    }
    params = {
        "profileManifest": manifest,
        "context": {},
        "options": {},
        "requestId": "wire-inline-prepare",
    }

    result = handlers["agents.nodes.prepare"](params)
    assert result["status"] == "published"
    assert result["node"]["nodeRef"]
    assert provider.calls == ["prepare", "start"]
    replay = handlers["agents.nodes.prepare"](params)
    assert replay == result
    assert provider.calls == ["prepare", "start"]
    assert store.read_operation(RequestKey("env", "principal", "wire-inline-prepare"))


@pytest.mark.parametrize("source_fields", [{}, {"profileRef": {"bad": "shape"}, "profileManifest": _manifest()}])
def test_prepare_rejects_missing_or_conflicting_sources_before_dispatch(preparation_wire, source_fields):
    handlers, _services, parts = preparation_wire
    _coordinator, _request, _profile_ref, provider, store, *_ = parts
    params = {
        "context": {},
        "options": {},
        "requestId": "wire-inline-prepare-invalid",
        **source_fields,
    }
    with pytest.raises(WireError) as caught:
        handlers["agents.nodes.prepare"](params)
    assert caught.value.family == "INVALID_REQUEST"
    assert store.read_operation(RequestKey("env", "principal", params["requestId"])) is None
    assert provider.calls == []


def test_apply_profile_accepts_inline_manifest_and_same_request_replays_once(management_setup, management_wire):
    handlers, services = management_wire
    parts = management_setup
    env, node, state = parts[1], parts[4], parts[7]
    base = _base_profile_ref(parts)
    params = {
        "nodeRef": encode_node_ref(node),
        "baseProfileRef": encode_revision_ref(base),
        "profileManifest": _manifest(),
        "expectedConfigurationRevision": "native-1",
        "applicationPolicy": ApplicationPolicy().to_dict(),
        "requestId": "wire-inline-apply",
    }

    assert services.configuration.capabilities()["configurationManagement"] is True
    caps = handlers["agents.capabilities"]({})
    assert "agents.nodes.applyProfile" in caps["supportedMethods"]
    result = handlers["agents.nodes.applyProfile"](params)
    assert result["status"] == "published"
    assert state["calls"] == 1 and state["model"] == "new"
    assert handlers["agents.nodes.applyProfile"](params) == result
    assert state["calls"] == 1


def test_apply_profile_same_request_with_different_manifest_does_not_dispatch_again(
    management_setup, management_wire
):
    handlers, _services = management_wire
    parts = management_setup
    base = _base_profile_ref(parts)
    params = {
        "nodeRef": encode_node_ref(parts[4]),
        "baseProfileRef": encode_revision_ref(base),
        "profileManifest": _manifest(),
        "expectedConfigurationRevision": "native-1",
        "applicationPolicy": ApplicationPolicy().to_dict(),
        "requestId": "wire-inline-apply-conflicting-replay",
    }
    first = handlers["agents.nodes.applyProfile"](params)
    changed = dict(params)
    changed["profileManifest"] = _manifest(
        {**DECLARATION, "payload": {"modelId": "different"}}
    )
    with pytest.raises(WireError) as caught:
        handlers["agents.nodes.applyProfile"](changed)
    assert caught.value.family == "CONFLICT_REQUEST"
    assert first["status"] == "published"
    assert parts[7]["calls"] == 1


def test_apply_profile_missing_required_resource_is_typed_and_unreserved(
    management_setup, management_wire
):
    handlers, _services = management_wire
    parts = management_setup
    declaration = {
        "declarationId": "model",
        "configurationKind": "model",
        "schemaVersion": "1",
        "action": "value",
        "requirement": "required",
        "resourceRefs": [{"environmentNamespace": "env", "resourceId": "missing"}],
    }
    params = {
        "nodeRef": encode_node_ref(parts[4]),
        "baseProfileRef": encode_revision_ref(_base_profile_ref(parts)),
        "profileManifest": _manifest(declaration),
        "expectedConfigurationRevision": "native-1",
        "applicationPolicy": ApplicationPolicy().to_dict(),
        "requestId": "wire-inline-apply-missing-resource",
    }
    with pytest.raises(WireError) as caught:
        handlers["agents.nodes.applyProfile"](params)
    assert caught.value.family == "CAPABILITY_UNSUPPORTED"
    assert caught.value.details["retryable"] is False
    assert parts[7]["calls"] == 0
    assert parts[0].read_operation(RequestKey("env", "principal", params["requestId"])) is None


@pytest.mark.parametrize(
    "source_fields",
    [
        {},
        {"profileRef": {"bad": "shape"}, "profileManifest": _manifest()},
    ],
)
def test_apply_profile_rejects_missing_or_conflicting_sources_without_effect(
    management_setup, management_wire, source_fields
):
    handlers, _services = management_wire
    parts = management_setup
    params = {
        "nodeRef": encode_node_ref(parts[4]),
        "baseProfileRef": encode_revision_ref(_base_profile_ref(parts)),
        "expectedConfigurationRevision": "native-1",
        "applicationPolicy": ApplicationPolicy().to_dict(),
        "requestId": "wire-inline-apply-invalid",
        **source_fields,
    }
    with pytest.raises(WireError) as caught:
        handlers["agents.nodes.applyProfile"](params)
    assert caught.value.family == "INVALID_REQUEST"
    assert parts[7]["calls"] == 0
    assert parts[0].read_operation(RequestKey("env", "principal", params["requestId"])) is None


def test_apply_profile_omission_names_missing_declaration_without_echoing_payload(
    management_setup, management_wire
):
    handlers, _services = management_wire
    parts = management_setup
    secret = "wire-omission-secret-sentinel"
    replacement = {
        "declarationId": "replacement",
        "configurationKind": "model",
        "schemaVersion": "1",
        "action": "value",
        "requirement": "required",
        "payload": {"modelId": secret},
    }
    params = {
        "nodeRef": encode_node_ref(parts[4]),
        "baseProfileRef": encode_revision_ref(_base_profile_ref(parts)),
        "profileManifest": _manifest(replacement),
        "expectedConfigurationRevision": "native-1",
        "applicationPolicy": ApplicationPolicy().to_dict(),
        "requestId": "wire-inline-apply-omission",
    }

    with pytest.raises(WireError) as caught:
        handlers["agents.nodes.applyProfile"](params)
    error = caught.value
    assert error.family == "INVALID_REQUEST"
    assert error.details["retryable"] is False
    assert error.details["internalCode"] == "CONFIGURATION_DECLARATIONS_OMITTED"
    assert error.details["omittedDeclarationIds"] == ["model"]
    assert secret not in str(error)
    assert secret not in json.dumps(error.details)
    assert parts[7]["calls"] == 0
    request = RequestKey("env", "principal", params["requestId"])
    with pytest.raises(UnitOperationUnknown):
        parts[0].read_operation(request)

    # Omission refusal is a data-only spent receipt in the existing request
    # store, not an OperationRecord or a reason to reserve/dispatch anew.
    services = getattr(parts[1], "_agent_services")
    snapshot_ref, _snapshot_write = services.profiles.stage_snapshot(_manifest(replacement))
    fixed = {
        "nodeRef": encode_node_ref(parts[4]),
        "profileRef": encode_revision_ref(snapshot_ref),
        "baseProfileRef": encode_revision_ref(_base_profile_ref(parts)),
        "expectedConfigurationRevision": "native-1",
        "applicationPolicy": ApplicationPolicy().to_dict(),
    }
    request_digest = parts[1]._fingerprint_port.fingerprint(
        request,
        "pacthold.agents.configuration.apply-profile-refusal",
        "sha256:" + hashlib.sha256(safe_json(fixed).encode()).hexdigest(),
    )
    receipt = parts[0].read_domain_result(request, request_digest)
    assert receipt == {
        "status": "refused",
        "code": "CONFIGURATION_DECLARATIONS_OMITTED",
        "omitted": ["model"],
    }
    with pytest.raises(WireError) as replay:
        handlers["agents.nodes.applyProfile"](params)
    assert replay.value.family == "INVALID_REQUEST"
    assert replay.value.details["internalCode"] == "CONFIGURATION_DECLARATIONS_OMITTED"
    assert replay.value.details["omittedDeclarationIds"] == ["model"]
    with pytest.raises(UnitOperationUnknown):
        parts[0].read_operation(request)
    assert parts[0].read_domain_result(request, request_digest) == receipt
    assert parts[7]["calls"] == 0


def test_apply_profile_is_not_advertised_or_dispatched_without_configuration_capability(
    management_setup,
):
    from ordessa_system_access_bindings import agent_core_methods

    parts = management_setup
    env, node = parts[1], parts[4]
    services = unit_services(env)
    handlers = _handlers(env)
    caps = handlers["agents.capabilities"]({})
    assert services.configuration.capabilities()["configurationManagement"] is False
    assert "agents.nodes.applyProfile" not in caps["supportedMethods"]
    params = {
        "nodeRef": encode_node_ref(node),
        "baseProfileRef": encode_revision_ref(_base_profile_ref(parts)),
        "profileManifest": _manifest(),
        "expectedConfigurationRevision": "native-1",
        "applicationPolicy": ApplicationPolicy().to_dict(),
        "requestId": "wire-apply-profile-unwired",
    }
    with pytest.raises(WireError) as caught:
        handlers["agents.nodes.applyProfile"](params)
    assert caught.value.family == "CAPABILITY_UNSUPPORTED"
    assert parts[7]["calls"] == 0
    assert parts[0].read_operation(RequestKey("env", "principal", params["requestId"])) is None


def test_v2_contract_does_not_fall_back_to_v3_profile_source_or_apply():
    from ordessa_system_access_bindings import agent_core_methods

    with pytest.raises(ValueError):
        agent_core_methods(lambda: None, contract_version="agent-assembly/2")
    assert AGENT_CONTRACT_VERSION != "agent-assembly/2"


def test_low_level_configuration_apply_keeps_its_existing_wire_contract(
    management_setup, management_wire
):
    handlers, _services = management_wire
    parts = management_setup
    from ordessa_units.configuration.contracts import ConfigurationChangeRequest

    node_ref = encode_node_ref(parts[4])
    params = {"nodeRef": node_ref, "change": parts[6].to_dict()}
    before = parts[7]["calls"]
    result = handlers["agents.nodes.configuration.apply"](params)
    assert result["status"] == "published"
    assert parts[7]["calls"] == before + 1
    assert ConfigurationChangeRequest.from_dict(parts[6].to_dict()) == parts[6]


@pytest.mark.parametrize("bad_policy", [None, {}, {"allowDeferred": 1, "allowRestart": False}, {"allowDeferred": False, "allowRestart": False, "extra": False}])
def test_apply_profile_validates_policy_through_public_dto(
    management_setup, management_wire, bad_policy
):
    handlers, _services = management_wire
    parts = management_setup
    params = {
        "nodeRef": encode_node_ref(parts[4]),
        "baseProfileRef": encode_revision_ref(_base_profile_ref(parts)),
        "profileManifest": _manifest(),
        "expectedConfigurationRevision": "native-1",
        "applicationPolicy": bad_policy,
        "requestId": "wire-inline-apply-bad-policy",
    }
    with pytest.raises(WireError) as caught:
        handlers["agents.nodes.applyProfile"](params)
    assert caught.value.family == "INVALID_REQUEST"
    assert parts[7]["calls"] == 0
    assert parts[0].read_operation(RequestKey("env", "principal", params["requestId"])) is None
