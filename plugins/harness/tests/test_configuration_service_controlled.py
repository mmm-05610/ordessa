"""C4 slice against the actual product carrier and a controlled native readback."""
from __future__ import annotations

import hashlib
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Event
import pytest

from ordessa_harness_api import (
    AdapterContext, ApplicationTarget, Assessment, ConfigurationAdapterDescriptor,
    DesiredFragment, FieldClaim, FieldPath, Installation, IntentSet, IntentSource,
    SetField, TargetDescriptor, TargetHandle, ValueSchema, VerificationUnknown,
    VersionRange,
)
from ordessa_harness.application import (
    ConfigurationApplicationService, FenceObservation, NativeActivationReceipt,
    NativeReadback, OperationJournal,
    RuntimeSnapshot,
)
from ordessa_harness.contributions import CONFIGURATION_POINT
from ordessa_harness.materialization import MergeAuthority, TargetAuthority
from ordessa_server.bootstrap import build_runtime
from server_plugin_api import (AbsentContribution, Contribution, ContributionBatch, ContributionOwnerBusyError,
                               ServerPluginDescriptor, ServerPluginRegistration)


FIXTURE = Path(__file__).parent / "fixtures" / "external_adapter" / "src" / "ordessa_test_external_adapter" / "__init__.py"
TARGET = ApplicationTarget("test-server", "test-session", "test-channel", 7)
HANDLE = TargetHandle("external-config", 7)
RESOURCE = ("private", "settings.json")


def external_plugin():
    installed = os.environ.get("ORDESSA_T05_EXTERNAL_DIST_ROOT")
    package_file = (Path(installed) / "ordessa_test_external_adapter" / "__init__.py") if installed else FIXTURE
    spec = importlib.util.spec_from_file_location("ordessa_test_external_adapter", package_file)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ReadbackExternalAdapterPlugin()


class ControlledRuntime:
    def __init__(self, root):
        self.root = root
        self.root.mkdir()
        self.root.chmod(0o700)
        self.activate_count = 0
        self.fail_after_effect = False
        self.corrupt_readback = False
        self.bytes = None
        self.revision = "base-1"
        self.snapshot_files = {}
        self.native_version = (1, 0, 0)
        self.capture_error = None
        self.receipt = None
        self.receipt_override = None
        self.last_readback_ref = None

    def capture(self, target):
        if self.capture_error is not None:
            raise self.capture_error
        descriptor = TargetDescriptor(HANDLE, "file", "json", "instance", (("model",),))
        context = AdapterContext((descriptor,), Installation("test-external", self.native_version,
                                 (1, 0, 0), "fixture:installed"), "acp", "instance", "fixture:capability")
        return RuntimeSnapshot(target, context,
            MergeAuthority((TargetAuthority(descriptor, RESOURCE),)), self.snapshot_files, {}, self.root,
            {}, self.revision, "native-version-1", 1, "auth-1", "secret-ref-1")

    def activate_generation(self, operation_id, target, lease, manifest_digest):
        self.activate_count += 1
        self.bytes = lease.read_bytes(RESOURCE)  # actual fd-bound generation bytes
        self.revision = "applied-1"
        if self.fail_after_effect:
            raise OSError("controlled endpoint lost acknowledgement after effect")
        self.receipt = NativeActivationReceipt(operation_id, target, manifest_digest,
            "native-session-1", self.revision, f"fixture:native-owner:{operation_id}")
        return self.receipt_override or self.receipt

    def observe(self, target):
        assert self.bytes is not None
        data = b'{"model":"other"}' if self.corrupt_readback else self.bytes
        self.last_readback_ref = "fixture:readback:" + hashlib.sha256(data).hexdigest()
        return NativeReadback(target, "native-session-1", self.revision,
                              json.loads(data), ((RESOURCE, hashlib.sha256(data).hexdigest()),),
                              self.last_readback_ref,
                              ("private-generation",), self.receipt)


class Permit:
    def __init__(self):
        self.allowed = True
        self.calls = 0

    def verify(self, principal, target, plan, operation_key, permit):
        self.calls += 1
        return self.allowed and principal == "alice" and target == TARGET and permit == "signed:fixture"


