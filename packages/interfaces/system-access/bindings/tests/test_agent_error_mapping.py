"""Concrete owner refusal/unknown categories retain the original wire fences."""
from types import SimpleNamespace

import pytest

import ordessa_system_access_bindings.agents as adapter
from ordessa_units.errors import (
    UnitAdmissionRefused, UnitGuaranteeUnavailable, UnitIdentityMismatch,
    UnitComparisonUnavailable, UnitOperationUnknown,
)
from ordessa_execution_agents.profiles import (
    HistoricalProfileIdentityMismatch, ProfileAccessRefused,
    ProfileStoreUnavailable, ProfileChangeUnknown,
)
from server_plugin_api import WireError


@pytest.mark.parametrize("error,code", [
    (UnitAdmissionRefused, "FORBIDDEN"),
    (ProfileAccessRefused, "FORBIDDEN"),
    (UnitGuaranteeUnavailable, "CAPABILITY_UNSUPPORTED"),
    (ProfileStoreUnavailable, "CAPABILITY_UNSUPPORTED"),
    (UnitIdentityMismatch, "CONFLICT_REQUEST"),
    (HistoricalProfileIdentityMismatch, "CONFLICT_REQUEST"),
    (UnitComparisonUnavailable, "OUTCOME_UNKNOWN"),
    (UnitOperationUnknown, "OUTCOME_UNKNOWN"),
    (ProfileChangeUnknown, "OUTCOME_UNKNOWN"),
])
def test_profile_observation_maps_actual_owner_errors_without_retry(monkeypatch, error, code):
    calls = []
    class Catalog:
        def list(self, **_kwargs):
            calls.append("list")
            raise error("controlled owner result")
    monkeypatch.setattr(adapter, "unit_services", lambda _context: SimpleNamespace(profiles=Catalog()))
    methods = adapter.agent_core_methods(lambda: object())
    method = next(item for item in methods if item.method_id == "agents.profiles.list")
    with pytest.raises(WireError) as captured:
        method.handler({})
    assert captured.value.family == code
    assert captured.value.details["retryable"] is False
    assert calls == ["list"]


@pytest.mark.parametrize("error,code", [
    (ProfileAccessRefused, "FORBIDDEN"),
    (ProfileChangeUnknown, "OUTCOME_UNKNOWN"),
    (UnitComparisonUnavailable, "OUTCOME_UNKNOWN"),
])
def test_effectful_profile_call_distinguishes_known_refusal_from_unknown(monkeypatch, error, code):
    calls = []
    class Catalog:
        def request_key(self, _request_id):
            return object()
        def create(self, **_kwargs):
            calls.append("create")
            raise error("controlled original request")
    monkeypatch.setattr(adapter, "unit_services", lambda _context: SimpleNamespace(profiles=Catalog()))
    methods = adapter.agent_core_methods(lambda: object())
    method = next(item for item in methods if item.method_id == "agents.profiles.create")
    with pytest.raises(WireError) as captured:
        method.handler({"requestId":"same-request", "profileId":"profile", "displayName":"Profile",
                        "manifest":{"schemaVersion":"1", "harnessDefinitionRef":{
                            "environmentNamespace":"environment", "definitionId":"controlled", "revision":"1"},
                            "declarations":[], "metadata":{}}})
    assert captured.value.family == code
    assert captured.value.details["retryable"] is False
    assert calls == ["create"]
