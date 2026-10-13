"""Claude family native evidence ports over the SAME owner observations.

These are the production evidence port implementations the deployment composes
into its existing UnitRecords constructor (``native_unit_evidence`` /
``termination_evidence`` / ``configuration_evidence``). They verify only what
this owner's own effects actually observed, bound to the exact original
unit/action/correlation: a caller string, a copied reference or a replay is
never proof, and a confirmed outcome stores the port's OWN provenance refs
(never caller-supplied values). The evidence store is process-local; a cold
restart re-verifies through fresh authorized reads under the frozen records
contracts. No secret, token, command line or handle is ever stored here.
"""
from __future__ import annotations

import hashlib
from typing import Any, Mapping

from ordessa_execution_api.environment.operations import safe_json, sealed_mapping

UNIT_CONFIRMATION_VERSION = "harness-unit-confirmation/1"
TERMINATION_ACTIONS = ("stop", "release")


class ClaudeEvidenceRefused(RuntimeError):
    code = "CLAUDE_EVIDENCE_REFUSED"


def _canonical(value: Any) -> str:
    try:
        return safe_json(value)
    except (TypeError, ValueError) as error:
        raise ClaudeEvidenceRefused("owner evidence value is not JSON-encodable") from error


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode()).hexdigest()


def _bounded_text(value, name: str) -> str:
    if (not isinstance(value, str) or not value or len(value) > 512
            or any(ord(c) < 32 for c in value)):
        raise ClaudeEvidenceRefused("owner evidence %s is invalid" % name)
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError as error:
        raise ClaudeEvidenceRefused("owner evidence %s is invalid" % name) from error
    return value


def _provenance_ref(value, name: str) -> Mapping:
    if not isinstance(value, Mapping) or set(value) != {
            "environmentNamespace", "ownerProviderRef", "sourceRevision", "ref"}:
        raise ClaudeEvidenceRefused("owner evidence %s must be an owner provenance ref" % name)
    _bounded_text(value["environmentNamespace"], "%s environmentNamespace" % name)
    _bounded_text(value["sourceRevision"], "%s sourceRevision" % name)
    _bounded_text(value["ref"], "%s ref" % name)
    if not isinstance(value["ownerProviderRef"], Mapping):
        raise ClaudeEvidenceRefused("owner evidence %s owner differs" % name)
    return value


def _observation_facts(observation) -> dict:
    if not isinstance(observation, Mapping) or not observation:
        raise ClaudeEvidenceRefused("termination observation must carry its facts")
    plain = {}
    for key, value in observation.items():
        if (not isinstance(key, str) or not key or len(key) > 128 or key.strip() != key
                or any(ord(c) < 32 for c in key)):
            raise ClaudeEvidenceRefused("termination observation key is invalid")
        if not isinstance(value, str):
            raise ClaudeEvidenceRefused("termination observation fact must be a string")
        _bounded_text(value, "termination observation value")
        plain[key] = value
    return plain


def _plain_mapping(canonical_text):
    """Parse a canonical JSON text back into a plain mapping."""
    import json
    try:
        parsed = json.loads(canonical_text)
    except (TypeError, ValueError) as error:
        raise ClaudeEvidenceRefused("owner evidence mapping is not parseable") from error
    if not isinstance(parsed, dict):
        raise ClaudeEvidenceRefused("owner evidence mapping is not an object")
    return parsed


def _native_request_binding(native_request):
    if not isinstance(native_request, Mapping):
        raise ClaudeEvidenceRefused("native configuration request binding required")
    request = _canonical(native_request)
    parsed = _plain_mapping(request)
    if set(parsed) != {"requestId", "digest"}:
        raise ClaudeEvidenceRefused("native configuration request binding required")
    return sealed_mapping(parsed)


