"""Controlled action owner, permit and runtime; no production authorization.

The actual product carrier and durable journal exercise leases and reservation.
Synthetic owner receipts deliberately make no claim about Pi/model execution.
"""
from dataclasses import replace
import json
import sqlite3

import pytest
from ordessa_harness_api import (
    ActionDescriptor, AdapterContext, ApplicationTarget, Assessment, ConfigurationAdapterDescriptor,
    DesiredFragment, FieldClaim, FieldPath, Installation, IntentSet, IntentSource, InvokeAction,
    Match, SetField, TargetDescriptor, TargetHandle, ValueSchema, VerificationUnknown, VersionRange,
)
from ordessa_harness.application.configuration_service import ConfigurationApplicationService, NativeReadback, RuntimeSnapshot
from ordessa_harness.application.action_execution import ActionBatch, ActionGrant, ActionInvocation
from ordessa_harness.application.operation_journal import NativeActivationReceipt, OperationJournal
from ordessa_harness.contributions import CONFIGURATION_POINT
from ordessa_harness.materialization import MergeAuthority, TargetAuthority
from ordessa_server.bootstrap import build_runtime
from server_plugin_api import Contribution, ContributionBatch, ServerPluginDescriptor, ServerPluginRegistration

TARGET = ApplicationTarget("controlled-server", "canonical-session", "channel", 4)
SCHEMA = ValueSchema("object", properties=(("level", ValueSchema("string")),), required=("level",))
FILE = TargetDescriptor(TargetHandle("file", 4), "file", "json", "session", (("level",),))
ACTION = ActionDescriptor("set-thinking", "v1", SCHEMA, SCHEMA, "session", "read-back", False)
FRAGMENT = DesiredFragment("thinking", "choice", "v1", "fixture:choice", "source-1", "set", {"level": "low"})


class Adapter:
    descriptor = ConfigurationAdapterDescriptor("controlled.adapter", "v1", "thinking", "v1", "controlled",
        VersionRange((1, 0, 0)), VersionRange((1, 0, 0)), ("acp",), SCHEMA,
        (FieldClaim("file", "file", ("level",)),))
    mode = "action"
    expected = "native-thinking"
    verification = True

    def assess(self, context, request):
        return Assessment("supported", evidence_ref="fixture:capability")

    def compile(self, context, before, desired):
        source = IntentSource("thinking", "adapter-placeholder", "v1")
        action = InvokeAction(source, "set-thinking", "v1", desired, self.expected)
        file = SetField(source, FILE.handle, FieldPath(("level",)), desired["level"])
        return IntentSet((action, file) if self.mode == "mixed" else
                         ((file,) if self.mode == "file" else (action,)))

    def verify(self, context, observed):
        return Match("fixture:adapter-match") if self.verification and observed == {"level": "low"} else VerificationUnknown("fixture mismatch")


class Plugin:
    def __init__(self, adapter):
        self.adapter = adapter

    def descriptor(self):
        return ServerPluginDescriptor("controlled.owner", "Controlled", "1")

    def build(self, context):
        return ServerPluginRegistration(contributions=ContributionBatch((
            Contribution(CONFIGURATION_POINT, "v1", self.adapter),)))


class Runtime:
    def __init__(self, root):
        self.root = root
        self.authority = MergeAuthority((TargetAuthority(FILE, ("private", "settings.json")),), (ACTION,), "session")
        self.receipt = None
        self.readback_mode = "valid"
        self.reads = 0

    def capture(self, target):
        context = AdapterContext((FILE,), Installation("controlled", (1, 0, 0), (1, 0, 0), "fixture:installation"),
                                 "acp", self.authority.scope, "fixture:capability")
        return RuntimeSnapshot(target, context, self.authority, {}, {}, self.root,
                               {}, "before-1", "native-v1", 1, "auth-1", "secret-1")

    def activate_generation(self, *args):
        pytest.fail("action flow must not materialize or activate files")

    def observe(self, target):
        self.reads += 1
        receipt = self.receipt
        return NativeReadback(target, "wrong-session" if self.readback_mode == "identity" else receipt.native_session_identity,
            receipt.applied_revision, {"level": "wrong"} if self.readback_mode == "value" else {"level": "low"}, (),
            receipt.evidence_ref if self.readback_mode == "same-evidence" else "fixture:independent-readback",
            ("session-thinking",), None if self.readback_mode == "missing-receipt" else receipt)


class Permit:
    allowed = True
    calls = 0

    def verify(self, principal, target, plan, key, permit):
        self.calls += 1
        return self.allowed and permit == "fixture-permit"


