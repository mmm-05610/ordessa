"""Product seam mapping/revision guards; controlled carrier, no native claims."""
from types import SimpleNamespace
from dataclasses import replace
import pytest
from ordessa_profile.contracts import (ConfigIntent, PlanResult, SessionRef, UNSET,
    PlannedItem, ApplyUnknown, ApplyRejected, ReconcileOutcome)
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
                                 resolver_factory=Resolver, supported_harnesses=('pi',))
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


@pytest.mark.parametrize('brands', [(), ['pi'], ('pi', 'pi'), ('',), (' route ',), (True,)])
def test_application_route_declarations_are_closed_and_cannot_be_guessed(rig, brands):
    _, _, _, _, _, sessions = rig
    with pytest.raises(ValueError, match='Explicit supported'):
        NativeProfileConfigPort(sessions, service_factory=lambda _: None,
                                resolver_factory=lambda: None, supported_harnesses=brands)


def test_neutral_integration_accepts_an_explicit_new_harness_without_implementing_it(rig):
    _, ref, _, _, _, sessions = rig
    ref = replace(ref, harness_id='extension-owned-harness')
    calls = []
    port = NativeProfileConfigPort(sessions,
        service_factory=lambda target: (calls.append(target) or object(), object()),
        resolver_factory=lambda: None, supported_harnesses=(ref.harness_id,))
    assert port.inspect(ref) == ref and len(calls) == 1


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


@pytest.fixture
def transition_rig(rig):
    from unittest.mock import Mock
    port, ref, intent, revisions, calls, sessions = rig
    original = port._port(ref)
    original.plan = lambda ref, desired, key: PlanResult(ref, key, 'blocked', items=(
        PlannedItem('assets.model-provider', 'choice', 'set', 'blocked',
                    'capability-unsupported: native construction route differs'),))
    native_plan = SimpleNamespace(operation_id='restore:controlled', input_digest='controlled-digest')
    restoration = Mock()
    restoration.prepare.return_value = native_plan
    restoration.attempted.return_value = False
    old_target = sessions.resolve(ref).snapshot.target
    result = SimpleNamespace(previous_target=old_target, snapshot=SimpleNamespace(
        target=replace(old_target, runtime_generation=2)))
    ticket = object()
    def execute(*args, **kwargs):
        restoration.attempted.return_value = True
        return SimpleNamespace(state='observed', ticket=ticket, restored=result)
    restoration.execute.side_effect = execute
    def complete(supplied_ref, supplied_ticket):
        assert supplied_ref == ref and supplied_ticket is ticket
        sessions.resolve = lambda _: result
        return result
    sessions.complete_restoration = complete
    port.restoration_service = restoration
    port.credential_resolver = lambda ref, desired: 'synthetic-secret'
    return SimpleNamespace(port=port, ref=ref, intent=intent, calls=calls, sessions=sessions,
        restoration=restoration, native_plan=native_plan, old_target=old_target,
        revisions=revisions, original=original)


def test_restoration_handoff_uses_a_fresh_owner_plan_not_a_restore_receipt(transition_rig):
    f = transition_rig
    plan = f.port.plan(f.ref, (f.intent,), 'switch')
    assert plan.overall == 'restart-resume'
    f.restoration.execute.assert_not_called()
    assert f.port.apply(plan, (f.intent,)) == 'controlled application callback'
    assert f.port._ports[f.ref.session_uid][0] != f.old_target
    assert f.port._ports[f.ref.session_uid][1] is not f.original
    assert [entry[0] for entry in f.calls] == ['plan', 'apply']
    f.restoration.execute.assert_called_once()


