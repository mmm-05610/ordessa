"""Product seam mapping/revision guards; controlled carrier, no native claims."""
from types import SimpleNamespace
from dataclasses import replace
import pytest
from ordessa_profile.contracts import ConfigIntent, PlanResult, SessionRef, UNSET
from ordessa_profile.errors import ProfileError
from ordessa_harness_api import ApplicationTarget
from ordessa_server_product.profile_configuration import NativeProfileConfigPort


@pytest.fixture
def rig(monkeypatch):
    ref = SessionRef("local", "pi", "native", "canonical")
    target = ApplicationTarget("incarnation", "canonical", "channel", 1)
    calls = []
    revisions = {"configVersion": 1}
    class Resolver:
        def resolve(self, choice, *, harness_id):
            assert choice == {"harnessId": "pi", "providerConfigId": "config", "modelId": "new"}
            assert harness_id == "pi"
            return SimpleNamespace(payload={"provider": "p", "model": "new", "protocol": "openai-chat",
                "endpoint": "https://fixture.test", "credentialRef": None}, revisions=dict(revisions))
    class Port:
        def __init__(self, service, **kwargs):
            assert kwargs["owner_application"] is True and "permit_provider" not in kwargs
        def inspect(self, target_ref):
            return target_ref
        def plan(self, target_ref, desired, operation_key):
            calls.append(("plan", desired))
            return PlanResult(target_ref, operation_key, "live-update", plan_digest="fixture")
        def apply(self, plan, desired):
            calls.append(("apply", desired))
            return "controlled application callback"
        def reconcile(self, key, ref):
            return "controlled query"
    monkeypatch.setattr("ordessa_server_product.profile_configuration.HarnessApiConfigPort", Port)
    sessions = SimpleNamespace(resolve=lambda supplied: SimpleNamespace(snapshot=SimpleNamespace(target=target)))
    sessions.require_registered = lambda supplied: sessions.resolve(supplied)
    port = NativeProfileConfigPort(sessions, service_factory=lambda _: (object(), object()),
                                 resolver_factory=Resolver)
    intent = ConfigIntent("assets.model-provider", "choice", "set", "model-provider/choice",
        "profile@1", {"harnessId": "pi", "providerConfigId": "config", "modelId": "new"})
    return port, ref, intent, revisions, calls, sessions


def test_current_business_reference_maps_without_native_hints(rig):
    port, ref, intent, _, calls, _ = rig
    plan = port.plan(ref, (intent,), "op")
    assert port.apply(plan, (intent,)) == "controlled application callback"
    assert calls[0][1] == calls[1][1]
    assert calls[0][1][0].value == {"provider": "p", "model": "new", "protocol": "openai-chat",
                                  "endpoint": "https://fixture.test", "credentialRef": None}
    assert "providerConfigId" in intent.value and "brandFields" not in calls[0][1][0].value


@pytest.mark.parametrize('brand', ['codex', 'claude-code'])
def test_explicit_brand_factory_selection_is_required_before_native_port_construction(rig, brand):
    _, ref, _, _, _, sessions = rig
    ref = replace(ref, harness_id=brand)
    calls = []
    factory = lambda target: (calls.append(target) or object(), object())
    default = NativeProfileConfigPort(sessions, service_factory=factory, resolver_factory=lambda: None)
    with pytest.raises(ProfileError, match='not yet available'):
        default.inspect(ref)
    assert not calls
    explicit = NativeProfileConfigPort(sessions, service_factory=factory, resolver_factory=lambda: None,
                                       supported_harnesses=(brand,))
    assert explicit.inspect(ref) == ref
    assert calls == [sessions.resolve(ref).snapshot.target]
    assert explicit.inspect(ref) == ref and len(calls) == 1


@pytest.mark.parametrize('brands', [(), ['pi'], ('pi', 'pi'), ('unknown',), (True,)])
def test_application_route_declarations_are_closed_and_cannot_be_guessed(rig, brands):
    _, _, _, _, _, sessions = rig
    with pytest.raises(ValueError, match='Explicit supported'):
        NativeProfileConfigPort(sessions, service_factory=lambda _: None,
                                resolver_factory=lambda: None, supported_harnesses=brands)


