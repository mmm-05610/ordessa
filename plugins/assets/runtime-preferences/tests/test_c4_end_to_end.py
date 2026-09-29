"""RA-6: the C4 application chain end-to-end against the real product carrier
(``ordessa_server.bootstrap.build_runtime``) and a controlled native readback,
with the required failure counterexamples: an unsupported key returns an
explicit refusal — never silence, never a fake success.

Fixture shape follows the harness controlled slice
(``plugins/harness/tests/test_configuration_service_controlled.py``): a
ControlledRuntime that materializes generation bytes, a one-use permit, a
durable journal, and the real C2 registration of THIS plugin's eight brand
adapters.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ordessa_harness.application import (
    ConfigurationApplicationService, NativeActivationReceipt, NativeReadback,
    OperationJournal, RuntimeSnapshot,
)
from ordessa_harness.materialization import MergeAuthority, TargetAuthority
from ordessa_harness_api import (
    AdapterContext, ApplicationTarget, Installation, Match, TargetDescriptor,
    TargetHandle,
)
from ordessa_server.bootstrap import build_runtime

from ordessa_runtime_preferences import bridge, common, keys
from ordessa_runtime_preferences.plugin import RuntimePreferencesAdaptersPlugin

TARGET = ApplicationTarget("test-server", "test-session", "test-channel", 7)


def _handle(brand: str) -> str:
    return keys.BRAND_TARGETS[brand][0] or f"{brand}.fixture.json"


def _resource(brand: str) -> tuple[str, ...]:
    return ("private", _handle(brand).split(".", 1)[1])


def _allowed_fields(brand: str) -> tuple[tuple[str, ...], ...]:
    compiled = [path for group in keys.GROUPS
                for path in keys.compiled_keys(brand, group).values()]
    return tuple(tuple(path) for path in compiled)


class ControlledRuntime:
    """The controlled native side: no harness process, exact generation
    bytes, honest readback (including a corruption switch for the mismatch
    counterexample)."""

    def __init__(self, brand: str, root: Path):
        self.brand = brand
        codec = keys.BRAND_TARGETS[brand][1] or "json"
        descriptor = TargetDescriptor(
            TargetHandle(_handle(brand), 7), "file", codec, "instance",
            _allowed_fields(brand))
        self.descriptor = descriptor
        self.resource = _resource(brand)
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.root.chmod(0o700)
        self.activate_count = 0
        self.bytes = None
        self.revision = "base-1"
        self.expected: dict[str, object] = {}
        self.receipt = None

    def capture(self, target: ApplicationTarget) -> RuntimeSnapshot:
        context = AdapterContext(
            (self.descriptor,),
            Installation(self.brand, (1, 2, 3), (1, 0, 0), "fixture:installed"),
            "acp", "instance", "fixture:capability")
        return RuntimeSnapshot(target, context,
                               MergeAuthority((TargetAuthority(self.descriptor,
                                                                self.resource),)),
                               {}, {}, self.root, {}, self.revision,
                               "native-version-1", 1, "auth-1", "secret-ref-1")

    def activate_generation(self, operation_id, target, lease, manifest_digest):
        self.activate_count += 1
        self.bytes = lease.read_bytes(self.resource)
        self.revision = "applied-1"
        self.receipt = NativeActivationReceipt(operation_id, target, manifest_digest,
                                               "native-session-1", self.revision,
                                               f"fixture:native-owner:{operation_id}")
        return self.receipt

    def observe(self, target: ApplicationTarget) -> NativeReadback:
        assert self.bytes is not None
        document = json.loads(self.bytes)
        readback = _flatten(document)
        digest = hashlib.sha256(self.bytes).hexdigest()
        return NativeReadback(target, "native-session-1", self.revision,
                              {"expected": dict(self.expected),
                               "readback": readback,
                               "native_session_id": "native-session-1"},
                              ((self.resource, digest),),
                              "fixture:readback:" + digest,
                              ("private-generation",), self.receipt)


def _flatten(value, prefix=()):
    flat = {}
    for key, item in value.items():
        path = prefix + (key,)
        if isinstance(item, dict):
            flat.update(_flatten(item, path))
        else:
            flat[".".join(path)] = item
    return flat


class Permit:
    def __init__(self):
        self.calls = 0

    def verify(self, principal, target, plan, operation_key, permit):
        self.calls += 1
        return principal == "alice" and target == TARGET and permit == "signed:fixture"


def _fragment(brand: str, value: dict, item_id: str = "compaction"):
    from ordessa_harness_api import DesiredFragment
    return DesiredFragment("assets.runtime-preferences", item_id, "1",
                           f"business:{brand}-prefs", "source-1", "set", value)


def _setup(tmp_path, brand: str):
    product = build_runtime(tmp_path / "product")
    host = product.plugin_host
    host.activate(RuntimePreferencesAdaptersPlugin())
    runtime = ControlledRuntime(brand, tmp_path / "generations")
    permit = Permit()
    journal = OperationJournal(tmp_path / "operations.sqlite")
    service = ConfigurationApplicationService(
        principal="alice", target=TARGET, carrier=host, runtime=runtime,
        permits=permit, journal=journal)
    return product, host, runtime, permit, service


def test_c4_end_to_end_applies_an_opencode_compaction_preference(tmp_path):
    """The happy chain: real C2 registration → plan → permit → generation
    materialization → native readback → adapter Match → Confirmed."""
    product, host, runtime, permit, service = _setup(tmp_path, "opencode")
    try:
        capabilities = service.inspect(TARGET)
        opencode = [c for c in capabilities.capabilities if c.harness_id == "opencode"]
        assert opencode and all(item.status in ("supported", "unknown") for item in opencode)

        payload = {"compaction": {"enabled": True, "reserveTokens": 20000,
                                  "keepRecentTokens": 4000}}
        planned = service.plan(TARGET, (_fragment("opencode", payload),), "base-1")
        assert planned.kind == "plan"
        assert runtime.activate_count == 0 and permit.calls == 0

        # the controlled native side records the compiled expectation it was
        # asked to apply (what a real native owner would have been told)
        runtime.expected = _flatten(payload_mapping(payload))
        confirmed = service.apply(planned.plan_id, "op-1", "signed:fixture")
        assert confirmed.kind == "confirmed"
        assert runtime.activate_count == 1 and permit.calls == 1

        document = json.loads(runtime.bytes)
        assert document == {"compaction": {"auto": True, "reserved": 20000,
                                           "preserve_recent_tokens": 4000}}
        # the golden bytes of the materialized document are byte-stable
        assert runtime.bytes.decode() == common.render_json_object(document)
        # readback equality is exactly what the adapter confirmed
        assert bridge.BridgeConfigurationAdapter("opencode").verify(
            runtime.capture(TARGET).context,
            {"expected": _flatten(payload_mapping(payload)),
             "readback": _flatten(document),
             "native_session_id": "native-session-1"}) == Match(
            f"runtime-preferences:readback:{common.digest_label(_flatten(payload_mapping(payload)))}")
    finally:
        product.stop()


def payload_mapping(payload: dict) -> dict:
    """Flatten a payload into canonical dotted paths (the compiled expectation)."""
    mapping = {}
    for group, params in payload.items():
        native_paths = keys.compiled_keys("opencode", group)
        for name, value in params.items():
            mapping[".".join(native_paths[name])] = value
    return mapping


def test_c4_apply_refuses_an_unsupported_key_explicitly(tmp_path):
    """Failure counterexample (RA-6): codex has no domain-ownable retry key
    (provider subtree = model-provider domain). The plan refuses with
    CAPABILITY_UNSUPPORTED — no silent drop, no fake green. C4 wraps the
    adapter-level assessment in its own refusal wording, so the domain reason
    is pinned at the adapter surface, where it is authored."""
    product, host, runtime, permit, service = _setup(tmp_path, "codex")
    try:
        planned = service.plan(TARGET, (_fragment(
            "codex", {"retry": {"maxRetries": 3}}, item_id="retry"),), "base-1")
        assert planned.kind == "refused"
        assert planned.code.name == "CAPABILITY_UNSUPPORTED"
        assert planned.original_state_preserved is True
        assert runtime.activate_count == 0 and permit.calls == 0
        # the authored domain reason stays available at the adapter surface
        assessment = bridge.BridgeConfigurationAdapter("codex").assess(
            runtime.capture(TARGET).context, {"retry": {"maxRetries": 3}})
        assert assessment.status == "unsupported"
        assert "model-provider" in assessment.reason
    finally:
        product.stop()


def test_c4_apply_refuses_an_undeclared_key_not_silently_drops_it(tmp_path):
    product, host, runtime, permit, service = _setup(tmp_path, "opencode")
    try:
        planned = service.plan(TARGET, (_fragment(
            "opencode", {"compaction": {"enabled": True, "nope": 1}}),), "base-1")
        assert planned.kind == "refused"
        assert planned.code.name == "INVALID_FRAGMENT"
        assert runtime.activate_count == 0
    finally:
        product.stop()


def test_c4_apply_refuses_dsh_until_a_target_is_pinnable(tmp_path):
    """dsh's honest boundary: available cells, no pinnable write target —
    a plan refuses instead of guessing a file."""
    product, host, runtime, permit, service = _setup(tmp_path, "dsh")
    try:
        planned = service.plan(TARGET, (_fragment(
            "dsh", {"compaction": {"enabled": True}}),), "base-1")
        assert planned.kind == "refused"
        assert planned.code.name == "CAPABILITY_UNSUPPORTED"
        assert "not pinnable" in planned.diagnostics[0]
    finally:
        product.stop()


def test_c4_apply_stale_revision_is_refused(tmp_path):
    product, host, runtime, permit, service = _setup(tmp_path, "opencode")
    try:
        planned = service.plan(TARGET, (_fragment(
            "opencode", {"compaction": {"enabled": True}}),), "stale-rev")
        assert planned.kind == "refused"
        assert planned.code.name == "STALE_PLAN"
    finally:
        product.stop()


def test_reconfiguration_declaration_follows_the_catalog(tmp_path):
    """RA-6 applyMode discipline at the boundary: kilo's documented restart
    surfaces as restart-resume; opencode's undocumented modes stay unverified;
    an unavailable group is 'refused'."""
    from ordessa_runtime_preferences.bridge import reconfiguration_for
    assert reconfiguration_for("kilo", {"compaction": {"enabled": True}}) == "restart-resume"
    assert reconfiguration_for("opencode", {"compaction": {"enabled": True}}) == "unverified"
    assert reconfiguration_for("codex", {"retry": {"maxRetries": 2}}) == "refused"
