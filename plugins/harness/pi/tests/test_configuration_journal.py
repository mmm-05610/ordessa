"""C: pi configuration confirmation through the REAL NativeConfigurationAttempt journal.

Real temporary SQLite + real OperationJournal/UnitRecords; the pi channel is a
controlled client double and the deployment's configuration evidence port is a
checking store double. This proves the records-path journal seam (begin →
pre-send dispatch binding → record/query) and that confirmation depends on
native observation (readback), never the ACK. P-level proof of the same seam
on the real process lives in test_runtime_process.py.
"""
from __future__ import annotations

import copy
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from pacthold.agents.configuration import (
    ConfigurationChangeRequest, ConfigurationChangeResult, ConfigurationItemResult,
    ConfigurationSnapshot,
)
from pacthold.agents.invocation import InvocationVerifier
from ordessa_environment_api.operations import safe_json
from ordessa_harness_transport import RequestTimeout
from ordessa_harness_pi import PiConnectionLeasePort, PiProviderRefused, PiRuntimeProvider
from ordessa_harness_records.operation_journal import OperationJournal
from ordessa_harness_records.unit_records import UnitRecords, UnitRecordsRefused
from test_termination_records import (  # shared controlled issuer/journal harness
    ControlledChannelFactory, ControlledContext, ControlledEpoch, ControlledIssuer,
    ControlledProjection, ControlledScope, DEFINITION, DIGEST, ENVIRONMENT, NODE, PROVIDER,
    REQUEST, SCOPE, build,
)


class JournallingEvidence:
    """Configuration evidence store double that actually verifies its captures."""

    def __init__(self):
        self.captured = {}
        self.next = 0

    def capture_configuration(self, unit, facts, native_request, native_receipt,
                              before_readback, after_readback, summary):
        request = json.loads(json.dumps(dict(native_request)))
        receipt = json.loads(safe_json(dict(native_receipt)))
        payload = json.dumps([request, receipt, before_readback, after_readback, summary])
        assert "secret-token" not in payload and "apiKey" not in payload
        self.next += 1
        ref = "config-proof-" + str(self.next)
        self.captured[ref] = {"facts": dict(facts), "request": request, "receipt": receipt,
                              "before": json.loads(safe_json(before_readback)),
                              "after": json.loads(safe_json(after_readback)),
                              "summary": json.loads(safe_json(summary))}
        return ref

    def verify_configuration(self, unit, identity, native_request_id, native_request_digest, evidence):
        entry = self.captured.get(evidence)
        if entry is None:
            raise ValueError("captured configuration evidence is missing or forged")
        # the stored confirmation binds the exact captured native dispatch
        digest = "sha256:" + __import__("hashlib").sha256(safe_json(entry["request"]).encode()).hexdigest()
        assert native_request_digest == digest
        assert native_request_id == entry["request"]["id"]
        assert entry["facts"]["inputDigest"] == identity["requestDigest"]
        return {"operationRef": entry["summary"]["operationRef"],
                "unitRef": identity["unitRef"], "scopeRef": identity["scopeRef"],
                "requestDigest": entry["facts"]["inputDigest"],
                "nativeRequestId": native_request_id,
                "nativeRequestDigest": native_request_digest,
                "evidenceRef": evidence}

    def read_configuration_result(self, unit, attempt):
        ref = attempt.confirmation["evidenceRef"]  # a plain string, as stored
        entry = self.captured[ref]
        summary = entry["summary"]
        snapshot = summary["confirmedSnapshot"]
        proof = {"operationRef": summary["operationRef"], "unitRef": identity_value(summary["unitRef"]),
                 "scopeRef": identity_value(summary["scopeRef"]),
                 "requestDigest": summary["requestDigest"],
                 "evidenceRef": {"environmentNamespace": ENVIRONMENT, "evidenceRef": ref}}
        snapshot = ConfigurationSnapshot(snapshot["unitRef"], snapshot["scopeRef"], snapshot["sourceRevision"],
                       snapshot["observedAt"], snapshot["configuration"], tuple(snapshot["unknownItems"]),
                       proof["evidenceRef"], snapshot["comparisonGuarantee"])
        return ConfigurationChangeResult(summary["operationRef"], tuple(
            ConfigurationItemResult(item["declarationId"], item["outcome"],
                                    proof if item["outcome"] == "applied" else None)
            for item in summary["itemOutcomes"]), snapshot)


def identity_value(value):
    return json.loads(safe_json(value))