class Executor:
    def __init__(self, runtime, journal):
        self.runtime, self.journal = runtime, journal
        self.effects = 0
        self.preflights = 0
        self.corrupt_receipt = False
        self.lose_after_effect = False
        self.preflight_refused = False

    def preflight(self, batch):
        self.preflights += 1
        if self.preflight_refused:
            raise RuntimeError("controlled native owner unavailable")
        assert batch.target == TARGET

    def execute(self, operation_id, batch):
        assert self.carrier.owner_busy("controlled.owner")
        with sqlite3.connect(self.journal.path) as db:
            assert db.execute("SELECT state FROM operations WHERE operation_id=?", (operation_id,)).fetchone()[0] == "applying"
            assert db.execute("SELECT manifest_digest FROM native_evidence WHERE operation_id=?", (operation_id,)).fetchone()[0] == batch.manifest_digest
        self.effects += 1
        receipt = NativeActivationReceipt(operation_id, batch.target, batch.manifest_digest,
            "fixture-native-session", "fixture-applied", "fixture:native-owner")
        self.runtime.receipt = receipt
        if self.lose_after_effect:
            raise OSError("fixture loses native response after effect")
        return replace(receipt, manifest_digest="0" * 64) if self.corrupt_receipt else receipt


@pytest.fixture
def rig(tmp_path):
    product = build_runtime(tmp_path / "product")
    adapter = Adapter()
    product.plugin_host.activate(Plugin(adapter))
    view = next(view for view in product.plugin_host.contributions(CONFIGURATION_POINT) if view.owner == "controlled.owner")
    runtime = Runtime(tmp_path / "unused-generation-root")
    journal = OperationJournal(tmp_path / "journal.sqlite")
    executor = Executor(runtime, journal)
    executor.carrier = product.plugin_host
    permit = Permit()
    grant = ActionGrant(TARGET, view.owner, view.publication_token, "thinking", "choice", "v1", "set-thinking", "v1")
    args = dict(principal="fixture-user", target=TARGET, carrier=product.plugin_host, runtime=runtime,
                permits=permit, journal=journal, action_executor=executor, action_grants=(grant,))
    service = ConfigurationApplicationService(**args)
    yield service, adapter, runtime, executor, permit, grant, args
    product.stop()


def test_action_confirmed_only_after_reserved_manifest_receipt_independent_readback_and_match(rig):
    service, adapter, runtime, executor, permit, grant, args = rig
    plan = service.plan(TARGET, (FRAGMENT,), "before-1")
    assert plan.kind == "plan" and executor.effects == 0 and permit.calls == 0
    batch = service._prepared[plan.plan_id].actions
    manifest = json.loads(batch.manifest_json)
    assert manifest["target"]["session_id"] == "canonical-session"
    assert manifest["actions"][0]["source"]["item_id"] == "choice"
    assert manifest["actions"][0]["input"] == {"level": "low"}
    assert manifest["actions"][0]["expectedObservation"] == "native-thinking"
    result = service.apply(plan.plan_id, "operation", "fixture-permit")
    assert result.kind == "confirmed" and executor.effects == 1 and runtime.reads == 1
    assert not runtime.root.exists()
    assert service.apply(plan.plan_id, "operation", "fixture-permit") == result
    assert executor.effects == 1 and permit.calls == 1
    restarted = ConfigurationApplicationService(**{**args, "journal": OperationJournal(args["journal"].path)})
    assert restarted.query("operation").result == result
    assert restarted.reconcile("operation") == result
    # Controlled transfer of the same prepared plan exercises another service's
    # durable replay branch; this is not a production plan-recovery API.
    restarted._prepared = dict(service._prepared)
    assert restarted.apply(plan.plan_id, "operation", "fixture-permit") == result
    assert executor.effects == 1


@pytest.mark.parametrize("change", ["executor", "grants", "target", "owner", "token", "facet", "item", "contribution", "action", "schema"])
def test_no_default_action_or_nonexact_grant_cannot_plan(rig, change):
    service, adapter, runtime, executor, permit, grant, args = rig
    if change == "executor":
        service.action_executor = None
    elif change == "grants":
        service.action_grants = ()
    else:
        field = {"target": "target", "owner": "publication_owner", "token": "publication_token", "facet": "facet_id",
                 "item": "item_id", "contribution": "contribution_version", "action": "action_id", "schema": "schema_version"}[change]
        value = replace(TARGET, channel_id="foreign") if change == "target" else "wrong"
        service.action_grants = (replace(grant, **{field: value}),)
    assert service.plan(TARGET, (FRAGMENT,), "before-1").kind == "refused"
    assert executor.effects == 0 and permit.calls == 0


def test_original_constructor_without_optional_dependencies_still_refuses_actions(rig):
    service, adapter, runtime, executor, permit, grant, args = rig
    default = ConfigurationApplicationService(**{
        key: value for key, value in args.items() if key not in {"action_executor", "action_grants"}})
    assert default.plan(TARGET, (FRAGMENT,), "before-1").kind == "refused"
    assert executor.effects == 0 and permit.calls == 0