def fragment(value="fixture-model"):
    return DesiredFragment("model", "fixture-selection", "v1", "business:fixture",
                           "source-1", "set", {"model": value})


def test_c4_binds_compiled_source_to_trusted_fragment_item_id(tmp_path):
    product, host, runtime, permit, journal, service = setup(tmp_path)
    try:
        chosen = replace(fragment(), item_id="policy-choice-1")
        planned = service.plan(TARGET, (chosen,), "base-1")
        assert planned.kind == "plan"
        assert runtime.activate_count == 0 and permit.calls == 0
        assert service._prepared[planned.plan_id].merged.intents[0].item_id == "policy-choice-1"
    finally:
        product.stop()


def test_c4_source_rebinding_rejects_cross_item_facet_version_and_claim(tmp_path):
    product, host, runtime, permit, journal, service = setup(tmp_path)
    try:
        with use_external_configuration(host) as view:
            adapter = view.payload
            original_compile = adapter.compile
            for source in (IntentSource("other", "placeholder", "v1"),
                           IntentSource("model", "placeholder", "v2")):
                adapter.compile = lambda *_args, source=source: IntentSet((
                    SetField(source, HANDLE, FieldPath(("model",)), "x"),))
                result = service.plan(TARGET, (replace(fragment(), item_id="chosen"),), "base-1")
                assert result.kind == "refused" and result.code.value == "invalid-fragment"
            adapter.compile = lambda *_args: IntentSet((
                SetField(IntentSource("model", "placeholder", "v1"), HANDLE,
                         FieldPath(("unclaimed",)), "x"),))
            result = service.plan(TARGET, (replace(fragment(), item_id="chosen"),), "base-1")
            assert result.kind == "refused" and result.code.value == "invalid-fragment"
            adapter.compile = lambda *_args: IntentSet((
                SetField(IntentSource("model", "placeholder", "v1"),
                         TargetHandle("other-target", 7), FieldPath(("model",)), "x"),))
            result = service.plan(TARGET, (replace(fragment(), item_id="chosen"),), "base-1")
            assert result.kind == "refused" and result.code.value == "invalid-fragment"
            adapter.compile = original_compile
            pair = (fragment(), replace(fragment(), item_id="policy-choice-1"))
            result = service.plan(TARGET, pair, "base-1")
            assert result.kind == "refused" and "aliases another authorized item" in result.diagnostics[0]
        assert permit.calls == 0 and runtime.activate_count == 0
    finally:
        product.stop()


def test_c4_two_facets_compile_under_distinct_exact_owner_leases(tmp_path):
    product, host, runtime, permit, journal, service = setup(tmp_path)
    second_target = TargetDescriptor(TargetHandle("external-theme", 7), "file", "json",
                                     "instance", (("theme",),))

    class ThemeAdapter:
        descriptor = ConfigurationAdapterDescriptor(
            "test.external.theme", "v1", "theme", "v1", "test-external",
            VersionRange((1, 0, 0)), VersionRange((1, 0, 0)), ("acp",),
            ValueSchema("object", properties=(("theme", ValueSchema("string")),),
                        required=("theme",)),
            (FieldClaim("file", "external-theme", ("theme",)),))

        def assess(self, _context, _request):
            return Assessment("supported", evidence_ref="controlled:theme")

        def compile(self, _context, _before, desired):
            with pytest.raises(ContributionOwnerBusyError):
                host.deactivate("test.external-adapter")
            with pytest.raises(ContributionOwnerBusyError):
                host.deactivate("test.theme")
            return IntentSet((SetField(IntentSource("theme", "adapter-placeholder", "v1"),
                                       second_target.handle, FieldPath(("theme",)),
                                       desired["theme"]),))

        def verify(self, _context, _observed):
            return VerificationUnknown("no native readback")

    class ThemePlugin:
        def descriptor(self):
            return ServerPluginDescriptor("test.theme", "Controlled theme", "1")

        def build(self, _context):
            return ServerPluginRegistration(contributions=ContributionBatch((
                Contribution(CONFIGURATION_POINT, "v1", ThemeAdapter()),)))

    original_capture = runtime.capture
    def capture(target):
        snapshot = original_capture(target)
        return replace(snapshot,
            context=replace(snapshot.context, targets=snapshot.context.targets + (second_target,)),
            authority=MergeAuthority(snapshot.authority.targets +
                (TargetAuthority(second_target, ("private", "theme.json")),)))

    runtime.capture = capture
    try:
        host.activate(ThemePlugin())
        theme = DesiredFragment("theme", "theme-choice", "v1", "controlled:theme",
                                "source-2", "set", {"theme": "dark"})
        planned = service.plan(TARGET, (fragment(), theme), "base-1")
        assert planned.kind == "plan"
        merged = service._prepared[planned.plan_id].merged
        assert {(intent.owner, intent.facet_id, intent.item_id)
                for intent in merged.intents} == {
            ("test.external-adapter", "model", "fixture-selection"),
            ("test.theme", "theme", "theme-choice")}
        assert permit.calls == 0 and runtime.activate_count == 0
        result = service.apply(planned.plan_id, "two-facets", "signed:fixture")
        assert result.kind == "unknown"  # theme has no native verification oracle
        assert runtime.activate_count == 1 and permit.calls == 1
        assert service.query("two-facets").result == result
        assert not host.owner_busy("test.theme")
        host.deactivate("test.theme")
    finally:
        product.stop()