class ConfigurationClient:
    """Controlled client: pi record shapes, one prepared native write each time."""

    def __init__(self, state):
        self.state = copy.deepcopy(state)
        self.calls = []
        self.seq = 0
        self.lost = False
        self.ack_only = False

    def initialize(self):
        self.calls.append("get_state:initialize")
        return {"sessionId": self.state["sessionId"]}

    def command(self, command, **fields):
        self.calls.append(command)
        assert command == "get_state"
        return {"data": copy.deepcopy(self.state)}

    def prepare_request(self, command, fields):
        self.calls.append("prepare:" + command)
        self.seq += 1
        self.wire = {"id": f"req-{self.seq}", "type": command, **dict(fields)}
        return SimpleNamespace(request_id=f"req-{self.seq}", payload=self.wire)

    def dispatch_prepared(self, frame, *, before_write, timeout=10.0):
        self.calls.append("dispatch")
        if before_write is not None:
            before_write((json.dumps(dict(frame.payload)) + "\n").encode())
        if self.lost:
            raise RequestTimeout(frame.payload["type"], frame.payload["id"], timeout)
        receipt = {"id": frame.payload["id"], "type": "response",
                   "command": frame.payload["type"], "success": True}
        if self.ack_only:
            return receipt
        if frame.payload["type"] == "set_thinking_level":
            # pi's available offline level space is {"off"}: other levels are
            # ACK-clamped without change (observed 0.86.1). The readback decides.
            if frame.payload["level"] == "off":
                self.state["thinkingLevel"] = "off"
        else:
            if frame.payload["modelId"] != "fixture-model":
                receipt["success"] = False
                receipt["error"] = "Model not found"
            else:
                self.state["model"] = {"provider": frame.payload["provider"], "id": frame.payload["modelId"]}
        return receipt


def build_config(tmp_path, *, state=None, client=None, evidence=None):
    roots = {"cwd": str(tmp_path / "cwd"), "home": str(tmp_path / "home"), "piHome": str(tmp_path / "pihome")}
    epoch = ControlledEpoch()
    issuer = ControlledIssuer(epoch)
    state = state or {"sessionId": "session-1", "model": {"provider": "native", "id": "old"},
                      "thinkingLevel": "off", "messageCount": 0, "pendingMessageCount": 0}
    factory = ControlledChannelFactory(roots)
    client = client or ConfigurationClient(state)
    factory.client = client
    evidence = evidence if evidence is not None else JournallingEvidence()
    projection = ControlledProjection(issuer)
    projection.revalidate_configuration = lambda unit, context: issuer.verify_configuration_continuation(unit, context)
    journal = OperationJournal(tmp_path / "owner.sqlite")
    records = UnitRecords(journal, scope_authority=ControlledScope(), native_evidence=projection,
                          verifier=issuer, epoch_port=epoch, configuration_evidence=evidence)
    projection.attach_owner(records)
    provider = PiRuntimeProvider(definition_ref=DEFINITION, implementation_digest=DIGEST,
                                 unit_records=records, projection=projection, verifier=issuer,
                                 channel_factory=factory, lease_port=PiConnectionLeasePort(),
                                 configuration_evidence=evidence)
    prepared = provider.prepare({"context": {"nodeRef": NODE, "privateRootFacts": dict(roots)}},
                                issuer.issue("prepare", "prepare", "prepare-input"))
    unit = records.owner_read_unit(prepared["unitRef"]["unitId"])
    provider.start({"unitRef": unit.public_ref}, issuer.issue("start", "start", "start-input"))
    return SimpleNamespace(roots=roots, epoch=epoch, issuer=issuer, factory=factory, client=client,
                           evidence=evidence, projection=projection, records=records, provider=provider,
                           unit=unit)


def declaration(kind="pi.thinking", payload=None, requirement="required", declaration_id="thinking"):
    return {"declarationId": declaration_id, "configurationKind": kind, "schemaVersion": "1",
            "action": "value", "requirement": requirement,
            "payload": payload or {"level": "off"} if kind == "pi.thinking" else {"provider": "native", "model": "new"}}


def change(flow, *declarations):
    snapshot = flow.provider.inspect_configuration(flow.unit.public_ref)
    request = ConfigurationChangeRequest("request-1", snapshot.source_revision, tuple(declarations))
    context = ControlledContext({"providerRef": PROVIDER,
                                 "targetRef": flow.unit.configuration_target_ref,
                                 "inputDigest": "apply-digest", "action": "applyConfiguration", "query": False,
                                 "managementEpoch": flow.epoch.value, "request": dict(REQUEST),
                                 "operationRef": "operation-config", "stepId": "apply",
                                 "contextRef": {"effectiveDeclarations": request.declarations}})
    flow.issuer.issued[context] = {"facts": context.facts, "state": "issued", "verified": False}
    return request, context


