"""Controlled run probe (T013 需求4): the MCP brand adapter executed
through the REAL Harness C4 machinery.

What exists to be run harmlessly: the harness publishes
``ordessa_harness.application.ConfigurationApplicationService`` (C4 slice)
plus ``HarnessContributionRegistry`` (the very handlers the product
composition binds), and its own controlled test pattern
(plugins/harness/tests/test_configuration_service_controlled.py) — an
in-memory fake runtime, no CLI spawn, no network, HOME untouched. This file
runs the MCP adapter through that real machinery.

Two layers of proof, kept apart honestly:

* the BRAND adapter's assess answers ``unknown`` (no runtime evidence), so
  the real service refuses plan with ``capability-unsupported`` BEFORE any
  effect — the honesty path executed for real (never fake green);
* a labelling double (``ChainProbeAdapter``, assess forced to supported,
  clearly labelled as evidence of WIRING not of the brand route) drives
  assess->compile->merge->preflight->materialize->verify end to end: the
  real merge authority admits the MCP SetFields, the real permit check
  refuses without the signed permit (zero activations, nothing written),
  and the apply content-readback can only project — the service lands on
  ``Unknown``, never ``Confirmed`` — because a file-byte readback is not a
  load attestation. That is the required counterexample "mismatch/bytes
  cannot be reported as loaded" executed against the real caller.
"""
import hashlib
import json
from dataclasses import replace

import pytest
from ordessa_harness.application import (
    ConfigurationApplicationService, NativeActivationReceipt, NativeReadback,
    OperationJournal, RuntimeSnapshot,
)
from ordessa_harness.contributions import (
    CONFIGURATION_POINT, POINT_API_VERSION, HarnessContributionRegistry,
)
from ordessa_harness.materialization import MergeAuthority, TargetAuthority
from ordessa_harness_api import (
    AdapterContext, ApplicationTarget, Assessment, Installation,
    TargetDescriptor, TargetHandle,
)
from ordessa_server.plugin_host import MethodRegistry, ServerPluginHost
from wiring_helpers import AdapterContributionPlugin, claude_planned

from adapters import claude as claude_mod
from backend import native_binding as nb

TARGET = ApplicationTarget("s1", "session-a", "mcp-plan", 7)
GENERATION = 7
RESOURCE = ("mcp", "config.json")


def _handles():
    return TargetHandle(nb.instance_target_id("claude-code"), GENERATION)


def _target_descriptor():
    return TargetDescriptor(_handles(), "file", "json", "instance",
                            (("mcpServers",),))


class ControlledMcpRuntime:
    """The fake harness instance: real private generation materialization,
    zero process, zero network. Same shape as the harness's own controlled
    runtime (test_configuration_service_controlled.py)."""

    def __init__(self, root):
        self.root = root
        self.root.mkdir()
        self.root.chmod(0o700)
        self.activate_count = 0
        self.revision = "base-1"
        self.bytes = None
        self.generation = GENERATION
        self.descriptor_override = None
        self.receipt = None

    def capture(self, target):
        descriptor = self.descriptor_override or _target_descriptor()
        if descriptor.handle != _handles() and self.descriptor_override is None:
            descriptor = TargetDescriptor(TargetHandle(descriptor.handle.handle_id,
                                                       self.generation),
                                          descriptor.kind, descriptor.codec,
                                          descriptor.scope, descriptor.allowed_fields)
        context = AdapterContext(
            (descriptor,),
            Installation("claude-code", (1, 0, 0), (1, 0, 0), "ev:installed"),
            "acp", "instance", "ev:capability")
        authority = MergeAuthority(
            (TargetAuthority(descriptor, RESOURCE, array_fields=(("mcpServers",),)),),
            scope="instance")
        return RuntimeSnapshot(target, context, authority, {}, {}, self.root,
                               {}, self.revision, "native-version-1", 1,
                               "auth-1", "secret-ref-1")

    def activate_generation(self, operation_id, target, lease, manifest_digest):
        # C4 native-receipt protocol (51c7905108): the activation returns a
        # receipt binding the operation id, the planned target and the leased
        # generation's manifest digest; observe must hand the SAME receipt
        # back — a receipt that does not re-bind this operation/generation
        # makes the service refuse confirmation (pinned by
        # test_readback_with_foreign_receipt_lands_unknown below).
        self.activate_count += 1
        self.bytes = lease.read_bytes(RESOURCE)
        self.revision = "applied-1"
        self.receipt = NativeActivationReceipt(
            operation_id, target, manifest_digest, "native-session-1",
            self.revision, f"native:mcp-chain:{operation_id}")
        return self.receipt

    def observe(self, target):
        assert self.bytes is not None and self.receipt is not None
        return NativeReadback(target, "native-session-1", self.revision,
                              json.loads(self.bytes),
                              ((RESOURCE, hashlib.sha256(self.bytes).hexdigest()),),
                              "ev:readback:" + hashlib.sha256(self.bytes).hexdigest(),
                              ("private-generation",), self.receipt)