def test_c4_ambiguous_enumeration_cannot_pick_first_adapter(tmp_path):
    product, host, runtime, permit, journal, service = setup(tmp_path)

    class DuplicateCarrier:
        def contributions(self, point_id):
            views = host.contributions(point_id)
            external = next(view for view in views if view.owner == "test.external-adapter")
            return views + (external,)

        def use_contribution_exact(self, *args, **kwargs):
            return host.use_contribution_exact(*args, **kwargs)

    try:
        service.carrier = DuplicateCarrier()
        capabilities = service.inspect(TARGET)
        assert capabilities.capabilities
        assert all(item.status == "unknown" for item in capabilities.capabilities)
        result = service.plan(TARGET, (fragment(),), "base-1")
        assert result.kind == "refused" and result.code.value == "target-conflict"
        assert permit.calls == 0 and runtime.activate_count == 0
    finally:
        product.stop()


def test_c4_enumerated_publication_without_exact_lease_refuses(tmp_path):
    product, host, runtime, permit, journal, service = setup(tmp_path)

    class LostLeaseCarrier:
        def contributions(self, point_id):
            return host.contributions(point_id)

        @contextmanager
        def use_contribution_exact(self, point_id, *, owner, publication_token, consumer=None):
            yield AbsentContribution(point_id, "publication retired before hold")

    try:
        service.carrier = LostLeaseCarrier()
        assert all(item.status == "unknown" for item in service.inspect(TARGET).capabilities)
        result = service.plan(TARGET, (fragment(),), "base-1")
        assert result.kind == "refused" and result.code.value == "adapter-missing"
        assert permit.calls == 0 and runtime.activate_count == 0
    finally:
        product.stop()


def setup(tmp_path, plugin=None):
    product = build_runtime(tmp_path / "product")
    host = product.plugin_host
    host.activate(plugin if plugin is not None else external_plugin())
    runtime = ControlledRuntime(tmp_path / "generations")
    permit = Permit()
    journal = OperationJournal(tmp_path / "operations.sqlite")
    service = ConfigurationApplicationService(principal="alice", target=TARGET,
        carrier=host, runtime=runtime, permits=permit, journal=journal)
    return product, host, runtime, permit, journal, service


@contextmanager
def use_external_configuration(host):
    matches = [view for view in host.contributions(CONFIGURATION_POINT)
               if view.owner == "test.external-adapter"]
    assert len(matches) == 1
    view = matches[0]
    with host.use_contribution_exact(CONFIGURATION_POINT, owner=view.owner,
                                     publication_token=view.publication_token) as held:
        yield held