def query_context(flow, operation_ref="operation-config", step="apply", digest="apply-digest",
                  declarations=()):
    context = ControlledContext({"providerRef": PROVIDER, "targetRef": flow.unit.configuration_target_ref,
                                 "inputDigest": digest, "action": "query", "query": True,
                                 "managementEpoch": flow.epoch.value, "request": dict(REQUEST),
                                 "operationRef": operation_ref, "stepId": step,
                                 "contextRef": {"effectiveDeclarations": tuple(declarations)}})
    flow.issuer.issued[context] = {"facts": context.facts, "state": "issued", "verified": False}
    return context


def test_confirmed_change_is_journal_recorded_and_native_readback_backed(tmp_path):
    flow = build_config(tmp_path)
    request, context = change(flow, declaration())
    result = flow.provider.apply_configuration(flow.unit.public_ref, request, context)
    assert result.overall_outcome == "applied"
    assert result.confirmed_snapshot.configuration["pi.thinking"] == {"level": "off"}
    attempt = flow.records.query_configuration_change(flow.unit.unit_ref, "operation-config",
                                                      query_context(flow, declarations=request.declarations),
                                                      input_digest="apply-digest")
    assert attempt.state == "confirmed" and attempt.native_request_id == "req-1"
    assert attempt.confirmation["evidenceRef"].startswith("config-proof-")
    assert flow.evidence.next == 1
    assert flow.client.calls.count("dispatch") == 1
    # the stored confirmation binds the exact native dispatch identity, not the ACK value
    assert attempt.native_request_digest.startswith("sha256:")


def test_stale_expected_revision_refuses_before_journal_claim_and_write(tmp_path):
    flow = build_config(tmp_path)
    request, context = change(flow, declaration())
    stale = ConfigurationChangeRequest("request-2", "sha256:" + "f" * 64, request.declarations)
    with pytest.raises(Exception, match="version prerequisite"):
        flow.provider.apply_configuration(flow.unit.public_ref, stale, context)
    assert flow.client.calls.count("dispatch") == 0
    # the refused apply never consumed the original authority: it still dispatches
    result = flow.provider.apply_configuration(flow.unit.public_ref, request, context)
    assert result.overall_outcome == "applied"


def test_required_unsupported_or_multi_setter_batches_refuse_before_claim(tmp_path):
    flow = build_config(tmp_path)
    request, context = change(flow, declaration(kind="absent", payload={}, requirement="required"))
    with pytest.raises(PiProviderRefused, match="declaration unsupported"):
        flow.provider.apply_configuration(flow.unit.public_ref, request, context)
    request, context = change(flow, declaration(), declaration(kind="pi.model",
                                                              payload={"provider": "native", "model": "new"},
                                                              declaration_id="model"))
    with pytest.raises(PiProviderRefused, match="distinct native writes"):
        flow.provider.apply_configuration(flow.unit.public_ref, request, context)
    request, context = change(flow, declaration(), declaration(kind="absent", payload={}, requirement="optional",
                                                              declaration_id="optional"))
    result = flow.provider.apply_configuration(flow.unit.public_ref, request, context)
    assert [(item.declaration_id, item.outcome) for item in result.item_results] == \
        [("thinking", "applied"), ("optional", "rejected")]
    assert result.overall_outcome == "partial"
    assert flow.client.calls.count("dispatch") == 1  # exactly one native write was bound


def test_readback_mismatch_keeps_unknown_even_with_success_ack(tmp_path):
    flow = build_config(tmp_path)
    # pi ACKs any written record, but the offline level space is only {"off"}:
    # the requested "high" level is clamped and the readback can never match.
    request, context = change(flow, declaration(payload={"level": "high"}))
    result = flow.provider.apply_configuration(flow.unit.public_ref, request, context)
    assert result.overall_outcome == "unknown" and result.confirmed_snapshot is None
    attempt = flow.records.query_configuration_change(flow.unit.unit_ref, "operation-config",
                                                      query_context(flow, declarations=request.declarations),
                                                      input_digest="apply-digest")
    assert attempt.state == "unknown" and attempt.native_request_id == "req-1"
    assert flow.evidence.captured == {}  # no evidence was captured for an unconfirmed change