class SignedPermit:
    def __init__(self):
        self.calls = 0

    def verify(self, principal, target, plan, operation_key, permit):
        self.calls += 1
        return (principal == "alice" and target == TARGET
                and permit == "signed:mcp-permit")


class ChainProbeAdapter(claude_mod.configuration_adapter().__class__):
    """Labelling double of the claude MCP adapter for chain coverage ONLY:
    assess is forced to ``supported`` so the REAL C4 machinery (merge,
    preflight, materialize, permit, readback, verify) executes the MCP
    intents end to end. It proves the WIRING; it proves nothing about the
    claude route — the brand adapter keeps answering unknown/unsupported
    (see test_brand_honesty_blocks_the_real_plan) and ``proven_routes``
    stays empty everywhere."""

    def assess(self, context, request):
        base = super().assess(context, request)
        if base.status == "unknown":
            return Assessment("supported", evidence_ref="controlled:fake-harness-chain")
        return base


def compose(tmp_path, adapter):
    registry = HarnessContributionRegistry()
    host = ServerPluginHost(methods=MethodRegistry(), data_root=tmp_path / "host")
    host.register_contribution_point(CONFIGURATION_POINT, POINT_API_VERSION,
                                     handler=registry.configuration_handler,
                                     exclusive=False)
    host.activate(AdapterContributionPlugin("ordessa.asset.mcp", adapter))
    runtime = ControlledMcpRuntime(tmp_path / "generations")
    permits = SignedPermit()
    journal = OperationJournal(tmp_path / "operations.sqlite")
    service = ConfigurationApplicationService(
        principal="alice", target=TARGET, carrier=host, runtime=runtime,
        permits=permits, journal=journal)
    return host, runtime, permits, service


def fragment():
    planned = claude_planned()
    payload = nb.facet_payload_of(planned)
    return nb.desired_fragment(payload, source_revision=payload["snapshotDigest"],
                               business_ref=f"mcp-snapshot:{payload['snapshotDigest']}")


# -- the honesty path through the REAL service -----------------------------------


def test_brand_honesty_blocks_the_real_plan(tmp_path):
    """The brand adapter's assess is ``unknown`` -> the REAL C4 service
    refuses before compile/merge/effect. Nothing is written, nothing is
    activated — the honest cell executed end to end."""
    adapter = claude_mod.configuration_adapter()
    host, runtime, permits, service = compose(tmp_path, adapter)
    result = service.plan(TARGET, (fragment(),), "base-1")
    assert result.kind == "refused"
    assert result.code.value == "capability-unsupported"
    assert runtime.activate_count == 0
    assert list(runtime.root.iterdir()) == []
    assert permits.calls == 0