class EmptyTokenCarrier:
    def __init__(self, host):
        self.host = host

    def contributions(self, point_id):
        return tuple(replace(view, publication_token="")
                     for view in self.host.contributions(point_id))

    @contextmanager
    def use_contribution_exact(self, point_id, *, owner, publication_token, consumer=None):
        with self.host.use_contribution_exact(point_id, owner=owner,
                                              publication_token=publication_token,
                                              consumer=consumer) as view:
            yield replace(view, publication_token="")


def test_external_adapter_c4_controlled_apply_requires_actual_readback(tmp_path):
    product, host, runtime, permit, journal, service = setup(tmp_path)
    try:
        capabilities = service.inspect(TARGET)
        assert {item.operation for item in capabilities.capabilities} == {"set", "reset"}
        assert {item.operation: item.status for item in capabilities.capabilities} == {
            "set": "supported", "reset": "unknown"}
        planned = service.plan(TARGET, (fragment(),), "base-1")
        assert planned.kind == "plan" and runtime.activate_count == 0
        assert list(runtime.root.iterdir()) == []
        confirmed = service.apply(planned.plan_id, "submission-1", "signed:fixture")
        assert confirmed.kind == "confirmed" and confirmed.native_session_identity == "native-session-1"
        assert confirmed.verification_evidence_ref == runtime.last_readback_ref
        assert confirmed.verification_evidence_ref != runtime.receipt.evidence_ref
        with sqlite3.connect(journal.path) as db:
            assert db.execute("SELECT receipt_json FROM native_evidence WHERE operation_id=?",
                              (confirmed.operation_id,)).fetchone()[0] is not None
            assert db.execute("SELECT readback_evidence_ref FROM native_verifications WHERE operation_id=?",
                              (confirmed.operation_id,)).fetchone()[0] == runtime.last_readback_ref
        assert runtime.activate_count == 1 and service.query("submission-1").result == confirmed
        assert service.apply(planned.plan_id, "submission-1", "signed:fixture") == confirmed
        assert runtime.activate_count == 1  # changed before revision cannot replay native effect
        assert len([path for path in runtime.root.iterdir() if path.name.startswith("gen-")]) == 1
    finally:
        product.stop()


def test_published_adapter_mutation_cannot_expand_admitted_claims_or_change_c4_identity(tmp_path):
    product, host, runtime, permit, journal, service = setup(tmp_path)
    try:
        with use_external_configuration(host) as view:
            adapter = view.payload
            admitted = adapter.descriptor
            assert admitted.facet_id == "model"
            object.__setattr__(admitted, "facet_id", "other")
            object.__setattr__(admitted, "claims", (FieldClaim("file", "external-config", ("other",)),))
            adapter.descriptor = replace(admitted, facet_id="other",
                claims=(FieldClaim("file", "external-config", ("other",)),))
            rogue = SetField(IntentSource("model", "fixture-selection", "v1"),
                HANDLE, FieldPath(("other",)), "unexpected")
            original_compile = adapter.compile
            adapter.compile = lambda *_args: IntentSet((rogue,))
            try:
                with pytest.raises(ValueError, match="registered claims"):
                    service._compile(runtime.capture(TARGET), (fragment(),), adapter, view.owner)
            finally:
                adapter.compile = original_compile
        capabilities = service.inspect(TARGET)
        assert {item.facet_id for item in capabilities.capabilities} == {"model"}
        planned = service.plan(TARGET, (fragment(),), "base-1")
        assert planned.kind == "plan"
        assert runtime.activate_count == 0
    finally:
        product.stop()