@pytest.mark.parametrize("change", ["scope", "confirmation", "mixed"])
def test_wrong_scope_ack_confirmation_and_mixed_batch_refused(rig, change):
    service, adapter, runtime, executor, permit, grant, args = rig
    if change == "scope":
        runtime.authority = MergeAuthority((), (replace(ACTION, scope="instance"),), "instance")
    elif change == "confirmation":
        runtime.authority = replace(runtime.authority, actions=(replace(ACTION, confirmation="protocol-ack"),))
    else:
        adapter.mode = "mixed"
    assert service.plan(TARGET, (FRAGMENT,), "before-1").kind == "refused"
    assert executor.effects == 0 and permit.calls == 0


def test_no_permit_no_effect(rig):
    service, adapter, runtime, executor, permit, grant, args = rig
    plan = service.plan(TARGET, (FRAGMENT,), "before-1")
    assert service.apply(plan.plan_id, "op", "").kind == "refused"
    assert executor.effects == 0 and runtime.reads == 0


def test_preflight_failure_and_revoked_permit_are_zero_effect_refusals(rig):
    service, adapter, runtime, executor, permit, grant, args = rig
    executor.preflight_refused = True
    assert service.plan(TARGET, (FRAGMENT,), "before-1").kind == "refused"
    assert permit.calls == 0
    executor.preflight_refused = False
    plan = service.plan(TARGET, (FRAGMENT,), "before-1")
    permit.allowed = False
    assert service.apply(plan.plan_id, "revoked", "fixture-permit").kind == "refused"
    assert executor.effects == 0 and runtime.reads == 0


def test_action_grant_rejects_instance_scope(rig):
    service, adapter, runtime, executor, permit, grant, args = rig
    with pytest.raises(ValueError, match="session target/scope"):
        replace(grant, scope="instance")


@pytest.mark.parametrize("field", ["target", "owner", "token", "facet", "item", "version", "action", "schema", "input", "expected"])
def test_canonical_manifest_binds_every_intent_identity_and_payload(rig, field):
    service, adapter, runtime, executor, permit, grant, args = rig
    plan = service.plan(TARGET, (FRAGMENT,), "before-1")
    batch = service._prepared[plan.plan_id].actions
    entry = batch.invocations[0]
    intent = entry.intent
    if field == "target":
        changed = replace(batch, target=replace(batch.target, runtime_generation=5))
    elif field in ("owner", "token"):
        changed = replace(batch, invocations=(replace(entry, **{
            "publication_owner" if field == "owner" else "publication_token": "changed"}),))
    else:
        if field in ("facet", "item", "version"):
            intent = replace(intent, source=replace(intent.source, **{
                {"facet": "facet_id", "item": "item_id", "version": "contribution_version"}[field]: "changed"}))
        elif field == "action": intent = replace(intent, action_id="changed")
        elif field == "schema": intent = replace(intent, schema_version="changed")
        elif field == "input": intent = replace(intent, typed_payload={"level": "high"})
        else: intent = replace(intent, expected_observation="changed")
        changed = replace(batch, invocations=(replace(entry, intent=intent),))
    assert changed.manifest_digest != batch.manifest_digest


@pytest.mark.parametrize("change", ["intent", "grant", "publication"])
def test_mutation_before_apply_refused_without_effect_or_permit(rig, change):
    service, adapter, runtime, executor, permit, grant, args = rig
    plan = service.plan(TARGET, (FRAGMENT,), "before-1")
    if change == "intent":
        adapter.expected = "changed-observation"
    elif change == "grant":
        service.action_grants = ()
    else:
        args["carrier"].deactivate("controlled.owner")
        args["carrier"].activate(Plugin(adapter))
    assert service.apply(plan.plan_id, "op", "fixture-permit").kind == "refused"
    assert executor.effects == 0 and permit.calls == 0


@pytest.mark.parametrize("mode", ["identity", "value", "same-evidence", "missing-receipt", "bad-receipt", "lost", "adapter"])
def test_uncertain_native_evidence_is_unknown_and_never_repeats_effect(rig, mode):
    service, adapter, runtime, executor, permit, grant, args = rig
    if mode == "bad-receipt": executor.corrupt_receipt = True
    elif mode == "lost": executor.lose_after_effect = True
    elif mode == "adapter": adapter.verification = False
    else: runtime.readback_mode = mode
    plan = service.plan(TARGET, (FRAGMENT,), "before-1")
    result = service.apply(plan.plan_id, "op", "fixture-permit")
    assert result.kind == "unknown" and executor.effects == 1
    assert service.apply(plan.plan_id, "op", "fixture-permit") == result
    restarted = ConfigurationApplicationService(**{**args, "journal": OperationJournal(args["journal"].path)})
    assert restarted.query("op").result == result
    assert restarted.reconcile("op") == result
    assert executor.effects == 1