class ClaudeNativeUnitEvidence:
    """``NativeUnitEvidencePort``: original same-pipe initialize receipt only.

    ``observe_binding`` is the owner's own start-effect birth record: it binds
    the observed native init identity to the exact unit and start correlation.
    ``verify_unit_binding`` confirms ONLY that birth record and returns the
    versioned proof shape the journal seals. An ACK, a session selector,
    ``default`` or any never-observed evidence is always refused.
    """

    def __init__(self):
        self._bindings: dict[tuple[str, str], Mapping] = {}

    def observe_binding(self, unit, correlation, *, session_id, process_ref,
                        transport_ref, initialization_ref) -> str:
        correlation = _bounded_text(correlation, "start correlation")
        session_id = _bounded_text(session_id, "native init session")
        if session_id == "default":
            raise ClaudeEvidenceRefused("native init session selector is not an identity")
        _provenance_ref(process_ref, "processRef")
        _provenance_ref(transport_ref, "transportRef")
        _provenance_ref(initialization_ref, "initializationRef")
        birth = sealed_mapping({"unitRef": unit.public_ref,
                                "creationCorrelation": correlation,
                                "sessionId": session_id,
                                "processRef": process_ref,
                                "transportRef": transport_ref,
                                "initializationRef": initialization_ref})
        digest = _digest(birth)
        evidence = "claude-native-unit/" + digest.split(":", 1)[1]
        key = (_canonical(unit.public_ref), correlation)
        previous = self._bindings.get(key)
        if previous is not None and previous["evidence"] != evidence:
            raise ClaudeEvidenceRefused("observed native init differs from this original start")
        # The journal's proof carries the evidence reference as a full owner
        # provenance ref; the string form stays the port's birth-lookup key.
        evidence_ref = sealed_mapping({
            "environmentNamespace": unit.public_ref["environmentNamespace"],
            "ownerProviderRef": unit.public_ref["ownerProviderRef"],
            "sourceRevision": digest,
            "ref": evidence})
        self._bindings[key] = {"evidence": evidence, "birth": birth, "evidenceRef": evidence_ref}
        return evidence

    def verify_unit_binding(self, unit, creation_correlation, evidence) -> Mapping:
        # The journal round-trips the stored proof, whose evidenceRef is the
        # full provenance mapping; the birth lookup itself stays the string ref.
        if isinstance(evidence, Mapping):
            try:
                evidence = evidence["ref"]
            except (KeyError, TypeError):
                evidence = None
        if (not isinstance(creation_correlation, str) or not creation_correlation
                or not isinstance(evidence, str) or not evidence):
            raise ClaudeEvidenceRefused("original native Unit evidence identity required")
        record = self._bindings.get((_canonical(unit.public_ref), creation_correlation))
        if record is None or record["evidence"] != evidence:
            raise ClaudeEvidenceRefused("original native Unit evidence is missing or forged")
        birth = record["birth"]
        return sealed_mapping({"contractVersion": UNIT_CONFIRMATION_VERSION,
                              "unitRef": birth["unitRef"],
                              "creationCorrelation": birth["creationCorrelation"],
                              "processRef": birth["processRef"],
                              "transportRef": birth["transportRef"],
                              "initializationRef": birth["initializationRef"],
                              "evidenceRef": record["evidenceRef"]})