def test_live_provider_handoff_refreshes_c4_without_a_new_owner_or_restoration_ticket(transition_rig):
    from unittest.mock import Mock
    f = transition_rig
    owner = object()
    snapshot = SimpleNamespace(target=f.old_target, owner=owner, native_generation='same')
    f.sessions.resolve = lambda _: SimpleNamespace(snapshot=snapshot)
    f.sessions.complete_restoration = Mock(side_effect=AssertionError('live registration cannot renew owner'))
    f.native_plan.mode = 'live-update'
    f.native_plan.before = snapshot
    f.native_plan.expected_generation = 'same'
    def execute(*args, **kwargs):
        f.restoration.attempted.return_value = True
        return SimpleNamespace(state='observed', ticket=None, restored=SimpleNamespace(snapshot=snapshot))
    f.restoration.execute.side_effect = execute
    plan = f.port.plan(f.ref, (f.intent,), 'live-switch')
    assert plan.overall == 'live-update'
    assert f.port.apply(plan, (f.intent,)) == 'controlled application callback'
    assert f.port._ports[f.ref.session_uid][0] == f.old_target
    assert f.port._ports[f.ref.session_uid][1] is not f.original
    f.sessions.complete_restoration.assert_not_called()
    assert [entry[0] for entry in f.calls] == ['plan', 'apply']


def test_unknown_restore_never_starts_configuration_application_or_repeats_restore(transition_rig):
    f = transition_rig
    f.restoration.execute.side_effect = lambda *a, **kw: SimpleNamespace(state='unknown')
    plan = f.port.plan(f.ref, (f.intent,), 'unknown-switch')
    assert isinstance(f.port.apply(plan, (f.intent,)), ApplyUnknown)
    assert isinstance(f.port.apply(plan, (f.intent,)), ApplyUnknown)
    assert f.port.reconcile(plan.operation_key, f.ref).state == 'unknown'
    f.restoration.execute.assert_called_once()
    assert not f.calls
    assert f.port._ports[f.ref.session_uid][1] is f.original


def test_whitelisted_condition_code_surfaces_through_the_seam_unknown(transition_rig):
    """The Harness service's nominal condition code becomes the journaled
    unknown reason; no digest, session id or credential value travels with it
    (N1 diagnosis whitelist)."""
    from ordessa_harness.configuration.model.restoration import ProviderRestorationOutcome
    f = transition_rig
    plan = f.port.plan(f.ref, (f.intent,), 'coded-unknown')
    f.restoration.execute.side_effect = lambda *a, **kw: ProviderRestorationOutcome(
        'unknown', None, reason='PI_AFTER_CONFIG_DIGEST_MISMATCH')
    outcome = f.port.apply(plan, (f.intent,))
    assert isinstance(outcome, ApplyUnknown) and outcome.reason == 'PI_AFTER_CONFIG_DIGEST_MISMATCH'
    f.restoration.execute.side_effect = lambda *a, **kw: ProviderRestorationOutcome('unknown', None)
    replay = f.port.apply(plan, (f.intent,))
    assert isinstance(replay, ApplyUnknown)
    assert 'controlled-digest' not in replay.reason and 'synthetic-secret' not in replay.reason


def test_proven_native_refusal_is_a_terminal_rejection_not_a_sticky_unknown(transition_rig):
    """A typed pre-effect refusal maps to the existing rejected-unchanged
    vocabulary: zero prompt permission, intent kept, and the operation is
    finished instead of wedging the session as pending-unknown."""
    from ordessa_harness.configuration.model.restoration import ProviderRestorationOutcome
    f = transition_rig
    plan = f.port.plan(f.ref, (f.intent,), 'refused-by-native')
    f.restoration.execute.side_effect = lambda *a, **kw: ProviderRestorationOutcome(
        'refused', None, reason='PI_REGISTRATION_REFUSED')
    outcome = f.port.apply(plan, (f.intent,))
    assert isinstance(outcome, ApplyRejected)
    assert outcome.reason == 'PI_REGISTRATION_REFUSED'
    # Idempotent replay and reconcile both answer from the recorded refusal.
    assert f.port.apply(plan, (f.intent,)) is outcome
    verdict = f.port.reconcile(plan.operation_key, f.ref)
    assert verdict.state == 'rejected-unchanged' and verdict.reason == 'PI_REGISTRATION_REFUSED'
    assert not f.calls


def test_changed_resources_block_before_restore(transition_rig):
    f = transition_rig
    plan = f.port.plan(f.ref, (f.intent,), 'resource-switch')
    f.revisions['configVersion'] += 1
    with pytest.raises(ProfileError, match='catalogue changed'):
        f.port.apply(plan, (f.intent,))
    f.restoration.execute.assert_not_called()
    assert not f.calls


