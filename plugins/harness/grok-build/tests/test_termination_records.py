"""C: grok-build family termination face over the REAL UnitRecords journal.

Real temporary SQLite + real OperationJournal/UnitRecords + the production
``GrokBuildTerminationEvidencePort`` logic; the native channel is a controlled
stub (no grok binary, no process). The port verifies process-level facts
against the bound record exactly as it does in P — with a stub subprocess
standing in for the real handle, so the verification logic
(pid/exit/liveness/roots/held-vs-released/correlation) is covered at C and
re-proven at P when the real grok process gate opens (registered NOT_RUN
until then).

Discipline: unknown keeps the attempt and its hold; release never kills and
never claims a stop effect; cold reconciliation is read-only along the
original correlation; caller strings alone are never evidence.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from ordessa_units.admission.invocation import InvocationVerifier
from ordessa_infrastructure.encoding.immutable_json import safe_json
from ordessa_harness_grok_build import (
    ChannelRecord, GrokBuildConnectionLeasePort, GrokBuildLeaseRefused, GrokBuildProviderRefused,
    GrokBuildRuntimeProvider, GrokBuildTerminationEvidencePort, GrokBuildTerminationRefused,
    PROTOCOL, termination_ready,
)
from ordessa_units.records.operation_journal import OperationJournal
from ordessa_units.records.unit_records import (
    CanonicalConfigurationScopeRef, UnitRecords, UnitRecordsRefused,
)

ENVIRONMENT = "grok-build-c"
# Test fixture digest only — NOT a real implementation digest.
DIGEST = "sha256:" + "a" * 64
DEFINITION = {"environmentNamespace": ENVIRONMENT, "definitionId": "grok-build", "revision": "1"}
PROVIDER = {"environmentNamespace": ENVIRONMENT, "providerId": "grok-build", "implementationDigest": DIGEST,
            "contractVersion": "agent-runtime/2", "generation": 1,
            "ownerActivationRef": {"environmentNamespace": ENVIRONMENT, "pluginId": "grok-build-plugin", "generation": 1}}
NODE = {"environmentNamespace": ENVIRONMENT, "nodeId": "node", "generation": 1}
REQUEST = {"environmentNamespace": ENVIRONMENT, "principalScope": "principal", "requestId": "request"}
SCOPE = CanonicalConfigurationScopeRef(ENVIRONMENT, "grok-build-c-physical", "1")


class StubProcess:
    def __init__(self, pid=4242):
        self.pid = pid
        self.returncode = None

    def poll(self):
        return self.returncode


class StubChannel:
    def __init__(self, process):
        self._process = process


class ControlledClient:
    """The lifecycle start sequence only needs the session identity round trip."""

    def __init__(self):
        self.calls = []

    def initialize(self):
        self.calls.append("initialize")
        return {"protocolVersion": 1, "agentCapabilities": {}}

    def new_session(self, **params):
        self.calls.append("session/new")
        return {"sessionId": "ses-1"}

    def command(self, method, **params):
        raise AssertionError("grok-build provider issues no generic RPC: " + method)


class ControlledChannelFactory:
    """Controlled factory double with the real open/record/close/release contract."""

    def __init__(self, roots):
        self.executable = "grok"
        self.roots = roots
        self.opens = 0
        self.released = False
        self.close_quiet = False  # when True, close() does not make the process exit
        self.client = ControlledClient()
        self._record = None

    def open(self, roots, facts):
        assert safe_json(roots) == safe_json(self.roots) and facts.get("action") == "start" and facts.get("query") is False
        self.opens += 1
        process = StubProcess()
        self._record = ChannelRecord(object(), self.client, StubChannel(process), object(),
                                     SimpleNamespace(argv=(self.executable, "agent", "stdio")), dict(roots))
        return self.client

    def record(self, entry):
        if self._record is None or self.released:
            raise RuntimeError("native channel record belongs to another factory view")
        return self._record

    def close(self, entry, timeout=15.0):
        process = self._record.channel._process
        if not self.close_quiet and process.returncode is None:
            process.returncode = 143
        rec = process.returncode if process.returncode is not None else 143
        return rec

    def release(self, entry):
        process = self._record.channel._process
        if process.poll() is None:
            raise RuntimeError("owned native process is still running; stop the unit first")
        self.released = True
        return {"pid": process.pid, "exitCode": int(process.returncode)}


class ControlledContext:
    __slots__ = ("facts",)

    def __init__(self, facts):
        self.facts = facts


class ControlledEpoch:
    def __init__(self):
        self.value = 0

    def current_epoch(self, node):
        return self.value


class ControlledIssuer(InvocationVerifier):
    """Controlled authority/activation/directory/epoch + verifier, real subclass."""

    def __init__(self, epoch):
        super().__init__(lambda context, *args, **kwargs: context.facts)
        self.allowed = True
        self.active = True
        self.permitted = True
        self.epoch = epoch
        self.issued = {}

    def issue(self, action, step, digest, node=NODE, *, query=False):
        facts = {"query": query, "action": action, "providerRef": PROVIDER,
                 "targetRef": node, "inputDigest": digest,
                 "managementEpoch": self.epoch.value, "request": dict(REQUEST),
                 "operationRef": "operation", "stepId": step}
        context = ControlledContext(facts)
        self.issued[context] = {"facts": facts, "state": "issued", "verified": False}
        return context

    def verify_and_consume(self, context, action, provider, node, digest):
        entry = self.issued.get(context)
        if entry is None:
            raise UnitRecordsRefused("unissued or consumed invocation")
        facts = entry["facts"]
        if (entry["state"] != "issued" or facts.get("action") != action
                or safe_json(facts.get("providerRef")) != safe_json(provider)
                or safe_json(facts.get("targetRef")) != safe_json(node)
                or facts.get("inputDigest") != digest):
            raise UnitRecordsRefused("verified invocation identity differs")
        for allowed, facet in ((self.allowed, "authority revoked"),
                               (self.active, "owner activation revoked"),
                               (self.permitted, "directory permission revoked")):
            if allowed is not True:
                raise UnitRecordsRefused(f"current {facet}")
        if not facts["query"]:
            entry["state"] = "consumed"
        entry["verified"] = True
        return dict(facts)

    def verify_start_continuation(self, unit, context):
        entry = self.issued.get(context)
        if (entry is None or entry["verified"] is not True or entry["state"] != "consumed"
                or entry["facts"] is not context.facts):
            raise UnitRecordsRefused("original start has no successful verification on this issuer")
        facts = entry["facts"]
        if (facts.get("action") != "start" or facts.get("query") is not False
                or safe_json(facts.get("providerRef")) != safe_json(unit.facts["providerRef"])
                or safe_json(facts.get("targetRef")) != safe_json(unit.facts["nodeRef"])
                or facts.get("managementEpoch") != unit.facts["managementEpoch"]):
            raise UnitRecordsRefused("current start authority identity differs")
        return self._facets(facts)

    def _facets(self, facts):
        for allowed, facet in ((self.allowed, "authority revoked"),
                               (self.active, "owner activation revoked"),
                               (self.permitted, "directory permission revoked")):
            if allowed is not True:
                raise UnitRecordsRefused(f"current {facet}")
        if self.epoch.value != facts["managementEpoch"]:
            raise UnitRecordsRefused("management epoch changed")
        return dict(facts)


class ControlledScope:
    def issue_scope(self, provider, node, roots):
        assert safe_json(provider) == safe_json(PROVIDER)
        return SCOPE

    def verify_scope(self, scope, roots):
        return scope == SCOPE

    def map_legacy_scope(self, target):
        raise AssertionError("no legacy fixture operations in this harness")


class ControlledProjection:
    """Same shape as the real GrokBuildUnitProjection, with controlled authority ports."""

    def __init__(self, issuer):
        self.issuer = issuer
        self.records = None

    def attach_owner(self, records):
        self.records = records

    def verify_preparation(self, plan, facts):
        assert safe_json(plan["context"]["nodeRef"]) == safe_json(facts["targetRef"])
        return plan["context"]["privateRootFacts"]

    def revalidate_start(self, unit, context):
        return self.issuer.verify_start_continuation(unit, context)

    def read_unit(self, ref):
        return self._owner_unit(ref)

    def read_session(self, ref):
        unit = self._owner_unit(ref)
        return self.records.owner_read_session(unit.unit_ref)

    def _owner_unit(self, ref):
        unit = self.records.owner_read_unit(ref["unitId"])
        if safe_json(unit.public_ref) != safe_json(ref):
            raise RuntimeError("unit reference differs from original owner source")
        return unit

    def publication_facts(self, ref):
        raise RuntimeError("core publication owner is absent")

    def publish_channel(self, unit, client, native_evidence):
        assert isinstance(native_evidence.get("sessionId"), str)
        assert isinstance(native_evidence.get("initialize"), dict)
        return "grok-build-native-session/controlled"

    def verify_binding(self, unit, creation_correlation, evidence):
        if evidence != "grok-build-native-session/controlled":
            raise RuntimeError("original native session evidence is missing or forged")
        return {"nativeRealm": PROTOCOL, "sessionId": "ses-1", "evidenceRef": evidence}

    def query_creation(self, correlation, facts):
        raise RuntimeError("controlled projection observes no cold creations in this harness")


def build(tmp_path, *, close_quiet=False):
    roots = {"cwd": str(tmp_path / "cwd"), "home": str(tmp_path / "home"),
             "grokHome": str(tmp_path / "grok")}
    epoch = ControlledEpoch()
    issuer = ControlledIssuer(epoch)
    factory = ControlledChannelFactory(roots)
    factory.close_quiet = close_quiet
    projection = ControlledProjection(issuer)
    port = GrokBuildTerminationEvidencePort(factory)
    journal = OperationJournal(tmp_path / "owner.sqlite")
    records = UnitRecords(journal, scope_authority=ControlledScope(), native_evidence=projection,
                          verifier=issuer, epoch_port=epoch, termination_evidence=port)
    projection.attach_owner(records)
    provider = GrokBuildRuntimeProvider(definition_ref=DEFINITION, implementation_digest=DIGEST,
                                        unit_records=records, projection=projection, verifier=issuer,
                                        channel_factory=factory, lease_port=GrokBuildConnectionLeasePort(),
                                        termination_evidence=port)
    assert termination_ready(records, port)
    return SimpleNamespace(tmp_path=tmp_path, roots=roots, epoch=epoch, issuer=issuer, factory=factory,
                           port=port, projection=projection, records=records, provider=provider)


@pytest.fixture
def flow(tmp_path):
    harness = build(tmp_path)
    context = harness.issuer.issue("prepare", "prepare", "prepare-input")
    plan = {"context": {"nodeRef": NODE, "privateRootFacts": dict(harness.roots)}}
    result = harness.provider.prepare(plan, context)
    harness.unit = harness.records.owner_read_unit(result["unitRef"]["unitId"])
    start = harness.issuer.issue("start", "start", "start-input")
    outcome = harness.provider.start({"unitRef": harness.unit.public_ref}, start)
    assert outcome["state"] == "confirmed"
    yield harness


def test_stop_and_release_are_advertised_only_with_the_production_ports(flow):
    methods = flow.provider.descriptor.supported_methods
    assert "stop" in methods and "release" in methods
    assert "apply_configuration" not in methods and "describe_configuration" not in methods
    assert flow.provider.termination_evidence is flow.port
    assert flow.records.termination_evidence is flow.port


def test_stop_records_confirmed_with_port_verified_process_refs(flow):
    unit_ref = flow.unit.public_ref
    result = flow.provider.stop(unit_ref, flow.issuer.issue("stop", "stop", "stop-input"))
    assert result["state"] == "confirmed" and result["action"] == "stop"
    record = flow.records.owner_read_termination(flow.unit.unit_ref, "stop")
    assert record["state"] == "confirmed" and record["projection"] == "owner-read"
    outcome = record["outcome"]
    assert outcome["nativeRealm"] == PROTOCOL and outcome["action"] == "stop"
    assert outcome["processRef"] == "grok-build-process/4242" and outcome["exitRef"] == "exit/143"
    assert re.fullmatch(r"grok-build-termination/[0-9a-f]{64}", outcome["evidenceRef"])
    binding = flow.records.owner_read_session(flow.unit.unit_ref)
    assert binding.state == "confirmed"  # stop does not rewrite the original session truth


def test_second_stop_is_refused_and_first_attempt_stays_single(flow):
    result = flow.provider.stop(flow.unit.public_ref, flow.issuer.issue("stop", "stop", "stop-input"))
    assert result["state"] == "confirmed"
    replay = flow.issuer.issue("stop", "stop-2", "other")
    with pytest.raises(UnitRecordsRefused, match="already"):
        flow.provider.stop(flow.unit.public_ref, replay)
    # The journal consumed the replay's authorization inside its admission
    # transaction before refusing the ledger collision; the hold stays single
    # and the caller can never reuse the spent claim.
    assert flow.issuer.issued[replay]["state"] == "consumed"
    rows = [action for action in ("stop", "release")
            if flow.records.owner_read_termination(flow.unit.unit_ref, action) is not None]
    assert rows == ["stop"] and rows[0] and \
        flow.records.owner_read_termination(flow.unit.unit_ref, "stop")["state"] == "confirmed"


def test_release_after_stop_frees_owned_records_and_revokes_grants(flow):
    unit_ref = flow.unit.public_ref
    stale_grant = flow.provider.lease_port.grant(unit_ref)
    assert flow.provider.stop(unit_ref, flow.issuer.issue("stop", "stop", "stop-input"))["state"] == "confirmed"
    result = flow.provider.release(unit_ref, flow.issuer.issue("release", "release", "release-input"))
    assert result["state"] == "confirmed" and result["action"] == "release"
    record = flow.records.owner_read_termination(flow.unit.unit_ref, "release")
    assert record["outcome"]["processRef"] == "grok-build-process/4242"
    assert record["outcome"]["exitRef"] == "exit/143"
    assert flow.factory.released is True
    assert flow.provider._channels == {}  # owned live handles are gone
    with pytest.raises(GrokBuildProviderRefused):
        flow.provider.describe_access(unit_ref)  # released owner no longer grants access
    with pytest.raises(GrokBuildLeaseRefused):
        # the pre-release grant was revoked: borrowed connections can never rebind
        flow.provider.lease_port.bind(unit_ref, stale_grant, object())


def test_release_before_stop_refuses_live_owned_unit_without_kill(flow):
    unit_ref = flow.unit.public_ref
    release = flow.issuer.issue("release", "release", "release-input")
    with pytest.raises(GrokBuildProviderRefused, match="requires stop before release"):
        flow.provider.release(unit_ref, release)
    assert flow.issuer.issued[release]["state"] == "issued"  # authority never consumed
    assert flow.records.owner_read_termination(flow.unit.unit_ref, "release") is None
    assert flow.factory._record.channel._process.poll() is None  # nothing was killed
    assert flow.factory.released is False


def test_release_without_owned_channel_records_nothing_owned(tmp_path):
    flow = build(tmp_path)
    context = flow.issuer.issue("prepare", "prepare", "prepare-input")
    result = flow.provider.prepare({"context": {"nodeRef": NODE, "privateRootFacts": dict(flow.roots)}}, context)
    flow.unit = flow.records.owner_read_unit(result["unitRef"]["unitId"])
    outcome = flow.provider.release(flow.unit.public_ref, flow.issuer.issue("release", "release", "release-input"))
    assert outcome["state"] == "confirmed"
    record = flow.records.owner_read_termination(flow.unit.unit_ref, "release")
    assert record["outcome"]["processRef"] == "grok-build-process/none"
    with pytest.raises(UnitRecordsRefused, match="already"):
        flow.provider.release(flow.unit.public_ref, flow.issuer.issue("release", "release-2", "x"))


def test_stop_unknown_keeps_hold_until_owner_verified_reconcile(tmp_path):
    flow = build(tmp_path, close_quiet=True)  # the stub close does not make the process exit
    context = flow.issuer.issue("prepare", "prepare", "prepare-input")
    prepared = flow.provider.prepare({"context": {"nodeRef": NODE, "privateRootFacts": dict(flow.roots)}}, context)
    flow.unit = flow.records.owner_read_unit(prepared["unitRef"]["unitId"])
    flow.provider.start({"unitRef": flow.unit.public_ref}, flow.issuer.issue("start", "start", "start-input"))
    with pytest.raises(GrokBuildProviderRefused, match="unknown"):
        flow.provider.stop(flow.unit.public_ref, flow.issuer.issue("stop", "stop", "stop-input"))
    record = flow.records.owner_read_termination(flow.unit.unit_ref, "stop")
    assert record["state"] == "unknown" and record["outcome"] is None
    correlation = record["identity"]["correlation"]
    # nothing else delivered the effect; the hold remains and no second stop exists
    with pytest.raises(UnitRecordsRefused, match="already"):
        flow.provider.stop(flow.unit.public_ref, flow.issuer.issue("stop", "stop-2", "x"))
    # the effect completes out of band; a read-only observation along the ORIGINAL
    # correlation lets the owner reconcile the retained attempt
    flow.factory._record.channel._process.returncode = 143
    observed = flow.port.observe_termination(flow.unit, "stop", correlation)
    query = flow.issuer.issue("query", "stop", "stop-input", query=True)
    reconciled = flow.records.reconcile_termination(flow.unit.unit_ref, query, input_digest="stop-input",
                                                    action="stop", expected_source_revision=2,
                                                    state="confirmed", evidence=observed)
    assert reconciled["state"] == "confirmed"
    assert reconciled["outcome"]["evidenceRef"].startswith("grok-build-termination/")
    foreign = flow.issuer.issue("query", "foreign-step", "stop-input", query=True)
    with pytest.raises(UnitRecordsRefused, match="original termination attempt"):
        flow.records.reconcile_termination(flow.unit.unit_ref, foreign, input_digest="stop-input",
                                           action="stop", expected_source_revision=3,
                                           state="confirmed", evidence=observed)
    terminal = flow.records.owner_read_termination(flow.unit.unit_ref, "stop")
    with pytest.raises(UnitRecordsRefused, match="terminal"):
        flow.records.reconcile_termination(flow.unit.unit_ref, query, input_digest="stop-input",
                                           action="stop", expected_source_revision=terminal["sourceRevision"],
                                           state="unknown")


def test_termination_refuses_forged_unit_and_foreign_action(flow):
    forged = {**flow.unit.public_ref, "unitId": "unit-other"}
    with pytest.raises(UnitRecordsRefused):
        flow.provider.stop(forged, flow.issuer.issue("stop", "stop", "x"))
    with pytest.raises(UnitRecordsRefused, match="stop or release"):
        flow.records.begin_termination(flow.unit.unit_ref, flow.issuer.issue("freeze", "x", "x"),
                                       input_digest="x", action="freeze")
    assert flow.records.owner_read_termination(flow.unit.unit_ref, "stop") is None


def test_epoch_change_expires_stop_ticket_and_keeps_hold(tmp_path):
    flow = build(tmp_path)
    context = flow.issuer.issue("prepare", "prepare", "prepare-input")
    prepared = flow.provider.prepare({"context": {"nodeRef": NODE, "privateRootFacts": dict(flow.roots)}}, context)
    flow.unit = flow.records.owner_read_unit(prepared["unitRef"]["unitId"])
    flow.provider.start({"unitRef": flow.unit.public_ref}, flow.issuer.issue("start", "start", "start-input"))
    # the activation epoch moves INSIDE the effect (between begin and record)
    original_close = flow.factory.close
    def bumping_close(entry, timeout=15.0):
        flow.epoch.value = 1
        return original_close(entry, timeout=timeout)
    flow.factory.close = bumping_close
    with pytest.raises(GrokBuildProviderRefused, match="unknown"):
        flow.provider.stop(flow.unit.public_ref, flow.issuer.issue("stop", "stop", "stop-input"))
    record = flow.records.owner_read_termination(flow.unit.unit_ref, "stop")
    assert record["state"] == "opening" and record["outcome"] is None


# -- production evidence port counter-examples (stub handle, real logic) --------

def terminated_record(tmp_path, *, exit_code=143, pid=4242, roots=None, executable="grok"):
    roots = roots or {"cwd": str(tmp_path / "cwd"), "home": str(tmp_path / "home"),
                      "grokHome": str(tmp_path / "grok")}
    process = StubProcess(pid)
    process.returncode = exit_code
    record = ChannelRecord(object(), ControlledClient(), StubChannel(process), object(),
                           SimpleNamespace(argv=(executable, "agent", "stdio")), dict(roots))
    return record, roots


class RecordingFactory:
    def __init__(self, executable="grok"):
        self.executable = executable
        self.records_map = {}

    def record(self, entry):
        target = self.records_map.get(id(entry))
        if target is None:
            raise RuntimeError("native channel record belongs to another factory view")
        return target


def evidence(action="stop", correlation="corr", *, pid="4242", exit_code=None, now=None):
    observed = {"action": action, "correlation": correlation,
                "observedAt": now or datetime.now(timezone.utc).isoformat()}
    if pid is not None:
        observed["pid"] = pid
        observed["exitCode"] = exit_code
    else:
        observed["ownedProcess"] = "none"
    return observed


def test_port_verifies_real_exited_process_shape(tmp_path):
    record, roots = terminated_record(tmp_path)
    factory = RecordingFactory()
    factory.records_map[id(record.entry)] = record
    port = GrokBuildTerminationEvidencePort(factory)
    port.bind_unit_channel("unit-1", record)
    refs = port.verify_termination(SimpleNamespace(unit_ref="unit-1", public_ref={"a": 1},
                                                   facts={"privateRootFacts": roots}), "stop", "corr",
                                   evidence(pid="4242", exit_code="143"))
    assert refs["processRef"] == "grok-build-process/4242" and refs["exitRef"] == "exit/143"
    assert refs["nativeRealm"] == PROTOCOL and refs["action"] == "stop"
    assert set(refs) == {"nativeRealm", "action", "processRef", "exitRef", "evidenceRef"}
    assert all(isinstance(value, str) and value for value in refs.values())


@pytest.mark.parametrize("mutate,message", [
    (lambda e: e.update(pid="7"), "observed pid"),
    (lambda e: e.update(exitCode="9"), "observed exit code"),
    (lambda e: e.update(action="release"), "another attempt"),
    (lambda e: e.update(correlation="other"), "another attempt"),
    (lambda e: e.update(observedAt="not-a-time"), "shape differs"),
    (lambda e: e.pop("exitCode"), "shape differs"),
])
def test_port_refuses_forged_stop_facts(tmp_path, mutate, message):
    record, roots = terminated_record(tmp_path)
    factory = RecordingFactory()
    factory.records_map[id(record.entry)] = record
    port = GrokBuildTerminationEvidencePort(factory)
    port.bind_unit_channel("unit-1", record)
    unit = SimpleNamespace(unit_ref="unit-1", public_ref={"a": 1}, facts={"privateRootFacts": roots})
    forged = evidence(pid="4242", exit_code="143")
    mutate(forged)
    with pytest.raises(GrokBuildTerminationRefused, match=message):
        port.verify_termination(unit, "stop", "corr", forged)


def test_port_refuses_live_process_released_missing_and_forged_roots(tmp_path):
    record, roots = terminated_record(tmp_path)
    record.channel._process.returncode = None  # still running: no effect exists
    factory = RecordingFactory()
    factory.records_map[id(record.entry)] = record
    port = GrokBuildTerminationEvidencePort(factory)
    port.bind_unit_channel("unit-1", record)
    unit = SimpleNamespace(unit_ref="unit-1", public_ref={"a": 1}, facts={"privateRootFacts": roots})
    with pytest.raises(GrokBuildTerminationRefused, match="still running"):
        port.verify_termination(unit, "stop", "corr", evidence(pid="4242", exit_code="0"))
    record.channel._process.returncode = 143
    with pytest.raises(GrokBuildTerminationRefused, match="released channel record"):
        port.verify_termination(unit, "release", "corr", evidence(action="release", pid="4242", exit_code="143"))
    foreign_roots = {**roots, "grokHome": str(tmp_path / "elsewhere")}
    other, _ = terminated_record(tmp_path, roots=foreign_roots)
    other.roots = {**roots, "grokHome": "/somewhere/not-the-unit-roots"}
    factory.records_map[id(other.entry)] = other
    port.bind_unit_channel("unit-2", other)
    unit2 = SimpleNamespace(unit_ref="unit-2", public_ref={"a": 2}, facts={"privateRootFacts": foreign_roots})
    with pytest.raises(GrokBuildTerminationRefused, match="differ from the original unit roots"):
        port.verify_termination(unit2, "stop", "corr", evidence(pid="4242", exit_code="143"))


def test_port_release_requires_released_record_and_no_owned_shape(tmp_path):
    record, roots = terminated_record(tmp_path)
    factory = RecordingFactory()
    factory.records_map[id(record.entry)] = record
    port = GrokBuildTerminationEvidencePort(factory)
    port.bind_unit_channel("unit-1", record)
    unit = SimpleNamespace(unit_ref="unit-1", public_ref={"a": 1}, facts={"privateRootFacts": roots})
    with pytest.raises(GrokBuildTerminationRefused, match="released channel record"):
        port.verify_termination(unit, "release", "corr", evidence(action="release", pid="4242", exit_code="143"))
    factory.records_map.pop(id(record.entry))  # the factory released it
    refs = port.verify_termination(unit, "release", "corr", evidence(action="release", pid="4242", exit_code="143"))
    assert refs["processRef"] == "grok-build-process/4242"
    none_refs = port.verify_termination(SimpleNamespace(unit_ref="unit-9", public_ref={"a": 9},
                                                        facts={"privateRootFacts": roots}),
                                        "release", "corr", evidence(action="release", pid=None))
    assert none_refs["processRef"] == "grok-build-process/none"
    with pytest.raises(GrokBuildTerminationRefused, match="still exists for this unit"):
        port.verify_termination(unit, "stop", "corr", evidence(pid=None))  # binding exists


def test_port_refuses_binding_conflicts_and_observes_read_only(tmp_path):
    record, roots = terminated_record(tmp_path)
    factory = RecordingFactory()
    port = GrokBuildTerminationEvidencePort(factory)
    port.bind_unit_channel("unit-1", record)
    other, _ = terminated_record(tmp_path)
    with pytest.raises(GrokBuildTerminationRefused, match="another owned channel record"):
        port.bind_unit_channel("unit-1", other)
    unit = SimpleNamespace(unit_ref="unit-1", public_ref={"a": 1}, facts={"privateRootFacts": roots})
    observed = port.observe_termination(unit, "stop", "corr")
    assert observed["pid"] == "4242" and observed["exitCode"] == "143"
    assert record.channel._process.returncode == 143  # observation changed nothing
    with pytest.raises(GrokBuildTerminationRefused, match="requires the original attempt facts"):
        port.observe_termination(unit, "restart", "corr")
    alive, alive_roots = terminated_record(tmp_path, pid=5151)
    alive.channel._process.returncode = None  # still running: no termination fact exists
    port.bind_unit_channel("unit-3", alive)
    with pytest.raises(GrokBuildTerminationRefused, match="still running"):
        port.observe_termination(SimpleNamespace(unit_ref="unit-3", public_ref={"a": 3},
                                                 facts={"privateRootFacts": alive_roots}), "stop", "corr")
