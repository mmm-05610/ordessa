"""G09-G12 through the REAL ``ConfigurationApplicationService``.

Consumption of the published harness-api checkpoint (d3f026904e, impl
61966e3118): the service behind ``HarnessApiConfigPort`` is C0's actual C4
``ConfigurationApplicationService`` over the product carrier
(``ordessa_server.bootstrap.build_runtime``) plus the controlled runtime /
permit / journal injections the checkpoint itself certifies as consumable
(its limitations: production ACP admission stays ready=False; restart
reconcile must stay Unknown without a native receipt).

These tests REPLACE the synthetic CarrierServiceDouble from
test_harness_carrier_port.py with that real service class.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from conftest import ScriptedProvider, ScriptedV2Provider, make_core
from ordessa_profile import ProfileError
from ordessa_profile.harness_port_adapter import HarnessApiConfigPort

FIXTURE = Path(__file__).resolve().parents[3] / "plugins" / "harness" / "tests" / \
    "fixtures" / "external_adapter" / "src" / "ordessa_test_external_adapter" / "__init__.py"

# The carrier fixture adapter declares facet_id="model", facet_schema_version="v1",
# payload {"model": <string>}, and authorizes item "fixture-selection"
# (its IntentSource is fixed by the fixture adapter).
FACET = "model"
ITEM = "fixture-selection"


class FixtureProvider(ScriptedV2Provider):
    """Values are payload objects matching the carrier's ValueSchema."""

    def __init__(self):
        super().__init__(
            FACET, ((ITEM, {"type": "object"}),),
            schema_version="v1",
            capability_rule="yes",
        )

    def validate(self, items, reference_facts):
        schema = self.descriptor().require_item(ITEM).value_schema
        from ordessa_profile.contracts import validate_value_against_schema
        violations = []
        for item_id, value in items.items():
            try:
                validate_value_against_schema(schema, value, where=item_id)
            except Exception as exc:  # schema refusal → violation
                from ordessa_profile.contracts import Violation
                violations.append(Violation(
                    facet_id=FACET, item_id=item_id,
                    code="FACET_VALUE_INVALID", message=str(exc)))
        return tuple(violations)

    def compile(self, resolved_items, target_facts):
        from ordessa_profile.contracts import CompileResult, ConfigIntent
        intents = []
        for item_id, value in sorted(resolved_items.items()):
            intents.append(ConfigIntent(
                facet_id=FACET, item_id=item_id, op="set",
                native_key=f"{FACET}.{item_id}",
                source=f"profile@{target_facts.get('source_revision', '')}",
                value=value,
            ))
        current_items = target_facts.get("current_items", {})
        for item_id, current in sorted(current_items.items()):
            if item_id in resolved_items or current is None:
                continue
            intents.append(ConfigIntent(
                facet_id=FACET, item_id=item_id, op="reset",
                native_key=f"{FACET}.{item_id}",
                source=f"profile@{target_facts.get('source_revision', '')}",
            ))
        return CompileResult(intents=tuple(intents))