def test_probe_double_chain_plan_apply_reaches_unknown_never_confirmed(tmp_path):
    """compile->merge->preflight->plan accepted; apply without permit is
    refused with zero effect; apply WITH the signed permit materializes and
    then lands on ``Unknown`` — the content readback can only project, and
    the adapter never dresses bytes up as load, so the service's
    Confirmed-only-via-Match rule keeps the result unknown."""
    adapter = ChainProbeAdapter(claude_mod.CLAUDE, verify_fn=claude_mod.verify_native)
    host, runtime, permits, service = compose(tmp_path, adapter)
    planned = service.plan(TARGET, (fragment(),), "base-1")
    assert planned.kind == "plan", planned
    assert runtime.activate_count == 0

    # no/ bogus permit -> typed refusal, no native effect, permit unspent
    refused = service.apply(planned.plan_id, "op-1", "not-the-permit")
    assert refused.kind == "refused"
    assert refused.code.value == "authorization-refused"
    assert runtime.activate_count == 0 and permits.calls == 1

    confirmed = service.apply(planned.plan_id, "op-1", "signed:mcp-permit")
    assert confirmed.kind == "unknown"
    assert runtime.activate_count == 1
    assert list(runtime.root.iterdir())  # a generation really materialized
    # reconcile/query keep the same answer without replaying the effect
    assert service.query("op-1").result == confirmed
    assert service.reconcile("op-1") == confirmed
    again = service.apply(planned.plan_id, "op-1", "signed:mcp-permit")
    assert again == confirmed and runtime.activate_count == 1


def test_readback_mismatch_refuses_confirmation(tmp_path):
    """Corrupting the readback content (a different server set) must not
    confirm: the verify door answers Mismatch, the service records Unknown,
    and replay stays refused — '把 mismatch 报成 loaded' dies at the API
    level, not just at ours."""
    adapter = ChainProbeAdapter(claude_mod.CLAUDE, verify_fn=claude_mod.verify_native)
    host, runtime, permits, service = compose(tmp_path, adapter)

    original_observe = runtime.observe

    def corrupt(target):
        readback = original_observe(target)
        bad = json.dumps({"mcpServers": {"someone-elses-server": {}}}).encode()
        return NativeReadback(readback.target, readback.native_session_identity,
                              readback.applied_revision, json.loads(bad),
                              readback.files, readback.evidence_ref,
                              readback.resource_changes, readback.receipt)

    runtime.observe = corrupt
    planned = service.plan(TARGET, (fragment(),), "base-1")
    result = service.apply(planned.plan_id, "op-m", "signed:mcp-permit")
    assert result.kind == "unknown"
    assert runtime.activate_count == 1
    # the journal forbids a replay of a non-confirmed operation
    assert service.apply(planned.plan_id, "op-other",
                         "signed:mcp-permit").kind == "refused"


def test_readback_with_foreign_receipt_lands_unknown(tmp_path):
    """The receipt-binding wall, exercised from THIS chain, ONE dimension at a
    time: the stranger receipt differs ONLY in ``operation_id`` (target,
    manifest digest, native identity, revision and evidence ref all equal the
    genuine receipt). If the service's confirmation gate checked anything
    other than the operation binding, this cell would go Confirmed and fail —
    so the Unknown it lands on is attributable to the operation binding alone.
    """
    adapter = ChainProbeAdapter(claude_mod.CLAUDE, verify_fn=claude_mod.verify_native)
    host, runtime, permits, service = compose(tmp_path, adapter)

    original_observe = runtime.observe

    def foreign_operation_receipt(target):
        readback = original_observe(target)
        genuine = readback.receipt
        stranger = NativeActivationReceipt(
            "op-of-someone-else", genuine.target, genuine.manifest_digest,
            genuine.native_session_identity, genuine.applied_revision,
            genuine.evidence_ref)
        return NativeReadback(readback.target, readback.native_session_identity,
                              readback.applied_revision, readback.observed_value,
                              readback.files, readback.evidence_ref,
                              readback.resource_changes, stranger)

    runtime.observe = foreign_operation_receipt
    planned = service.plan(TARGET, (fragment(),), "base-1")
    result = service.apply(planned.plan_id, "op-f", "signed:mcp-permit")
    assert result.kind == "unknown"
    assert runtime.activate_count == 1