class ClaudeTerminationEvidence:
    """``NativeTerminationEvidencePort`` for the stop/release action family.

    ``observe`` is called by the actual stop/release effect at the moment the
    owned channel was observed acting. ``verify_termination`` confirms only an
    observation identical to that birth record under the exact (unit, action)
    pair and correlation; a caller-fabricated mapping is always refused and
    never stored. The returned refs are this port's own provenance strings.
    """

    def __init__(self):
        self._observations: dict[tuple[str, str], Mapping] = {}

    def observe(self, unit, action, correlation, observation) -> Mapping:
        if action not in TERMINATION_ACTIONS:
            raise ClaudeEvidenceRefused("termination evidence exists for stop and release only")
        correlation = _bounded_text(correlation, "termination correlation")
        plain = _observation_facts(observation)
        birth = sealed_mapping({"unitRef": unit.public_ref, "action": action,
                                "correlation": correlation, "observation": plain})
        digest = _digest(birth)
        record = {"digest": digest, "correlation": correlation, "birth": birth,
                  "refs": {"terminationEvidenceRef": "claude-termination/" + digest.split(":", 1)[1],
                           "action": action}}
        self._observations[(_canonical(unit.public_ref), action)] = record
        return record["refs"]

    def verify_termination(self, unit, action, correlation, evidence) -> Mapping:
        if action not in TERMINATION_ACTIONS:
            raise ClaudeEvidenceRefused("termination evidence exists for stop and release only")
        if not isinstance(evidence, Mapping) or not evidence:
            raise ClaudeEvidenceRefused("termination evidence identity required")
        correlation = _bounded_text(correlation, "termination correlation")
        record = self._observations.get((_canonical(unit.public_ref), action))
        if record is None:
            raise ClaudeEvidenceRefused("termination evidence is missing or forged")
        if correlation != record["correlation"]:
            raise ClaudeEvidenceRefused("termination evidence belongs to another correlation")
        if _canonical(evidence) != _canonical(record["birth"]["observation"]):
            raise ClaudeEvidenceRefused("termination evidence differs from the observed effect")
        return sealed_mapping(record["refs"])


class ClaudeConfigurationEvidence:
    """``NativeConfigurationEvidencePort``: original receipt+readback capture.

    ``capture_configuration`` seals the original readback evidence at owner
    confirmation time and returns its own evidence reference.
    ``verify_configuration`` reconstructs only that one original proof for the
    exact (unit, identity, native request) tuple — the journal stores what this
    port returns; caller strings are never proof.
    """

    def __init__(self):
        self._captures: dict[str, Mapping] = {}

    def capture_configuration(self, unit, identity, native_request, readback) -> str:
        identity = _canonical(identity)
        request = _native_request_binding(native_request)
        native_request_id = request["requestId"]
        if (type(native_request_id) not in (str, int) or isinstance(native_request_id, bool)
                or (isinstance(native_request_id, str) and not native_request_id)):
            raise ClaudeEvidenceRefused("native configuration request identity required")
        digest = _bounded_text(request["digest"], "native request digest")
        if not digest.startswith("sha256:") or len(digest) != 71:
            raise ClaudeEvidenceRefused("native request digest shape differs")
        ref = "claude-config/" + _digest({"unitRef": _canonical(unit.public_ref),
                                          "identity": identity,
                                          "nativeRequest": request,
                                          "readback": _canonical(readback)}).split(":", 1)[1]
        self._captures[ref] = sealed_mapping({"identity": _plain_mapping(identity),
                                              "nativeRequest": request,
                                              "readback": _plain_mapping(_canonical(readback))})
        return ref

    def verify_configuration(self, unit, identity, native_request_id, native_request_digest,
                             evidence) -> Mapping:
        if (not isinstance(evidence, str) or not evidence.startswith("claude-config/")
                or not isinstance(native_request_digest, str)):
            raise ClaudeEvidenceRefused("original configuration evidence identity required")
        captured = self._captures.get(evidence)
        if captured is None:
            raise ClaudeEvidenceRefused("original native configuration confirmation unavailable")
        identity = _plain_mapping(_canonical(identity))
        request = captured["nativeRequest"]
        if (type(request["requestId"]) is not type(native_request_id)
                or request["requestId"] != native_request_id
                or request["digest"] != native_request_digest):
            raise ClaudeEvidenceRefused("native configuration request identity differs")
        stored_identity = captured["identity"]
        for field in ("operationRef", "unitRef", "scopeRef", "requestDigest"):
            if identity.get(field) != stored_identity.get(field):
                raise ClaudeEvidenceRefused("configuration identity differs from original capture")
        return sealed_mapping({"operationRef": stored_identity["operationRef"],
                               "unitRef": stored_identity["unitRef"],
                               "scopeRef": stored_identity["scopeRef"],
                               "requestDigest": stored_identity["requestDigest"],
                               "nativeRequestId": request["requestId"],
                               "nativeRequestDigest": native_request_digest,
                               "evidenceRef": evidence})