def test_one_use_permit_is_not_spent_on_same_key_replay_or_deterministic_refusal(tmp_path):
    product, host, runtime, permit, journal, service = setup(tmp_path)
    try:
        planned = service.plan(TARGET, (fragment(),), "base-1")
        runtime.snapshot_files = {RESOURCE: b"not-json"}
        refused = service.apply(planned.plan_id, "one", "signed:fixture")
        assert refused.kind == "refused" and permit.calls == 0
        assert service.query("one").kind == "not-found"

        runtime.snapshot_files = {}
        original_verify = permit.verify
        def verify_once(*args):
            return permit.calls == 0 and original_verify(*args)
        permit.verify = verify_once
        confirmed = service.apply(planned.plan_id, "one", "signed:fixture")
        assert confirmed.kind == "confirmed" and permit.calls == 1
        assert service.apply(planned.plan_id, "one", "already-spent") == confirmed
        assert permit.calls == 1 and runtime.activate_count == 1

        different = service.plan(TARGET, (fragment("different-model"),), "applied-1")
        conflict = service.apply(different.plan_id, "one", "already-spent")
        assert conflict.kind == "refused" and conflict.code.value == "target-conflict"
        assert permit.calls == 1 and runtime.activate_count == 1
    finally:
        product.stop()


def test_concurrent_same_key_replay_does_not_verify_twice(tmp_path):
    product, host, runtime, permit, journal, service = setup(tmp_path)
    entered = Event()
    release = Event()
    original_verify = permit.verify
    def verify_once(*args):
        if permit.calls:
            return False
        allowed = original_verify(*args)
        entered.set()
        assert release.wait(5), "controlled verifier was never released"
        return allowed
    permit.verify = verify_once
    try:
        planned = service.plan(TARGET, (fragment(),), "base-1")
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(service.apply, planned.plan_id, "same", "signed:fixture")
            assert entered.wait(5), "first apply did not reach the verifier"
            second = pool.submit(service.apply, planned.plan_id, "same", "signed:fixture")
            release.set()
            assert second.result(timeout=5) == first.result(timeout=5)
        assert permit.calls == 1 and runtime.activate_count == 1
    finally:
        release.set()
        product.stop()


def test_missing_permit_and_plugin_unload_refuse_before_native_effect(tmp_path):
    product, host, runtime, permit, journal, service = setup(tmp_path)
    try:
        planned = service.plan(TARGET, (fragment(),), "base-1")
        assert service.apply(planned.plan_id, "one", "missing").kind == "refused"
        assert runtime.activate_count == 0 and list(runtime.root.iterdir()) == []
        host.deactivate("test.external-adapter")
        assert service.apply(planned.plan_id, "one", "signed:fixture").kind == "refused"
        assert runtime.activate_count == 0 and list(runtime.root.iterdir()) == []
    finally:
        product.stop()


def test_external_effect_failure_and_mismatched_readback_remain_unknown_without_replay(tmp_path):
    product, host, runtime, permit, journal, service = setup(tmp_path)
    try:
        planned = service.plan(TARGET, (fragment(),), "base-1")
        runtime.fail_after_effect = True
        unknown = service.apply(planned.plan_id, "one", "signed:fixture")
        assert unknown.kind == "unknown" and runtime.activate_count == 1
        assert service.query("one").result == unknown
        assert service.reconcile("one") == unknown
        assert service.apply(planned.plan_id, "one", "signed:fixture") == unknown
        assert runtime.activate_count == 1
        assert service.apply(planned.plan_id, "two", "signed:fixture").kind == "refused"
    finally:
        product.stop()


def test_native_readback_mismatch_cannot_confirm(tmp_path):
    product, host, runtime, permit, journal, service = setup(tmp_path)
    try:
        planned = service.plan(TARGET, (fragment(),), "base-1")
        runtime.corrupt_readback = True
        unknown = service.apply(planned.plan_id, "one", "signed:fixture")
        assert unknown.kind == "unknown" and runtime.activate_count == 1
        assert unknown.observed_effects == (f"native-receipt:fixture:native-owner:{unknown.operation_id}",)
        assert service.query("one").result == unknown
        assert OperationJournal(journal.path).query("alice", TARGET, "one").result == unknown
        assert service.apply(planned.plan_id, "one", "signed:fixture") == unknown
        assert runtime.activate_count == 1
    finally:
        product.stop()