def load_external_adapter():
    spec = importlib.util.spec_from_file_location(
        "ordessa_test_external_adapter_z1", FIXTURE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ReadbackExternalAdapterPlugin()


class Runtime:
    """Mirrors C0's controlled runtime: generation files, an operation-bound
    native owner receipt and the matching native readback (the service only
    confirms when the readback carries the activation receipt)."""

    def __init__(self, root):
        self.root = root
        self.root.mkdir()
        self.root.chmod(0o700)  # the service refuses group/world-writable roots
        self.activate_count = 0
        self.fail_after_effect = False
        self.corrupt_readback = False
        self.bytes = None
        self.snapshot_files = {}
        self.revision = "base-1"
        self.receipt = None

    def capture(self, target):
        from ordessa_harness_api import AdapterContext, Installation
        from ordessa_harness.application.configuration_service import RuntimeSnapshot
        from ordessa_harness.materialization import MergeAuthority, TargetAuthority
        from ordessa_harness_api import TargetDescriptor, TargetHandle as _TH
        descriptor = TargetDescriptor(
            __import__("ordessa_harness_api").TargetHandle("external-config", 7),
            "file", "json", "instance", (("model",),))
        context = AdapterContext(
            (descriptor,),
            Installation("test-external", (1, 0, 0), (1, 0, 0), "fixture:installed"),
            "acp", "instance", "fixture:capability")
        return RuntimeSnapshot(
            target, context,
            MergeAuthority((TargetAuthority(descriptor, ("private", "settings.json")),)),
            self.snapshot_files, {}, self.root, {},
            self.revision, "native-version-1", 1, "auth-1", "secret-ref-1")

    def activate_generation(self, operation_id, target, lease, manifest_digest):
        from pathlib import Path as _P
        from ordessa_harness.application.operation_journal import NativeActivationReceipt
        self.activate_count += 1
        resource = ("private", "settings.json")
        self.bytes = lease.read_bytes(resource)
        self.revision = "applied-1"
        if self.fail_after_effect:
            raise OSError("controlled endpoint lost acknowledgement after effect")
        self.receipt = NativeActivationReceipt(operation_id, target, manifest_digest,
            "native-session-1", self.revision, f"fixture:native-owner:{operation_id}")
        return self.receipt

    def observe(self, target):
        from ordessa_harness.application.configuration_service import NativeReadback
        assert self.bytes is not None
        data = b'{"model":"other"}' if self.corrupt_readback else self.bytes
        return NativeReadback(
            target, "native-session-1", self.revision, json.loads(data),
            ((("private", "settings.json"),
              __import__("hashlib").sha256(data).hexdigest()),),
            "fixture:readback:" + __import__("hashlib").sha256(data).hexdigest(),
            ("private-generation",), self.receipt)


class Permit:
    def __init__(self, allowed=True):
        self.allowed = allowed
        self.calls = 0

    def verify(self, principal, target, plan, operation_key, permit):
        self.calls += 1
        return self.allowed and principal == "alice" and permit == "signed:fixture"


def make_world(tmp_path, *, permit_allowed=True):
    """Product carrier + real ConfigurationApplicationService + Profile core."""
    from ordessa_server.bootstrap import build_runtime
    from ordessa_harness.application import (
        ConfigurationApplicationService, OperationJournal,
    )
    from ordessa_harness_api import ApplicationTarget

    product = build_runtime(tmp_path / "product")
    host = product.plugin_host
    host.activate(load_external_adapter())

    runtime = Runtime(tmp_path / "generations")
    permit = Permit(allowed=permit_allowed)
    journal = OperationJournal(tmp_path / "operations.sqlite")
    target = ApplicationTarget("local", "S", "S", 0)
    service = ConfigurationApplicationService(
        principal="alice", target=target, carrier=host, runtime=runtime,
        permits=permit, journal=journal)

    core = make_core(
        tmp_path, providers=(),
        v2_providers=((FixtureProvider(), "carrier-test-domain"),),
        config_port=HarnessApiConfigPort(
            service,
            permit_provider=lambda ref, plan_id: "signed:fixture",
            schema_version_of=lambda facet_id: "v1",
            revision_provider=lambda ref: runtime.revision,
        ),
    )
    # The fixture adapter's verify confirms ONLY observed
    # {"model": "fixture-model"} — B's stored value must match.
    a = core.profiles.create("ka", harness_id="pi", display_name="A")
    b = core.profiles.create("kb", harness_id="pi", display_name="B")
    core.profiles.set_facet_values(
        "ka1", profile_id=a["profile_id"], expected_version=1,
        values=[{"facet_id": FACET, "item_id": ITEM,
                 "value": {"model": "m1"}}])
    core.profiles.set_facet_values(
        "kb1", profile_id=b["profile_id"], expected_version=1,
        values=[{"facet_id": FACET, "item_id": ITEM,
                 "value": {"model": "fixture-model"}}])
    core.sessions.open_session("ks", session_id="S", harness_id="pi",
                               profile_id=a["profile_id"])
    return core, a, b, runtime, permit, service, product


def test_real_service_confirmed_switch_receipt_and_overlay_clear(tmp_path):
    core, a, b, runtime, permit, service, product = make_world(tmp_path)
    try:
        core.sessions.set_overlay(
            "o1", session_id="S", facet_id=FACET, item_id=ITEM,
            value={"model": "m3"})  # overlay differs → a real set intent exists
        core.sessions.select_profile(
            "s1", session_id="S", profile_id=b["profile_id"])
        ticket = core.sessions.begin_turn("t1", session_id="S")
        assert ticket["applied_switch"] is True
        receipt = ticket["receipt"]
        assert receipt["evidence_kind"] == "harness-api-confirmed"
        assert receipt["execution_id"] == "native-session-1"
        config = core.sessions.session_config("S")
        assert config["current"]["profile_id"] == b["profile_id"]
        assert config["evidence"]["journal"]["state"] == "confirmed"
        values = {i["item_id"]: i["value"] for i in config["items"]}
        assert values[ITEM] == {"model": "fixture-model"}
        assert all(i["source"] == "profile" for i in config["items"])  # overlay cleared
        assert runtime.activate_count == 1  # the native effect happened once
        # the real runtime generation file carries the applied payload
        assert json.loads(runtime.bytes)["model"] == "fixture-model"
    finally:
        product.stop()


def test_real_service_permit_refusal_is_retriable_not_unknown(tmp_path):
    core, a, b, runtime, permit, service, product = make_world(
        tmp_path, permit_allowed=False)
    try:
        core.sessions.select_profile(
            "s1", session_id="S", profile_id=b["profile_id"])
        with pytest.raises(ProfileError) as exc:
            core.sessions.begin_turn("t1", session_id="S")
        assert exc.value.code == "SWITCH_BLOCKED"
        config = core.sessions.session_config("S")
        assert config["switch_state"] == "pending"  # retriable
        assert config["evidence"]["journal"]["state"] == "rejected"
        assert core.sessions.turns("S") == []
        assert runtime.activate_count == 0  # zero native writes (G08/G09)
        # authorization restored: the same pending switch then applies
        permit.allowed = True
        ticket = core.sessions.begin_turn("t2", session_id="S")
        assert ticket["applied_switch"] is True
    finally:
        product.stop()


def test_real_service_lost_ack_blocks_and_published_reconcile_stays_unknown(tmp_path):
    core, a, b, runtime, permit, service, product = make_world(tmp_path)
    try:
        runtime.fail_after_effect = True  # effect happens, ack lost
        core.sessions.select_profile(
            "s1", session_id="S", profile_id=b["profile_id"])
        with pytest.raises(ProfileError) as exc:
            core.sessions.begin_turn("t1", session_id="S")
        assert exc.value.code == "SESSION_NEEDS_RECOVERY"
        config = core.sessions.session_config("S")
        assert config["switch_state"] == "needs_recovery"
        assert config["evidence"]["journal"]["state"] == "unknown"
        assert core.sessions.turns("S") == []  # no message went out
        # native effect DID happen once, exactly once (G10: no silent retry)
        assert runtime.activate_count == 1
        # The published slice's reconcile is read-only and cannot prove a
        # native outcome (checkpoint limitation: operation-bound native
        # receipts are absent) — it stays unknown and the session stays
        # blocked.  Profile never settles on a guess.
        runtime.fail_after_effect = False
        result = core.sessions.reconcile("r1", session_id="S")
        assert result["state"] == "unknown"
        config = core.sessions.session_config("S")
        assert config["switch_state"] == "needs_recovery"
        assert config["evidence"]["receipt"] is None
        with pytest.raises(ProfileError):
            core.sessions.begin_turn("t2", session_id="S")  # send stays blocked
    finally:
        product.stop()


def test_real_service_corrupt_readback_keeps_blocked_and_never_fakes(tmp_path):
    core, a, b, runtime, permit, service, product = make_world(tmp_path)
    try:
        runtime.corrupt_readback = True  # native claims success, proof lies
        core.sessions.select_profile(
            "s1", session_id="S", profile_id=b["profile_id"])
        with pytest.raises(ProfileError):
            core.sessions.begin_turn("t1", session_id="S")
        config = core.sessions.session_config("S")
        assert config["switch_state"] == "needs_recovery"
        assert config["evidence"]["receipt"] is None
        # still corrupt: reconcile stays unknown — Profile must not settle
        result = core.sessions.reconcile("r1", session_id="S")
        assert result["state"] == "unknown"
        assert core.sessions.session_config("S")["switch_state"] == \
            "needs_recovery"
        result = core.sessions.reconcile("r2", session_id="S")
        assert result["state"] == "unknown"  # read-only reconcile, never guesses
    finally:
        product.stop()


def test_reset_unsupported_by_carrier_blocks_honestly_g08_g13(tmp_path):
    """The fixture adapter cannot compile resets (inspect honestly reports
    reset=unknown).  A switch that would remove an owned item must be
    blocked at plan time — never filtered away, never faked as applied."""
    core, a, b, runtime, permit, service, product = make_world(tmp_path)
    try:
        # B has NO carrier-facet value: switching A→B would remove the item
        b2 = core.profiles.create("kb2", harness_id="pi", display_name="B2")
        core.sessions.select_profile(
            "s1", session_id="S", profile_id=b2["profile_id"])
        with pytest.raises(ProfileError) as exc:
            core.sessions.begin_turn("t1", session_id="S")
        assert exc.value.code == "SWITCH_BLOCKED"
        config = core.sessions.session_config("S")
        assert config["switch_state"] == "pending"  # retriable, nothing applied
        assert config["current"]["profile_id"] == a["profile_id"]
        assert core.sessions.turns("S") == []
        assert runtime.activate_count == 0  # zero native writes
        journal = config["evidence"]["journal"]
        assert journal is None or journal["state"] in ("planned", "rejected")
    finally:
        product.stop()