def test_new_application_refusal_after_restore_is_not_old_configuration_preserved(transition_rig, monkeypatch):
    f = transition_rig
    plan = f.port.plan(f.ref, (f.intent,), 'refused-switch')
    original_complete = f.sessions.complete_restoration
    def complete(ref, ticket):
        result = original_complete(ref, ticket)
        original_port = f.port._port
        def get_port(ref):
            native = original_port(ref)
            native.apply = lambda *a: ApplyRejected('rejected-unchanged', 'C4 refused new state')
            return native
        monkeypatch.setattr(f.port, '_port', get_port)
        return result
    f.sessions.complete_restoration = complete
    assert isinstance(f.port.apply(plan, (f.intent,)), ApplyUnknown)
    assert f.port.reconcile(plan.operation_key, f.ref).state == 'unknown'
    f.restoration.execute.assert_called_once()


def test_missing_or_unusable_restoration_preserves_the_original_blocked_plan(transition_rig):
    f = transition_rig
    f.restoration.prepare.side_effect = ValueError('unavailable route')
    assert f.port.plan(f.ref, (f.intent,), 'unsupported').blocked
    f.restoration.execute.assert_not_called()
    f.original.plan = lambda ref, desired, key: PlanResult(ref, key, 'blocked', items=(
        PlannedItem('*', '*', '*', 'blocked', 'adapter-missing: publication absent'),))
    f.restoration.prepare.reset_mock()
    assert f.port.plan(f.ref, (f.intent,), 'missing-publication').blocked
    f.restoration.prepare.assert_not_called()


def test_native_preflight_refusal_reports_no_effect_and_is_not_retried(transition_rig):
    f = transition_rig
    f.restoration.execute.side_effect = ValueError('stale source')
    plan = f.port.plan(f.ref, (f.intent,), 'preflight-refused')
    first = f.port.apply(plan, (f.intent,))
    assert isinstance(first, ApplyRejected)
    assert f.port.apply(plan, (f.intent,)) == first
    f.restoration.execute.assert_called_once()
    assert not f.calls


def test_transition_plan_replay_cannot_replace_a_started_operation(transition_rig):
    f = transition_rig
    plan = f.port.plan(f.ref, (f.intent,), 'retained-switch')
    f.restoration.execute.side_effect = lambda *a, **kw: SimpleNamespace(state='unknown')
    f.port.apply(plan, (f.intent,))
    assert f.port.plan(f.ref, (f.intent,), 'retained-switch') is plan
    with pytest.raises(ProfileError, match='already bound'):
        f.port.plan(f.ref, (replace(f.intent, source='different'),), 'retained-switch')
    assert isinstance(f.port.apply(plan, (f.intent,)), ApplyUnknown)
    f.restoration.execute.assert_called_once()
    f.restoration.prepare.assert_called_once()


def test_late_restore_proof_does_not_claim_the_unapplied_profile_or_repeat_effects(transition_rig):
    f = transition_rig
    observed = f.restoration.execute.side_effect()
    f.restoration.execute.side_effect = lambda *a, **kw: SimpleNamespace(state='unknown')
    f.restoration.query.return_value = observed
    plan = f.port.plan(f.ref, (f.intent,), 'late-proof')
    assert isinstance(f.port.apply(plan, (f.intent,)), ApplyUnknown)
    assert f.port.reconcile(plan.operation_key, f.ref).state == 'unknown'
    assert f.sessions.resolve(f.ref).snapshot.target != f.old_target
    assert isinstance(f.port.apply(plan, (f.intent,)), ApplyUnknown)
    f.restoration.execute.assert_called_once()
    assert not f.calls  # readonly confirmation is not a new configuration action


def test_complete_application_proof_can_be_reconciled_without_reexecuting(transition_rig):
    from ordessa_profile.contracts import ApplyConfirmed
    f = transition_rig
    plan = f.port.plan(f.ref, (f.intent,), 'confirmed-proof')
    f.port.apply(plan, (f.intent,))
    fresh = f.port._ports[f.ref.session_uid][1]
    receipt = object()
    fresh.reconcile = lambda *a: ReconcileOutcome('confirmed-current', receipt=receipt)
    replay = f.port.apply(plan, (f.intent,))
    assert isinstance(replay, ApplyConfirmed) and replay.receipt is receipt
    f.restoration.execute.assert_called_once()
    assert [entry[0] for entry in f.calls] == ['plan', 'apply']
