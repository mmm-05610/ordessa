"""Claude family configuration fact confirmation over the original ledger.

Session-local ``claude.model`` changes are dispatched through the provider's
fenced SDK transport; the original native control request is bound before its
actual write by the transport pre-send listener, and a confirmation exists
only as a fresh native readback observation verified against the SAME native
session binding. An ACK alone is never applied: it leaves the original
configuration attempt unknown, keeps the scope fence and is reported as an
unknown item outcome. ``expectedConfigurationRevision`` is preserved end to
end: the face refuses an unusable observation before consuming anything,
re-checks the same revision immediately before dispatch and the ledger keeps
it in the original attempt identity. ``queryChange`` only reports existing
original attempts; it never infers outcomes from the current configuration.
"""
from __future__ import annotations

import hashlib
import threading
from datetime import datetime, timezone
from typing import Mapping

from ordessa_environment_api.operations import safe_json
from pacthold.agents.public import (
    ConfigurationChangeResult, ConfigurationDescription, ConfigurationItemResult,
    ConfigurationRevisionConflict, ConfigurationSnapshot, ConfigurationUnsupported,
)
from ordessa_harness_api.model_compilation import AdapterContext, TargetHandle
from .acp_model_configuration import ClaudeAdapter

CONFIGURATION_KIND = "claude.model"
CONFIGURATION_SCHEMA = "1"
MODEL_SCHEMA = {"type": "object",
                "properties": {"model": {"type": "string", "minLength": 1, "maxLength": 256}},
                "additionalProperties": False, "minProperties": 1}


class ClaudeConfigurationRefused(ConfigurationUnsupported):
    code = "CLAUDE_CONFIGURATION_REFUSED"


def _now():
    return datetime.now(timezone.utc).isoformat()


def _digest_facts(value) -> str:
    return "sha256:" + hashlib.sha256(safe_json(value).encode()).hexdigest()


def _valid_model(model) -> bool:
    return (isinstance(model, str) and bool(model) and len(model) <= 256
            and model.strip() == model and not any(ord(c) < 32 for c in model))


def _valid_session(session) -> bool:
    return (isinstance(session, str) and bool(session) and len(session) <= 512
            and session != "default" and session.strip() == session
            and not any(ord(c) < 32 for c in session))


