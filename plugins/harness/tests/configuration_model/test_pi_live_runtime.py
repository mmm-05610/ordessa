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


@pytest.mark.parametrize('brand,protocol,provider,api', [
    ('codex', 'openai-responses', 'custom-gateway', 'responses'),
    ('claude-code', 'anthropic-messages', 'main', 'anthropic'),
])
def test_native_compiler_accepts_bounded_nested_groups_but_not_malformed_catalog(brand, protocol, provider, api):
    from ordessa_harness.configuration.model.live_model import compile_native_model
    from ordessa_harness_api import AdapterRefusal, InvokeAction, IntentSource
    option = {'value': 'new', '_meta': {'ordessaModel': {
        'provider': provider, 'api': api, 'baseUrl': 'https://fixture.test/v1', 'model': 'new'}}}
    snapshot = SimpleNamespace(busy=False, native_generation='g', config_options=[{
        'id': 'model', 'type': 'select', 'options': [{'options': [{'options': [option]}]}]}])
    desired = {'provider': 'business-label', 'model': 'new', 'protocol': protocol,
               'endpoint': 'https://fixture.test/v1'}
    source = IntentSource('assets.model-provider', 'choice', '1')
    assert isinstance(compile_native_model(snapshot, desired, source, brand), InvokeAction)
    for options in ([{'options': [{'options': [{'options': [option]}]}]}], ['malformed'],
                    [{'value': 'new', '_meta': 'malformed'}], [option, option]):
        snapshot.config_options[0]['options'] = options
        assert isinstance(compile_native_model(snapshot, desired, source, brand), AdapterRefusal)
from ordessa_harness.server_acp.pi_action_executor import configuration_digest
from ordessa_harness.server_acp.profile_owner import ProfileConfigurationSnapshot
from ordessa_harness.server_acp.registry import NativeSessionObservation
from ordessa_server.bootstrap import build_runtime


@pytest.fixture
def rig(tmp_path):
    yield from make_rig(tmp_path, 'pi')


def make_rig(tmp_path, brand):
    product = build_runtime(tmp_path / "product")
    product.plugin_host.activate(ModelProviderAdaptersPlugin())
    view = next(v for v in product.plugin_host.contributions("harness.configuration-adapters")
                if v.payload.descriptor.adapter_id == 'assets.model-provider.' +
                {'pi': 'pi', 'codex': 'codex', 'claude-code': 'claude'}[brand])
    target = ApplicationTarget("incarnation", "canonical", "channel", 1)
    owner = NativeSessionObservation("channel", "execution", "ledger", "native")
    options = [{"id": "model", "type": "select", "currentValue": "p/old", "options": [
        {"value": "p/new", "_meta": {"ordessaModel": {"provider": "p", "model": "new",
         "api": "openai-completions", "baseUrl": "https://fixture.test/v1"}}}]}]
    if brand != 'pi':
        options[0]['currentValue'] = 'old'
        options[0]['options'][0] = {'value': 'new', '_meta': {'ordessaModel': {
            'provider': 'custom-gateway' if brand == 'codex' else 'main', 'model': 'new',
            'api': 'responses' if brand == 'codex' else 'anthropic', 'baseUrl': 'https://fixture.test/v1'}}}
    calls = []
    class Channel:
        harness_id = brand
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
                "after": after, "evidenceRef": brand + "-native-operation:fixture"}
    channel = Channel()
    registry = SimpleNamespace(get=lambda _: channel, native_session_observation=lambda *args: owner)
    def readback(t):
        assert t == target
        return ProfileConfigurationSnapshot(t, owner, "native-generation", False, json.dumps(options))
    owners = SimpleNamespace(readback=readback)
    from ordessa_harness.codex.configuration.runtime import CodexLiveModelRuntime
    from ordessa_harness.claude.configuration.runtime import ClaudeLiveModelRuntime
    runtime_class = {'pi': PiLiveModelRuntime, 'codex': CodexLiveModelRuntime,
                     'claude-code': ClaudeLiveModelRuntime}[brand]
    runtime = runtime_class(registry, owners, target=target,
        installation=Installation(brand, runtime_class.native_version, (1, 0, 0), "fixture:verified-installation"),
        private_root=tmp_path / "never-materialized", publication_revision=view.publication_token)
    grant = ActionGrant(target, view.owner, view.publication_token, "assets.model-provider", "choice",
                        "1", "acp.session.set-config-option", "1")
    service = ConfigurationApplicationService(principal="backend", target=target,
        carrier=product.plugin_host, runtime=runtime, permits=None, owner_application=True,
        journal=OperationJournal(tmp_path / "operations.sqlite"), action_executor=runtime,
        action_grants=(grant,))
    if brand != 'pi':
        from ordessa_harness.configuration.model.live_service import create_model_service
        service, runtime = create_model_service(registry=registry, owners=owners, target=target,
            carrier=product.plugin_host, installation=runtime.installation,
            journal_path=tmp_path / 'factory-operations.sqlite')
    desired = {"provider": "p", "model": "new", "protocol": "openai-chat",
               "endpoint": "https://fixture.test/v1", "credentialRef": None}
    if brand != 'pi':
        desired['protocol'] = 'openai-responses' if brand == 'codex' else 'anthropic-messages'
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


