#!/usr/bin/env python3
"""Generate the shared cross-language wire vectors (Python codec is authority).

Writes tests/contracts/vectors/open-environment.json. The TypeScript mirror
test asserts byte-identical output for every case; regenerating without a
contract-version bump is a freeze violation.
"""
from __future__ import annotations

import json
import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from ordessa_environment_api import (  # noqa: E402
    CONTRACT_VERSION,
    ActivityReceipt,
    ActivationReceipt,
    BindingSnapshot,
    CanonicalFactTarget,
    ChangeReservation,
    CurrentFactView,
    DataAreaDescriptor,
    FingerprintDescriptor,
    GuaranteeLevel,
    HostDialogRequest,
    HostDialogResult,
    HostDialogStatus,
    InputCapture,
    PersistentReference,
    RecoveryBinding,
    ReferenceStatus,
    RequestKey,
    RevisionSelector,
    SecretRef,
    SequenceTriple,
    UnclassifiedDeliveryFact,
)
from ordessa_environment_api.codec import encode_envelope  # noqa: E402
from ordessa_environment_api.identity import ActivationRef  # noqa: E402

WS = CanonicalFactTarget(realm="workspace", identity_namespace="ordessa.workspace", stable_entity_id="ws-main")
SKILL = CanonicalFactTarget(realm="resource", identity_namespace="ordessa.skills", stable_entity_id="skill-x")
ACT = ActivationRef(environment="env-a", plugin_id="ordessa.harness", generation=7)

cases = [
    ("request-key", "request-key", RequestKey(
        environment_namespace="prod-root", principal_scope="user:local:a1", request_id="req-0001",
        comparison={"input": "a" * 64, "binding": "b" * 64})),
    ("authority-key", "authority-key", dict(
        authority_kind="session-config", target=WS)),
    ("binding-snapshot", "binding-snapshot", BindingSnapshot(
        environment="env-a", logical_surface="codex.session", provider_activation=ACT,
        transport_contract="acp/1", environment_context_revision="ctx-12",
        grant_refs=("grant-read",), guarantee=GuaranteeLevel.RELIABLE,
        binding_digest="c" * 64, native_axis={"observed": "rev-3"})),
    ("activity-receipt", "activity-receipt", ActivityReceipt(
        request=RequestKey(environment_namespace="prod-root", principal_scope="user:local:a1",
                           request_id="req-0002"),
        issued_revision="rev-41", delivery="acknowledged",
        safe_summary={"turns": 1},
        sequences=SequenceTriple(source_revision="n-88", ingest_sequence=4,
                                 environment_knowledge_revision=12))),
    ("current-fact", "current-fact", CurrentFactView(
        outcome="concluded", revision=5, conflicts=(), obligations=())),
    ("current-fact-disputed", "current-fact", CurrentFactView(
        outcome="disputed", revision=6, conflicts=("seq-conflict-9",), obligations=("scope-1",))),
    ("persistent-reference", "persistent-reference", PersistentReference(
        relation_id="rel-1", source_key=WS, source_revision="rev-9", target_key=SKILL,
        revision_selector=RevisionSelector(op="exact", revision="3"),
        declaring_owner_domain="ordessa.profile", policy_contract_id="profile.facet",
        policy_contract_version=2, operation_id="op-77",
        source_commit_evidence="sha256:abcd1234", status=ReferenceStatus.PUBLISHED,
        coverage_epoch=1)),
    ("change-reservation", "change-reservation", ChangeReservation(
        reservation_id="res-5", target_key=SKILL, expected_revision="3", change_kind="delete",
        operation_id="op-78", refused_relations=("rel-1",))),
    ("input-capture", "input-capture", InputCapture(
        content_digest="d" * 64, attachment_digests=("e" * 64,), config_operation_ids=("op-1",),
        base_revision="rev-40", handles={"draft": "content-ref-1"})),
    ("fingerprint", "fingerprint", FingerprintDescriptor(
        algorithm="hmac-sha256", key_id="k-2026-04", comparison_scope="request-input")),
    ("recovery-binding", "recovery-binding", RecoveryBinding(
        environment="env-a", binding_id="rb-3", native_authority="codex",
        native_owner_identity="owner-1", native_session_id="s-9", native_generation=2,
        evidence_kind="history-read", principal="user:local:a1",
        continuity={"rollout": "ok"})),
    ("unclassified-delivery", "unclassified-delivery", UnclassifiedDeliveryFact(
        environment="env-a", fact_id="udf-1", source_identity="codex:stream",
        correlated_object="obj-2", ingest_revision=44, safe_digest="f" * 32,
        budget_used=3, budget_max=64)),
    ("data-area", "data-area", DataAreaDescriptor(
        area_id="area-1", namespace="ordessa.skills.store", owner_domain="ordessa.skills",
        backend_kind="sqlite", supported_schema_range="1-3", current_schema_evidence="3",
        access="write", persistence_guarantee="durable", retention="keep")),
    ("secret-ref", "secret-ref", SecretRef(
        ref="sec-9", revision="r-2", owner_namespace="ordessa.model-provider",
        access_purpose="provider-auth")),
    ("host-dialog-request", "host-dialog-request", HostDialogRequest(
        operation_id="op-90", caller_activation="ordessa.profile", caller_generation=3,
        scope="window-1", purpose="choose-project-dir", options=())),
    ("host-dialog-result-cancelled", "host-dialog-result", HostDialogResult(
        operation_id="op-90", status=HostDialogStatus.CANCELLED)),
    ("activation-receipt", "activation-receipt", ActivationReceipt(
        activation=ACT, published_contribution_revision="cr-5",
        settlement_notes=("artifact-cleanup-pending",))),
]

vectors = {
    "contractVersion": CONTRACT_VERSION,
    "authority": "python/ordessa_environment_api.codec",
    "note": "frozen by spec 026 order 002; TS mirror must match byte-for-byte",
    "cases": [{"name": n, "kind": k, "encoded": encode_envelope(k, p)} for n, k, p in cases],
}

out = pathlib.Path(__file__).resolve().parents[4] / "tests" / "contracts" / "vectors" / "open-environment.json"
out.write_text(json.dumps(vectors, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"wrote {out} with {len(cases)} cases")