def test_matching_preexisting_readback_without_native_activation_is_unknown(tmp_path):
    product, host, runtime, permit, journal, service = setup(tmp_path)
    try:
        planned = service.plan(TARGET, (fragment(),), "base-1")
        def no_activation(operation_id, target, lease, manifest_digest):
            # The observer can already see matching bytes, but the native owner
            # never acknowledged this operation or activated this generation.
            runtime.bytes = lease.read_bytes(RESOURCE)
            runtime.revision = "applied-1"
        runtime.activate_generation = no_activation
        result = service.apply(planned.plan_id, "one", "signed:fixture")
        assert result.kind == "unknown" and runtime.activate_count == 0
        assert service.query("one").result.kind == "unknown"
    finally:
        product.stop()


@pytest.mark.parametrize("wrong", ["operation", "target", "generation", "manifest"])
def test_wrong_native_owner_receipt_cannot_confirm(tmp_path, wrong):
    product, host, runtime, permit, journal, service = setup(tmp_path)
    try:
        planned = service.plan(TARGET, (fragment(),), "base-1")
        original = runtime.activate_generation
        def wrong_receipt(operation_id, target, lease, manifest_digest):
            receipt = original(operation_id, target, lease, manifest_digest)
            bad_target = (replace(target, server_id="other-server") if wrong == "target" else
                          replace(target, runtime_generation=target.runtime_generation + 1)
                          if wrong == "generation" else target)
            return replace(receipt,
                operation_id="op-wrong" if wrong == "operation" else receipt.operation_id,
                target=bad_target,
                manifest_digest="0" * 64 if wrong == "manifest" else receipt.manifest_digest)
        runtime.activate_generation = wrong_receipt
        result = service.apply(planned.plan_id, "one", "signed:fixture")
        assert result.kind == "unknown" and runtime.activate_count == 1
        assert service.query("one").result.kind == "unknown"
    finally:
        product.stop()


def test_reopened_old_reservation_without_native_receipt_remains_unknown(tmp_path):
    product, host, runtime, permit, journal, service = setup(tmp_path)
    try:
        planned = service.plan(TARGET, (fragment(),), "base-1")
        old = journal.reserve("alice", planned.plan_id, "one",
            FenceObservation.from_plan(planned), now=datetime.now(timezone.utc))
        assert old.result.kind == "unknown"
        reopened = ConfigurationApplicationService(principal="alice", target=TARGET,
            carrier=host, runtime=runtime, permits=permit, journal=OperationJournal(journal.path))
        assert reopened.query("one").result.kind == "unknown"
        assert reopened.reconcile("one").kind == "unknown"
        assert runtime.activate_count == 0
    finally:
        product.stop()


def test_external_success_then_journal_failure_remains_queryable_unknown_after_restart(tmp_path, monkeypatch):
    product, host, runtime, permit, journal, service = setup(tmp_path)
    try:
        planned = service.plan(TARGET, (fragment(),), "base-1")
        original = journal._persist_result

        def fail_after_write(*args):
            original(*args)
            raise OSError("controlled journal failure")

        monkeypatch.setattr(journal, "_persist_result", fail_after_write)
        unknown = service.apply(planned.plan_id, "one", "signed:fixture")
        assert unknown.kind == "unknown" and runtime.activate_count == 1
        reopened = ConfigurationApplicationService(principal="alice", target=TARGET, carrier=host,
            runtime=runtime, permits=permit, journal=OperationJournal(journal.path))
        persisted = reopened.query("one")
        assert persisted.result.kind == "unknown" and persisted.result.phase in {"applying", "verifying"}
        assert reopened.reconcile("one") == persisted.result
        assert reopened.apply(planned.plan_id, "one", "signed:fixture").kind == "refused"
        assert runtime.activate_count == 1
    finally:
        product.stop()


def test_stale_fence_and_bad_fragment_refuse_before_native_effect(tmp_path):
    product, host, runtime, permit, journal, service = setup(tmp_path)
    try:
        assert service.plan(TARGET, (), "base-1").kind == "refused"
        assert service.plan(TARGET, (fragment(),), "wrong").kind == "refused"
        assert service.plan(TARGET, (fragment(7),), "base-1").kind == "refused"
        planned = service.plan(TARGET, (fragment(),), "base-1")
        runtime.revision = "changed-outside"
        assert service.apply(planned.plan_id, "one", "signed:fixture").kind == "refused"
        assert runtime.activate_count == 0 and list(runtime.root.iterdir()) == []
    finally:
        product.stop()


