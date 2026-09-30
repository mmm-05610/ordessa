"""Real C2 carrier/C4 journal with a controlled native owner, no model calls."""
from dataclasses import asdict
from types import SimpleNamespace
import copy
import hashlib
import json

import pytest
from ordessa_harness_api import ApplicationTarget, DesiredFragment, Installation
from ordessa_harness.application.configuration_service import ConfigurationApplicationService
from ordessa_harness.application.operation_journal import OperationJournal
from ordessa_harness.application.action_execution import ActionGrant
from ordessa_harness.configuration.model.plugin import ModelProviderAdaptersPlugin
from ordessa_harness.pi.configuration.runtime import PiLiveModelRuntime
from ordessa_harness.server_acp.pi_action_executor import configuration_digest
from ordessa_harness.server_acp.profile_owner import ProfileConfigurationSnapshot
from ordessa_harness.server_acp.registry import NativeSessionObservation
from ordessa_server.bootstrap import build_runtime


@pytest.fixture
def rig(tmp_path):
    product = build_runtime(tmp_path / "product")
    product.plugin_host.activate(ModelProviderAdaptersPlugin())
    view = next(v for v in product.plugin_host.contributions("harness.configuration-adapters")
                if v.payload.descriptor.adapter_id == "assets.model-provider.pi")
    target = ApplicationTarget("incarnation", "canonical", "channel", 1)
    owner = NativeSessionObservation("channel", "execution", "ledger", "native")
    options = [{"id": "model", "type": "select", "currentValue": "p/old", "options": [
        {"value": "p/new", "_meta": {"ordessaModel": {"provider": "p", "model": "new",
         "api": "openai-completions", "baseUrl": "https://fixture.test/v1"}}}]}]
    calls = []
    class Channel:
        harness_id = "pi"
        ended = False
        def _configuration_rpc(self, native, method, request):
            assert native == "native" and method == "_ordessa/session/configuration/apply"
            before = configuration_digest(options)
            assert request["expectedConfigDigest"] == before
            calls.append(copy.deepcopy(request))
            options[0]["currentValue"] = request["value"]
            after = {"sessionId": "native", "generation": "native-generation", "busy": False,
                     "configOptions": copy.deepcopy(options)}
            manifest = json.dumps(request["actionManifest"], sort_keys=True, ensure_ascii=False,
                                  separators=(",", ":"))
            return owner, {"operationId": request["operationId"], "state": "observed",
                "generation": "native-generation", "target": asdict(target),
                "manifestDigest": hashlib.sha256(manifest.encode()).hexdigest(),
                "beforeConfigDigest": before, "configId": "model", "requestedValue": request["value"],
                "observedValue": request["value"], "afterConfigDigest": configuration_digest(options),
                "after": after, "evidenceRef": "pi-native-operation:fixture"}
    channel = Channel()
    registry = SimpleNamespace(get=lambda _: channel, native_session_observation=lambda *args: owner)
    def readback(t):
        assert t == target
        return ProfileConfigurationSnapshot(t, owner, "native-generation", False, json.dumps(options))
    owners = SimpleNamespace(readback=readback)
    runtime = PiLiveModelRuntime(registry, owners, target=target,
        installation=Installation("pi", (0, 5, 0), (1, 0, 0), "fixture:verified-installation"),
        private_root=tmp_path / "never-materialized", publication_revision=view.publication_token)
    grant = ActionGrant(target, view.owner, view.publication_token, "assets.model-provider", "choice",
                        "1", "acp.session.set-config-option", "1")
    service = ConfigurationApplicationService(principal="backend", target=target,
        carrier=product.plugin_host, runtime=runtime, permits=None, owner_application=True,
        journal=OperationJournal(tmp_path / "operations.sqlite"), action_executor=runtime,
        action_grants=(grant,))
    desired = {"provider": "p", "model": "new", "protocol": "openai-chat",
               "endpoint": "https://fixture.test/v1", "credentialRef": None}
    fragment = lambda value: DesiredFragment("assets.model-provider", "choice", "1",
        "provider:fixture", "revision:1", "set", value)
    yield service, runtime, target, desired, fragment, calls, options, product
    product.stop()


def test_c4_live_model_confirmed_only_with_native_receipt_independent_query_and_match(rig):
    service, runtime, target, desired, fragment, calls, options, _ = rig
    plan = service.plan(target, (fragment(desired),), runtime.capture(target).before_revision)
    assert plan.kind == "plan" and not calls, plan
    result = service.apply_prepared(plan.plan_id, "apply-model")
    assert result.kind == "confirmed", result
    assert len(calls) == 1 and options[0]["currentValue"] == "p/new"
    assert not runtime.private_root.exists()
    assert service.apply_prepared(plan.plan_id, "apply-model") == result
    assert len(calls) == 1


@pytest.mark.parametrize("patch", [{"endpoint": "https://changed.test"},
    {"credentialRef": "ref://new"}, {"protocol": "openai-responses"}])
def test_unproven_provider_changes_have_zero_native_effects(rig, patch):
    service, runtime, target, desired, fragment, calls, _, _ = rig
    plan = service.plan(target, (fragment({**desired, **patch}),), runtime.capture(target).before_revision)
    assert plan.kind == "refused" and not calls


def test_native_change_after_plan_and_adapter_unload_refuse_before_effects(rig):
    service, runtime, target, desired, fragment, calls, options, product = rig
    plan = service.plan(target, (fragment(desired),), runtime.capture(target).before_revision)
    assert plan.kind == "plan", plan
    options[0]["currentValue"] = "p/external-change"
    assert service.apply_prepared(plan.plan_id, "stale").kind == "refused"
    assert not calls
    plan = service.plan(target, (fragment(desired),), runtime.capture(target).before_revision)
    assert plan.kind == "plan"
    product.plugin_host.deactivate("ordessa.model-provider.adapters")
    assert service.apply_prepared(plan.plan_id, "unloaded").kind == "refused"
    assert not calls


def test_wrong_independent_model_readback_is_unknown_never_confirmed(rig):
    service, runtime, target, desired, fragment, calls, options, _ = rig
    plan = service.plan(target, (fragment(desired),), runtime.capture(target).before_revision)
    original = runtime.observe
    def mismatched(t):
        options[0]["currentValue"] = "p/wrong"
        return original(t)
    runtime.observe = mismatched
    assert service.apply_prepared(plan.plan_id, "mismatch").kind == "unknown"
    assert len(calls) == 1


def test_preflight_does_not_refresh_away_a_change_since_c4_capture(rig):
    from ordessa_harness.application.action_execution import ActionBatch, ActionInvocation
    from ordessa_harness_api import IntentSource, InvokeAction
    service, runtime, target, _, _, calls, options, _ = rig
    runtime.capture(target)
    grant = service.action_grants[0]
    batch = ActionBatch(target, (ActionInvocation(grant.publication_owner, grant.publication_token,
        InvokeAction(IntentSource("assets.model-provider", "choice", "1"),
            "acp.session.set-config-option", "1", {"configId": "model", "value": "p/new"}, "p/new")),))
    options[0]["currentValue"] = "p/external-change"
    with pytest.raises(ValueError, match="before configuration changed"):
        runtime.preflight(batch)
    assert not calls