def test_catalogue_change_after_plan_blocks_before_application(rig):
    port, ref, intent, revisions, calls, _ = rig
    plan = port.plan(ref, (intent,), "op")
    revisions["configVersion"] = 2
    with pytest.raises(ProfileError, match="catalogue changed"):
        port.apply(plan, (intent,))
    assert len(calls) == 1


def test_changed_intent_or_foreign_plan_cannot_use_application(rig):
    port, ref, intent, _, calls, _ = rig
    plan = port.plan(ref, (intent,), "op")
    for different in (replace(intent, source="changed"), replace(intent, item_id="other")):
        with pytest.raises(ProfileError, match="Unknown or changed"):
            port.apply(plan, (different,))
    with pytest.raises(ProfileError, match="Unknown or changed"):
        port.apply(replace(plan, operation_key="foreign"), (intent,))
    assert len(calls) == 1


def test_reset_and_other_facets_do_not_silently_disappear(rig):
    port, ref, intent, _, calls, _ = rig
    for desired in ((), (intent, intent), (replace(intent, op="reset", value=UNSET),),
                    (replace(intent, facet_id="assets.skills"),)):
        with pytest.raises(ProfileError, match="requires one supported model"):
            port.plan(ref, desired, "unsupported")
    assert not calls


def test_replaced_owner_generation_does_not_reuse_cached_service(rig):
    port, ref, intent, _, calls, sessions = rig
    port.plan(ref, (intent,), "op")
    sessions.resolve = lambda _: SimpleNamespace(snapshot=SimpleNamespace(
        target=ApplicationTarget("incarnation", "canonical", "channel", 2)))
    with pytest.raises(ProfileError, match="generation changed"):
        port.inspect(ref)
    assert len(calls) == 1


def test_explicit_restoration_discards_old_plan_and_prepares_fresh_instance(rig):
    port, ref, intent, _, calls, sessions = rig
    old_plan = port.plan(ref, (intent,), 'old-plan')
    old_target = sessions.resolve(ref).snapshot.target
    new_target = replace(old_target, runtime_generation=2)
    result = SimpleNamespace(previous_target=old_target, snapshot=SimpleNamespace(target=new_target))
    ticket = object()
    def complete(supplied_ref, supplied_ticket):
        assert supplied_ref == ref and supplied_ticket is ticket
        sessions.resolve = lambda _: SimpleNamespace(snapshot=SimpleNamespace(target=new_target))
        return result
    sessions.complete_restoration = complete
    assert port.complete_restoration(ref, ticket) is result
    with pytest.raises(ProfileError, match='Unknown or changed'):
        port.apply(old_plan, (intent,))
    assert port.inspect(ref) == ref
    new_plan = port.plan(ref, (intent,), 'new-plan')
    assert port.apply(new_plan, (intent,)) == 'controlled application callback'
    assert [call[0] for call in calls] == ['plan', 'plan', 'apply']


def test_unknown_restoration_keeps_old_plan_and_never_applies_to_new_instance(rig):
    port, ref, intent, _, calls, sessions = rig
    port.plan(ref, (intent,), 'old-plan')
    old_port = port._ports[ref.session_uid]
    def complete(*args):
        raise ProfileError('SWITCH_BLOCKED', 'Restoration unknown', status=409)
    sessions.complete_restoration = complete
    with pytest.raises(ProfileError, match='unknown'):
        port.complete_restoration(ref, object())
    assert port._ports[ref.session_uid] is old_port
    assert 'old-plan' in port._plans
    assert len(calls) == 1


def test_restoration_cache_mismatch_refuses_before_mutating_product_binding(rig):
    port, ref, intent, _, _, sessions = rig
    port.plan(ref, (intent,), 'old-plan')
    cached_target, cached_port = port._ports[ref.session_uid]
    port._ports[ref.session_uid] = (replace(cached_target, runtime_generation=99), cached_port)
    completions = []
    def complete(*args):
        completions.append(args)
        pytest.fail('Mismatched cache must not mutate product session binding')
    sessions.complete_restoration = complete
    with pytest.raises(ProfileError, match='cached owner'):
        port.complete_restoration(ref, object())
    assert completions == []
    assert 'old-plan' in port._plans