class ClaudeConfigurationFace:
    """Management face for session-local model facts on the original ledger.

    Explicitly injected ports only (none inferred): ``records`` is the
    deployment's UnitRecords owner with its ``configuration_evidence`` port;
    ``projection`` reads only owner reads; ``session_owner`` is the native
    SDK session owner with ``session_apply_model(unit, action, payload,
    context)`` (the ONE native dispatch per batch through the unit's fenced
    transport), ``observe_model(unit)`` and ``observe_session(unit)`` as pure
    actual observations. ``dispatch_listener(unit_ref)`` arms the ledger's
    pre-send binding hook for that unit's fenced transport.
    """

    def __init__(self, *, records, verifier, projection, session_owner):
        self.records, self.verifier, self.projection, self.session_owner = \
            records, verifier, projection, session_owner
        self._lock = threading.RLock()
        self._waiters: dict[str, dict] = {}
        ledger_methods = ("begin_configuration_change", "bind_configuration_dispatch",
                          "record_configuration_change", "query_configuration_change")
        if any(not callable(getattr(records, name, None)) for name in ledger_methods):
            raise ClaudeConfigurationRefused("original configuration ledger methods required")
        evidence = records.configuration_evidence
        if any(not callable(getattr(evidence, name, None))
               for name in ("verify_configuration", "capture_configuration")):
            raise ClaudeConfigurationRefused("native configuration evidence owner required")
        if getattr(projection, "records", None) is not records:
            raise ClaudeConfigurationRefused("configuration face requires the owner projection")
        if any(not callable(getattr(session_owner, name, None))
               for name in ("session_apply_model", "observe_model", "observe_session")):
            raise ClaudeConfigurationRefused("native session configuration owner required")
        # Explicit composition: the session owner's fenced transports carry
        # this face's per-unit pre-send listeners (the ledger bind hook).
        binder = getattr(session_owner, "bind_face", None)
        if callable(binder):
            binder(self)

    @property
    def ready(self) -> bool:
        return True

    # -- description -----------------------------------------------------------------
    def describe(self, unit_ref):
        self.projection.read_unit(unit_ref)
        return (ConfigurationDescription(
            CONFIGURATION_KIND, CONFIGURATION_SCHEMA, MODEL_SCHEMA,
            ("value", "reset"), "session", ("live",), "readback", "supported"),)

    # -- actual observation --------------------------------------------------------------
    def _observed_model(self, unit):
        observation = self.session_owner.observe_model(unit)
        if observation is None:
            return None
        if not isinstance(observation, Mapping):
            raise ClaudeConfigurationRefused("native model observation is not a fact mapping")
        model = observation.get("model")
        if model is not None and not _valid_model(model):
            raise ClaudeConfigurationRefused("native model fact is invalid")
        return model

    def _observed_session(self, unit):
        session = self.session_owner.observe_session(unit)
        if session is not None and not _valid_session(session):
            raise ClaudeConfigurationRefused("native session fact is invalid")
        return session

    def _snapshot(self, unit_ref):
        unit = self.projection.read_unit(unit_ref)
        binding = self.projection.read_session(unit_ref)
        if binding.state != "confirmed":
            raise ClaudeConfigurationRefused("confirmed native session required for model facts")
        model = self._observed_model(unit)
        session = self._observed_session(unit)
        observed = {"model": model}
        if session is not None:
            observed["nativeSessionId"] = session
        unknown = tuple(name for name, value in (("model", model),
                                                 ("nativeSessionId", session)) if value is None)
        revision = None if model is None else _digest_facts(observed)
        environment = unit_ref["environmentNamespace"]
        snapshot = ConfigurationSnapshot(
            unit_ref, unit.configuration_target_ref, revision, _now(),
            {} if model is None else {"model": model}, unknown,
            {"environmentNamespace": environment,
             "evidenceRef": "claude-model-observation/" + _digest_facts(observed).split(":", 1)[1]},
            "ownerSerialized" if model is not None else "unavailable")
        return unit, binding, snapshot

    def inspect(self, unit_ref):
        _, _, snapshot = self._snapshot(unit_ref)
        return snapshot

    # -- apply -----------------------------------------------------------------------------
    def apply(self, unit_ref, change_request, invocation_context):
        if not hasattr(change_request, "declarations"):
            raise ClaudeConfigurationRefused("typed fixed change request required")
        with self._lock:
            return self._apply_locked(unit_ref, change_request, invocation_context)

    def _apply_locked(self, unit_ref, change_request, invocation_context):
        unit, binding, snapshot = self._snapshot(unit_ref)
        if snapshot.source_revision is None or snapshot.comparison_guarantee == "unavailable":
            raise ClaudeConfigurationRefused("configuration fact unavailable; comparison refused")
        if snapshot.source_revision != change_request.expected_configuration_revision:
            raise ConfigurationRevisionConflict("configuration revision differs from native owner")
        compiled = self._compile(change_request)
        facts = invocation_context.facts
        operation_ref = facts["operationRef"]
        # begin consumes the original invocation here; nothing was consumed before.
        ticket = self.records.begin_configuration_change(
            unit.unit_ref, invocation_context, input_digest=facts["inputDigest"],
            expected_revision=change_request.expected_configuration_revision)
        waiter = {"ticket": ticket, "attempt_revision": 1, "native_request": None,
                  "desired": compiled["model"], "action": compiled["action"],
                  "supported": compiled["supported"], "rejected": compiled["rejected"],
                  "finalized": False}
        self._waiters[unit_ref["unitId"]] = waiter
        try:
            # Canonical owner-serialized recheck immediately before dispatch.
            _, _, current = self._snapshot(unit_ref)
            if current.source_revision != change_request.expected_configuration_revision:
                raise ConfigurationRevisionConflict("native configuration changed before dispatch")
            receipt = self.session_owner.session_apply_model(
                unit, compiled["action"],
                {"model": compiled["model"]} if compiled["action"] == "value" else {},
                invocation_context)
            del receipt  # An ACK receipt is bookkeeping only; it confirms nothing itself.
            if waiter["native_request"] is None:
                raise ClaudeConfigurationRefused("no native configuration dispatch was bound")
            attempt = waiter["attempt"]
            model_after = self._observed_model(unit)
            session_after = self._observed_session(unit)
            result = self._conclude(unit, unit_ref, change_request, compiled, waiter, attempt,
                                    model_after, session_after, binding, facts)
        except BaseException as exc:
            try:
                recorded = self.records.record_configuration_change(
                    waiter["ticket"], expected_source_revision=waiter["attempt_revision"],
                    state="unknown")
                waiter["attempt_revision"] = recorded.source_revision
            except Exception:
                pass  # a concurrently concluded original attempt is never downgraded
            self._drop_waiter(unit_ref["unitId"])
            if not isinstance(exc, Exception):
                raise
            return self._unknown_result(operation_ref, change_request.declarations, compiled)
        return result

    def _drop_waiter(self, unit_id):
        self._waiters.pop(unit_id, None)

    # -- native dispatch binding -------------------------------------------------------------
    def dispatch_listener(self, unit_ref):
        """Pre-send binding hook for this unit's fenced SDK transport.

        The fenced transport calls it inside the write barrier BEFORE the
        actual native write; the ledger's bind must finish there. The argument
        is the unit reference (or its unitId); frames that are not the one
        native model-dispatch control request are ignored.
        """
        unit_id = unit_ref["unitId"] if isinstance(unit_ref, Mapping) else unit_ref

        def listen(payload, digest):
            if (not isinstance(payload, Mapping) or payload.get("type") != "control_request"
                    or not isinstance(payload.get("request"), Mapping)
                    or payload["request"].get("subtype") != "set_model"):
                return
            self._bind_dispatch(unit_id, payload, digest)
        return listen

    def _bind_dispatch(self, unit_id, payload, digest):
        with self._lock:
            waiter = self._waiters.get(unit_id)
            if waiter is None or waiter.get("finalized"):
                return  # nothing armed on this exact native write
            request_id = payload.get("request_id")
            if type(request_id) not in (str, int) or isinstance(request_id, bool) or (
                    isinstance(request_id, str) and not request_id):
                raise ClaudeConfigurationRefused("native control request identity required")
            attempt = self.records.bind_configuration_dispatch(
                waiter["ticket"], native_request_id=request_id, native_request_digest=digest)
            waiter["native_request"] = {"requestId": request_id, "digest": digest}
            waiter["attempt"] = attempt
            waiter["attempt_revision"] = attempt.source_revision

    # -- conclusion -----------------------------------------------------------------------------
    def _conclude(self, unit, unit_ref, change_request, compiled, waiter, attempt,
                  model_after, session_after, binding, facts):
        waiters = waiter
        expected_session = binding.native_facts["sessionId"]
        verdict = self._verify(unit_ref, desired=waiters["desired"], observed_model=model_after,
                               session_now=session_after, expected_session=expected_session)
        if verdict != "match":
            waiters["finalized"] = True
            self.records.record_configuration_change(
                waiters["ticket"], expected_source_revision=waiters["attempt_revision"],
                state="unknown")
            self._drop_waiter(unit_ref["unitId"])
            return self._unknown_result(facts["operationRef"], change_request.declarations, compiled)
        evidence_ref = self.records.configuration_evidence.capture_configuration(
            unit, attempt.identity, waiters["native_request"],
            {"model": model_after, "nativeSessionId": session_after})
        identity = attempt.identity
        environment = unit_ref["environmentNamespace"]
        proof = {"operationRef": identity["operationRef"], "unitRef": identity["unitRef"],
                 "scopeRef": identity["scopeRef"], "requestDigest": identity["requestDigest"],
                 "evidenceRef": {"environmentNamespace": environment, "evidenceRef": evidence_ref}}
        items = tuple(
            ConfigurationItemResult(declaration["declarationId"],
                                    "applied" if declaration["declarationId"] in compiled["supported"]
                                    else "rejected",
                                    proof if declaration["declarationId"] in compiled["supported"] else None)
            for declaration in change_request.declarations)
        observed = {"model": model_after}
        if session_after is not None:
            observed["nativeSessionId"] = session_after
        unknown_after = tuple(name for name, value in (("model", model_after),
                              ("nativeSessionId", session_after)) if value is None)
        environment_after = unit_ref["environmentNamespace"]
        snapshot = ConfigurationSnapshot(
            unit_ref, unit.configuration_target_ref,
            None if model_after is None else _digest_facts(observed), _now(),
            {} if model_after is None else {"model": model_after}, unknown_after,
            {"environmentNamespace": environment_after,
             "evidenceRef": "claude-model-observation/" + _digest_facts(observed).split(":", 1)[1]},
            "ownerSerialized" if model_after is not None else "unavailable")
        result = ConfigurationChangeResult(facts["operationRef"], items, snapshot)
        self.records.record_configuration_change(
            waiters["ticket"], expected_source_revision=waiters["attempt_revision"],
            state="confirmed", evidence=evidence_ref)
        self._drop_waiter(unit_ref["unitId"])
        return result

    def _verify(self, unit_ref, *, desired, observed_model, session_now, expected_session):
        # The frozen adapter verdict consumes only facts: desired choice, an
        # actual readback sample and the native session identity evidence.
        adapter = ClaudeAdapter()
        context = AdapterContext(
            TargetHandle("claude-code", "instance", unit_ref["unitId"]),
            "unmeasured", {"native_session_id": expected_session})
        return adapter.verify(context, {
            "desired_model": desired,
            "readback": {} if observed_model is None else {"model": observed_model},
            "native_session_id": session_now}).verdict

    def _unknown_result(self, operation_ref, declarations=(), compiled=None):
        items = []
        for declaration in declarations:
            declaration_id = declaration.get("declarationId") if isinstance(declaration, Mapping) \
                else declaration
            if compiled is not None and declaration_id in compiled["rejected"]:
                outcome = "rejected"
            else:
                outcome = "unknown"
            items.append(ConfigurationItemResult(declaration_id, outcome))
        if not items:
            raise ClaudeConfigurationRefused("original attempt item identities unavailable")
        return ConfigurationChangeResult(operation_ref, tuple(items))

    # -- compile ----------------------------------------------------------------------------------
    def _compile(self, change_request):
        supported, rejected = [], []
        action = model = None
        for declaration in change_request.declarations:
            valid = (declaration.get("configurationKind") == CONFIGURATION_KIND
                     and declaration.get("schemaVersion") == CONFIGURATION_SCHEMA
                     and declaration.get("action") in ("value", "reset")
                     and not declaration.get("resourceRefs"))
            payload = declaration.get("payload")
            if not isinstance(payload, Mapping):
                payload = {}
            if declaration.get("action") == "reset":
                item_action, item_model = "reset", None
                valid = valid and not payload
            elif declaration.get("action") == "value":
                item_action, item_model = "value", payload.get("model")
                valid = valid and set(payload) == {"model"} and _valid_model(item_model)
            else:
                item_action, item_model, valid = None, None, False
            if not valid:
                if declaration.get("requirement") == "required":
                    raise ClaudeConfigurationRefused("required native configuration unsupported")
                rejected.append(declaration["declarationId"])
                continue
            if action is not None and item_action != action:
                raise ClaudeConfigurationRefused("one native model write per batch")
            if item_action == "value" and model is not None and model != item_model:
                raise ClaudeConfigurationRefused("conflicting model values in one batch")
            action, model = item_action, item_model
            supported.append(declaration["declarationId"])
        if not supported:
            raise ClaudeConfigurationRefused("no supported native configuration in this batch")
        return {"action": action, "model": model,
                "supported": frozenset(supported), "rejected": frozenset(rejected)}

    # -- query ----------------------------------------------------------------------------------------
    def query(self, unit_ref, operation_ref, authorized_read_context):
        unit = self.projection.read_unit(unit_ref)
        facts = authorized_read_context.facts
        if facts.get("operationRef") != operation_ref:
            raise ConfigurationRevisionConflict("read authority belongs to another operation")
        with self._lock:
            attempt = self.records.query_configuration_change(
                unit.unit_ref, operation_ref, authorized_read_context,
                input_digest=facts["inputDigest"])
            declaration_ids = _context_declarations(facts)
            if attempt.state == "confirmed":
                return self._confirmed_result(unit_ref, attempt, declaration_ids)
            self._drop_waiter(unit_ref["unitId"])
            return self._unknown_result(facts["operationRef"], declaration_ids)

    def _confirmed_result(self, unit_ref, attempt, declaration_ids):
        confirmation = attempt.confirmation
        environment = unit_ref["environmentNamespace"]
        proof = {"operationRef": confirmation["operationRef"],
                 "unitRef": confirmation["unitRef"],
                 "scopeRef": confirmation["scopeRef"],
                 "requestDigest": confirmation["requestDigest"],
                 "evidenceRef": {"environmentNamespace": environment,
                                 "evidenceRef": confirmation["evidenceRef"]}}
        if not declaration_ids:
            raise ClaudeConfigurationRefused("original attempt declarations unavailable")
        items = tuple(ConfigurationItemResult(name, "applied", proof) for name in declaration_ids)
        return ConfigurationChangeResult(confirmation["operationRef"], items)


def _context_declarations(facts):
    context = facts.get("contextRef")
    declarations = context.get("effectiveDeclarations") if isinstance(context, Mapping) else None
    if isinstance(declarations, (list, tuple)):
        return tuple(item["declarationId"] for item in declarations
                     if isinstance(item, Mapping) and isinstance(item.get("declarationId"), str))
    return ()