def test_lost_receipt_never_resents_and_query_stays_unknown(tmp_path):
    flow = build_config(tmp_path)
    flow.client.lost = True
    request, context = change(flow, declaration())
    result = flow.provider.apply_configuration(flow.unit.public_ref, request, context)
    assert result.overall_outcome == "unknown"
    attempt = flow.records.query_configuration_change(flow.unit.unit_ref, "operation-config",
                                                      query_context(flow, declarations=request.declarations),
                                                      input_digest="apply-digest")
    assert attempt.state == "unknown" and attempt.native_request_id == "req-1"
    calls = list(flow.client.calls)
    outcome = flow.provider.query_change(flow.unit.public_ref, "operation-config",
                                         query_context(flow, declarations=request.declarations))
    assert outcome.overall_outcome == "unknown"
    assert flow.client.calls == calls  # the query wrote nothing: no re-dispatch, no recovery send
    # a matching current configuration still never substitutes the lost original receipt
    assert flow.evidence.captured == {}


def test_query_change_reads_confirmed_original_result_without_writes(tmp_path):
    flow = build_config(tmp_path)
    request, context = change(flow, declaration())
    result = flow.provider.apply_configuration(flow.unit.public_ref, request, context)
    calls = list(flow.client.calls)
    later = query_context(flow, declarations=request.declarations)
    flow.client.state["thinkingLevel"] = "externally-changed"
    outcome = flow.provider.query_change(flow.unit.public_ref, "operation-config", later)
    assert outcome.overall_outcome == "applied"
    assert outcome.item_results[0].confirmation["operationRef"] == "operation-config"
    assert flow.client.calls == calls  # queries never write


def test_foreign_or_incomplete_evidence_ports_stay_unready(tmp_path):
    flow = build_config(tmp_path)
    impostor = PiRuntimeProvider(definition_ref=DEFINITION, implementation_digest=DIGEST,
                                 unit_records=flow.records, projection=flow.projection,
                                 verifier=flow.issuer, channel_factory=flow.factory,
                                 configuration_evidence=JournallingEvidence())
    # a second evidence store is never the records' owner port: never advertised
    assert "apply_configuration" not in impostor.descriptor.supported_methods
    assert flow.records.configuration_evidence is flow.evidence
    with pytest.raises(PiProviderRefused):
        impostor.apply_configuration(flow.unit.public_ref, object(), None)
    bare = PiRuntimeProvider(definition_ref=DEFINITION, implementation_digest=DIGEST,
                             unit_records=flow.records, projection=flow.projection,
                             verifier=flow.issuer, channel_factory=flow.factory)
    assert "apply_configuration" not in bare.descriptor.supported_methods
    assert all(description.support_status == "unknown" and description.confirmation == "none"
               for description in bare.describe_configuration(flow.unit.public_ref))


def test_forged_unit_reference_never_reaches_claim_or_write(tmp_path):
    flow = build_config(tmp_path)
    request, context = change(flow, declaration())
    for forged in ({**flow.unit.public_ref, "unitId": "unit-other"},
                   {**flow.unit.public_ref, "sourceRevision": "forged"}):
        # records/projection refusals surface unchanged through the trusted read
        with pytest.raises((PiProviderRefused, RuntimeError, UnitRecordsRefused)):
            flow.provider.apply_configuration(forged, request, context)
    assert flow.client.calls.count("dispatch") == 0
    assert flow.evidence.captured == {}
    with pytest.raises((PiProviderRefused, RuntimeError, UnitRecordsRefused)):
        flow.provider.query_change({**flow.unit.public_ref, "unitId": "unit-other"},
                                   "operation-config", query_context(flow))


def test_external_native_change_between_reads_fails_dispatch(tmp_path):
    flow = build_config(tmp_path)
    request, context = change(flow, declaration())
    original_command = flow.client.command
    observed = []
    flipped = False

    def external_edit(command, **fields):
        nonlocal flipped
        observed.append(command)
        # observed[0] is the apply's preliminary read; the before-dispatch read
        # (observed[1]) lands after an external native write
        if len(observed) == 2 and not flipped:
            flipped = True
            flow.client.state["thinkingLevel"] = "external-1f"
        if len(observed) >= 3 and flipped:
            flow.client.state["thinkingLevel"] = "off"  # a later read may observe a settled state
        return original_command(command, **fields)

    flow.client.command = external_edit
    result = flow.provider.apply_configuration(flow.unit.public_ref, request, context)
    assert result.overall_outcome == "unknown"
    assert flow.client.calls.count("dispatch") == 0
    assert flow.evidence.captured == {}
    # the held attempt keeps the scope fence: a second apply with fresh authority
    # can never dispatch again
    broadcast, second_context = change(flow, declaration())
    assert broadcast.expected_configuration_revision == request.expected_configuration_revision
    with pytest.raises(Exception, match="cannot dispatch again"):
        flow.provider.apply_configuration(flow.unit.public_ref, broadcast, second_context)
    assert flow.client.calls.count("dispatch") == 0