@pytest.fixture(params=['codex', 'claude-code'])
def native_rig(tmp_path, request):
    yield from make_rig(tmp_path, request.param)


def test_two_brand_c4_confirmed_requires_bound_action_and_independent_native_observation(native_rig):
    service, runtime, target, desired, fragment, calls, options, _ = native_rig
    plan = service.plan(target, (fragment(desired),), runtime.capture(target).before_revision)
    assert plan.kind == 'plan' and not calls, plan
    result = service.apply_prepared(plan.plan_id, 'native-model')
    assert result.kind == 'confirmed', result
    assert len(calls) == 1 and options[0]['currentValue'] == 'new'
    assert not runtime.private_root.exists()
    assert service.apply_prepared(plan.plan_id, 'native-model') == result and len(calls) == 1


def test_two_brand_private_credential_binding_preserves_ref_and_requires_c4_receipt(native_rig):
    service, runtime, target, desired, fragment, calls, options, _ = native_rig
    desired = {**desired, 'credentialRef': 'ref://startup-credential'}
    seen = []
    def binding(snapshot, value):
        seen.append((snapshot.owner.native_session_id, copy.deepcopy(value)))
        return (all(value.get(key) == desired.get(key) for key in ('provider', 'protocol', 'endpoint', 'credentialRef'))
                and snapshot.native_generation == 'native-generation')
    runtime.credential_binding = binding
    plan = service.plan(target, (fragment(desired),), runtime.capture(target).before_revision)
    assert plan.kind == 'plan' and not calls
    result = service.apply_prepared(plan.plan_id, 'credential-bound-model')
    assert result.kind == 'confirmed', result
    assert len(calls) == 1 and options[0]['currentValue'] == 'new'
    assert len(seen) >= 4
    assert all(value['credentialRef'] == 'ref://startup-credential' for _, value in seen)
    second = copy.deepcopy(options[0]['options'][0])
    second['value'] = 'second-model'
    second['_meta']['ordessaModel']['model'] = 'second-model'
    options[0]['options'].append(second)
    second_desired = {**desired, 'model': 'second-model'}
    second_plan = service.plan(target, (fragment(second_desired),), runtime.capture(target).before_revision)
    assert second_plan.kind == 'plan', second_plan
    second_result = service.apply_prepared(second_plan.plan_id, 'credential-bound-second-model')
    assert second_result.kind == 'confirmed', second_result
    assert len(calls) == 2 and options[0]['currentValue'] == 'second-model'


def test_two_brand_credential_binding_changed_after_plan_refuses_without_effect(native_rig):
    service, runtime, target, desired, fragment, calls, _, _ = native_rig
    desired = {**desired, 'credentialRef': 'ref://startup-credential'}
    runtime.credential_binding = lambda snapshot, value: True
    plan = service.plan(target, (fragment(desired),), runtime.capture(target).before_revision)
    assert plan.kind == 'plan' and not calls
    runtime.credential_binding = lambda snapshot, value: False
    assert service.apply_prepared(plan.plan_id, 'credential-changed').kind == 'refused'
    assert not calls


def test_two_brand_private_binding_also_fences_dropped_credential_reference(native_rig):
    service, runtime, target, desired, fragment, calls, _, _ = native_rig
    runtime.credential_binding = lambda snapshot, value: value.get('credentialRef') == 'ref://startup-credential'
    plan = service.plan(target, (fragment(desired),), runtime.capture(target).before_revision)
    assert plan.kind == 'refused' and not calls


@pytest.mark.parametrize('patch', [{'endpoint': 'https://changed.test'}, {'credentialRef': 'ref://changed'},
                                 {'protocol': 'gemini-generate'}, {'requestParams': {'maxTokens': 10}}])
def test_two_brand_model_action_never_discards_provider_or_other_configuration_changes(native_rig, patch):
    service, runtime, target, desired, fragment, calls, _, _ = native_rig
    plan = service.plan(target, (fragment({**desired, **patch}),), runtime.capture(target).before_revision)
    assert plan.kind == 'refused' and not calls


def test_two_brand_missing_route_and_stale_capture_refuse_without_effect(native_rig):
    service, runtime, target, desired, fragment, calls, options, _ = native_rig
    original = copy.deepcopy(options[0]['options'][0]['_meta'])
    options[0]['options'][0].pop('_meta')
    assert service.plan(target, (fragment(desired),), runtime.capture(target).before_revision).kind == 'refused'
    options[0]['options'][0]['_meta'] = original
    plan = service.plan(target, (fragment(desired),), runtime.capture(target).before_revision)
    assert plan.kind == 'plan'
    options[0]['currentValue'] = 'external-change'
    assert service.apply_prepared(plan.plan_id, 'stale-native').kind == 'refused'
    assert not calls


def test_two_brand_independent_readback_mismatch_is_unknown(native_rig):
    service, runtime, target, desired, fragment, calls, options, _ = native_rig
    plan = service.plan(target, (fragment(desired),), runtime.capture(target).before_revision)
    original = runtime.observe
    def mismatched(t):
        options[0]['currentValue'] = 'wrong'
        return original(t)
    runtime.observe = mismatched
    assert service.apply_prepared(plan.plan_id, 'mismatched-native').kind == 'unknown'
    assert len(calls) == 1