def test_revision_drift_refuses_before_effects(tmp_path):
    adapter = ChainProbeAdapter(claude_mod.CLAUDE, verify_fn=claude_mod.verify_native)
    host, runtime, permits, service = compose(tmp_path, adapter)
    wrong = service.plan(TARGET, (fragment(),), "not-the-current-revision")
    assert wrong.kind == "refused"
    assert wrong.code.value == "stale-plan"
    # drift discovered at apply time (revision moved after plan) is refused
    planned = service.plan(TARGET, (fragment(),), "base-1")
    runtime.revision = "moved-outside"
    refused = service.apply(planned.plan_id, "op-d", "signed:mcp-permit")
    assert refused.kind == "refused"
    assert runtime.activate_count == 0


def test_target_generation_swap_refuses(tmp_path):
    """跨 target/instance 冒用句柄: after the plan, the runtime's target
    handle generation changes — the old plan's intents now reference a stale
    handle; the REAL merge authority answers 'unknown or stale target
    generation' and apply refuses typed. A plan can never apply onto a
    swapped instance."""
    adapter = ChainProbeAdapter(claude_mod.CLAUDE, verify_fn=claude_mod.verify_native)
    host, runtime, permits, service = compose(tmp_path, adapter)
    planned = service.plan(TARGET, (fragment(),), "base-1")
    assert planned.kind == "plan"
    runtime.descriptor_override = TargetDescriptor(
        TargetHandle(nb.instance_target_id("claude-code"), GENERATION + 1),
        "file", "json", "instance", (("mcpServers",),))
    result = service.apply(planned.plan_id, "op-s", "signed:mcp-permit")
    assert result.kind == "refused"
    assert runtime.activate_count == 0


def test_foreign_target_handle_cannot_be_claimed(tmp_path):
    """An intent aimed at a handle the contribution never claimed (wrong
    target id) exceeds registered claims — the service refuses it before
    any materialization."""
    from ordessa_harness_api import FieldPath, IntentSet, IntentSource, SetField

    adapter = ChainProbeAdapter(claude_mod.CLAUDE, verify_fn=claude_mod.verify_native)

    def forged_compile(context, before, desired):
        return IntentSet((SetField(
            IntentSource(nb.FACET_ID, nb.FACET_ITEM_ID, nb.FACET_SCHEMA_VERSION),
            TargetHandle("someone-elses.target", 7),
            FieldPath(("mcpServers", "demo")), {"command": "/bin/true"}),))

    adapter.compile = lambda context, before, desired: forged_compile(context, before, desired)
    host, runtime, permits, service = compose(tmp_path, adapter)
    result = service.plan(TARGET, (fragment(),), "base-1")
    assert result.kind == "refused"
    assert runtime.activate_count == 0 and list(runtime.root.iterdir()) == []


# -- LaunchRequest shape (the plan->launch identity binding) ----------------------


def test_launch_request_binds_the_plan_snapshot_ref():
    request = nb.launch_request(_handles(), "plan-proof-1",
                                native_session_identity="native-session-1")
    assert request.target == _handles()
    assert request.configuration_snapshot_ref == "plan-proof-1"
    # a path is not a handle and never becomes one
    with pytest.raises(Exception):
        nb.launch_request("/runtime/home/.claude/.claude.json", "plan-1")
    # empty snapshot ref refused by the API itself
    with pytest.raises(Exception):
        nb.launch_request(_handles(), "")


def test_runtime_unknown_and_reconfiguration_views():
    from ordessa_harness_api import ReconfigurationDecision, RuntimeUnknown, Unknown

    view = nb.runtime_unknown_view(RuntimeUnknown("inst-1", ("alloc",), ("readback",)))
    assert view["kind"] == "unknown" and view["pendingChecks"] == ["readback"]
    decision = nb.reconfiguration_view(
        ReconfigurationDecision("unsupported", (), "no reload surface"))
    assert decision["mode"] == "unsupported"
    assert "no reload surface" in decision["reason"]