def test_republished_same_owner_adapter_invalidates_old_plan(tmp_path):
    same_plugin = external_plugin()
    product, host, runtime, permit, journal, service = setup(tmp_path, same_plugin)
    try:
        planned = service.plan(TARGET, (fragment(),), "base-1")
        assert planned.kind == "plan"
        host.deactivate("test.external-adapter")
        host.activate(same_plugin)  # even reusing the identical payload must change publication
        result = service.apply(planned.plan_id, "one", "signed:fixture")
        assert result.kind == "refused" and result.code.value == "adapter-missing"
        assert runtime.activate_count == 0 and list(runtime.root.iterdir()) == []
    finally:
        product.stop()


def test_deterministic_materialization_refused_before_reservation(tmp_path):
    product, host, runtime, permit, journal, service = setup(tmp_path)
    try:
        planned = service.plan(TARGET, (fragment(),), "base-1")
        runtime.snapshot_files = {RESOURCE: b"not-json"}
        result = service.apply(planned.plan_id, "one", "signed:fixture")
        assert result.kind == "refused" and result.code.value == "invalid-fragment"
        assert runtime.activate_count == 0 and list(runtime.root.iterdir()) == []
        assert service.query("one").kind == "not-found"
        runtime.snapshot_files = {}
        confirmed = service.apply(planned.plan_id, "one", "signed:fixture")
        assert confirmed.kind == "confirmed" and runtime.activate_count == 1
    finally:
        product.stop()


def test_plan_rejects_invalid_materialization_snapshot_before_journal_write(tmp_path):
    product, host, runtime, permit, journal, service = setup(tmp_path)
    try:
        runtime.snapshot_files = {RESOURCE: b"not-json"}
        result = service.plan(TARGET, (fragment(),), "base-1")
        assert result.kind == "refused" and result.code.value == "invalid-fragment"
        assert service._prepared == {}
        with sqlite3.connect(journal.path) as db:
            assert db.execute("SELECT COUNT(*) FROM plans").fetchone()[0] == 0
        assert runtime.activate_count == 0 and list(runtime.root.iterdir()) == []
        runtime.snapshot_files = {}
        assert service.plan(TARGET, (fragment(),), "base-1").kind == "plan"
    finally:
        product.stop()


def test_empty_publication_identity_cannot_bind_or_apply_plan(tmp_path):
    product, host, runtime, permit, journal, service = setup(tmp_path)
    try:
        service.carrier = EmptyTokenCarrier(host)
        result = service.plan(TARGET, (fragment(),), "base-1")
        assert result.kind == "refused" and result.code.value == "adapter-missing"
        with sqlite3.connect(journal.path) as db:
            assert db.execute("SELECT COUNT(*) FROM plans").fetchone()[0] == 0
        service.carrier = host
        planned = service.plan(TARGET, (fragment(),), "base-1")
        service.carrier = EmptyTokenCarrier(host)
        result = service.apply(planned.plan_id, "one", "signed:fixture")
        assert result.kind == "refused" and result.code.value == "adapter-missing"
        assert service.query("one").kind == "not-found" and runtime.activate_count == 0
    finally:
        product.stop()


def test_version_and_capture_errors_are_typed_plan_refusals(tmp_path):
    product, host, runtime, permit, journal, service = setup(tmp_path)
    try:
        runtime.native_version = None
        result = service.plan(TARGET, (fragment(),), "base-1")
        assert result.kind == "refused" and result.code.value == "version-unverified"
        runtime.native_version = (0, 1, 0)
        result = service.plan(TARGET, (fragment(),), "base-1")
        assert result.kind == "refused" and result.code.value == "capability-unsupported"
        runtime.native_version = (1, 0, 0)
        runtime.capture_error = OSError("controlled capture unavailable")
        result = service.plan(TARGET, (fragment(),), "base-1")
        assert result.kind == "refused" and result.code.value == "version-unverified"
        assert runtime.activate_count == 0
    finally:
        product.stop()
