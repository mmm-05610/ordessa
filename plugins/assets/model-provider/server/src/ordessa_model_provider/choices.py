"""The versioned ``modelProvider.*`` choice surface (Z3 T01 increments).

Authored in this line against the frozen target semantics
(``specs/011-z3-model-provider/t00-freeze.md`` §8 for the wire names,
``docs/design/model-provider/contracts.md`` for the Port signatures). The
legacy six ``providerModels.*`` methods and their codes are untouched; the new
surface speaks the new failure-code vocabulary below. Codes the submit gate
owns (``VERSION_UNVERIFIED``, ``TARGET_STALE``, ``RESUME_UNAVAILABLE``,
``CREDENTIAL_UNRESOLVED``, ``PROTOCOL_UNSUPPORTED``) are defined here so the
vocabulary lives in one domain-owned place; the gate (C0/harness-api, see
``api-requests.md`` REQ-Z3-2) raises them on the apply path.

Absence semantics stay fail-closed everywhere: no harness-config port means
"unknown, never supported" and a reconcile that cannot verify answers
``unknown-outcome``; an explicitly requested overlay-revision check without an
overlay port refuses ``REFERENCE_STATE_UNKNOWN`` instead of guessing.

``begin_turn_application`` is the thin submit gate of the 021 appendix §2: it
consumes the session's *frozen* intent and delegates the single real
application to the injected :class:`~ordessa_model_provider.turn_application.TurnApplicationPort`.
It applies nothing itself and never falls back to the legacy
``ConfigurationServiceHarnessPort`` pseudo read-back. choose/query/reconcile
keep their contract: choose only queues, query and reconcile only read.
"""
from __future__ import annotations

from typing import Any, Mapping

from ordessa_server.errors import ServerError
from ordessa_model_provider.next_turn import (
    OBSERVED_CONFIRMED, OBSERVED_MISMATCH, OUTCOME_PENDING, SESSION_REF_KEYS,
    NextTurnSelector, TurnFact, session_key_of,
)
from ordessa_model_provider.ports import (
    ELIGIBILITY_READY, ELIGIBILITY_UNSUPPORTED, REFERENCE_STATE_UNKNOWN,
    SESSION_CONFIG_OUTCOME_UNKNOWN, SessionConfigError,
)
from ordessa_model_provider.turn_application import (
    HANDOVER_UNRESOLVED, INTENT_ROUTE_HANDOVER_FAILED, INTENT_ROUTE_INDEPENDENT,
    INTENT_ROUTE_PROFILE_OVERLAY, INTENT_ROUTES, PORT_OUTCOMES, SUBMIT_NO_INTENT,
    SUBMIT_READY, SUBMIT_REFUSED, SUBMIT_UNKNOWN, ApplicationEvidenceError,
    TurnIntentHandoverError, observed_routing_identity, same_routing_identity,
    submission_operation_key, validated_application,
)

#: The design contract's failure-code table (contracts.md "下一轮提交接缝"),
#: domain-owned constants. Codes raised by this module are noted; the rest are
#: consumed by the submit gate / brand adapters on the apply path.
PROVIDER_NOT_FOUND = "PROVIDER_NOT_FOUND"          # raised here (404)
PROVIDER_ARCHIVED = "PROVIDER_ARCHIVED"            # raised here (409)
MODEL_NOT_FOUND = "MODEL_NOT_FOUND"                # raised here (404)
CREDENTIAL_UNRESOLVED = "CREDENTIAL_UNRESOLVED"    # submit-gate scope
PROTOCOL_UNSUPPORTED = "PROTOCOL_UNSUPPORTED"      # submit-gate scope
ADAPTER_MISSING = "ADAPTER_MISSING"                 # raised here as a reason
VERSION_UNVERIFIED = "VERSION_UNVERIFIED"           # submit-gate scope
SELECTION_UNSUPPORTED = "SELECTION_UNSUPPORTED"     # raised here (422)
CONFIG_REVISION_CONFLICT = "CONFIG_REVISION_CONFLICT"  # raised here (409, save/probe CAS)
TARGET_STALE = "TARGET_STALE"                       # submit-gate scope
RESUME_UNAVAILABLE = "RESUME_UNAVAILABLE"           # submit-gate scope
VERIFICATION_MISMATCH = "VERIFICATION_MISMATCH"     # raised here as a reconcile reason
OPERATION_UNKNOWN = "OPERATION_UNKNOWN"             # raised here (catalogue store failure)

OUTCOME_CONFIRMED = "confirmed"
OUTCOME_REFUSED = "refused"
OUTCOME_UNKNOWN = "unknown-outcome"

_QUEUE_SCOPE = "modelProvider.chooseForSession"
_SUBMIT_SCOPE = "modelProvider.beginTurnApplication"

#: The longest native identity the target strings may carry (the wire's own
#: bounded-string rule, applied to each reference key).
_TARGET_FIELD_LIMIT = 256


def _session_key(target: Mapping[str, Any]) -> tuple[str, ...]:
    missing = [key for key in SESSION_REF_KEYS if not target.get(key)]
    if missing:
        raise ServerError(
            "REQUEST_INVALID",
            "target must carry native " + ", ".join(SESSION_REF_KEYS), status=422,
        )
    return session_key_of(target)


def _submission_target(target: Any) -> dict[str, str]:
    """The frozen §2 target, validated fail-closed.

    Unknown keys, missing keys, non-string and empty values are all refused:
    the submission applies a *native* configuration, so an unrecognized or
    malformed reference must never be guessed into a target (M09).
    """
    if not isinstance(target, Mapping):
        raise ServerError("REQUEST_INVALID", "target must be an object", status=422)
    unknown = sorted(set(target) - set(SESSION_REF_KEYS))
    if unknown:
        raise ServerError(
            "REQUEST_INVALID",
            "target carries unknown fields: " + ", ".join(unknown), status=422)
    resolved: dict[str, str] = {}
    for key in SESSION_REF_KEYS:
        value = target.get(key)
        if not isinstance(value, str) or not (0 < len(value) <= _TARGET_FIELD_LIMIT):
            raise ServerError(
                "REQUEST_INVALID",
                f"target.{key} must be a bounded non-empty string", status=422)
        resolved[key] = value
    return resolved


class ModelChoiceService:
    """Queue/inspect/reconcile for per-session ModelChoices, plus the paged
    catalogue. The pending queue is the ``NextTurnSelector`` (migrated,
    unchanged); this service adds the wire-facing validation and facts."""

    def __init__(self, catalog, *, harness_config_port=None, idempotency=None,
                 overlay_port=None, turn_application_port=None,
                 intent_sink=None) -> None:
        self._catalog = catalog
        self._harness = harness_config_port
        self._idempotency = idempotency
        self._overlay = overlay_port
        #: The ONE real-application entry for the next turn (appendix §3.3).
        #: Absent -> ``begin_turn_application`` refuses typed and applies
        #: nothing; it never falls back to ``self._harness`` (B.2).
        self._turn_application = turn_application_port
        #: 021 appendix §6b.4(a): the OPTIONAL bound-mode intent bridge,
        #: injected by the product composition. When the sink takes an intent
        #: (the session is a registered Profile session) the Profile session
        #: overlay becomes the intent's authority and the queued entry below
        #: is a UI projection only - ``begin_turn_application`` then answers
        #: ``no-intent`` so no second real application can exist. Absent (or
        #: declined) -> the queue stays the authority: unbound semantics are
        #: exactly what they were before this hook.
        self._intent_sink = intent_sink
        self._selector = NextTurnSelector(harness_config_port, catalog)
        #: sequence -> (session_key, session_ref, choice); the reconcile's
        #: operation index (the selector keeps only the newest intent/session).
        self._operations: dict[int, tuple[tuple[str, ...], Mapping[str, Any], Mapping[str, Any]]] = {}
        self._confirmed: dict[tuple[str, ...], dict[str, Any]] = {}
        self._revisions: dict[tuple[str, ...], int] = {}
        #: session_key -> the sequence whose authority was routed to the
        #: session's Profile overlay by the sink. A newer pick overwrites the
        #: mark; only an exact-sequence match suppresses the submit gate.
        self._routed: dict[tuple[str, ...], int] = {}
        #: session_key -> the sequence whose overlay handover FAILED or is
        #: unknown (appendix §6c F2). The intent stays queued with the mark
        #: and the submit gate answers HANDOVER_UNRESOLVED until a newer pick
        #: supersedes the mark - never a silent "unbound" downgrade.
        self._handover_failed: dict[tuple[str, ...], int] = {}

    # -- catalogue -----------------------------------------------------------

    def catalogue(self, include_archived: bool = False, cursor: int | None = None) -> dict[str, Any]:
        """One page of provider-config summaries. A store failure is a typed
        ``OPERATION_UNKNOWN`` - never an empty page (MP-03)."""
        try:
            rows = self._catalog.records.list(include_archived=include_archived)
        except ServerError:
            raise
        except Exception as error:  # noqa: BLE001 - typed, never an empty list
            raise ServerError(
                OPERATION_UNKNOWN, f"catalogue query failed: {error}", status=500,
            ) from error
        start = int(cursor or 0)
        page = 100
        window = rows[start:start + page]
        following = start + len(window)
        return {
            "items": [self._catalog.project(row) for row in window],
            "nextCursor": following if following < len(rows) else None,
        }

    # -- choice facts --------------------------------------------------------

    def inspect_choice(self, target: Mapping[str, Any], choice: Mapping[str, Any]) -> dict[str, Any]:
        """supported | unsupported | unknown for one (session, choice)."""
        key = _session_key(target)
        row = self._validate_choice(key[1], choice)
        version = int(row["version"])
        if self._harness is None:
            return {"verdict": "unknown", "reason": ADAPTER_MISSING,
                    "providerConfigId": row["id"], "configVersion": version}
        eligibility = self._harness.eligibility(
            key[1], {"providerConfigId": row["id"], "version": version}, dict(target))
        if eligibility == ELIGIBILITY_READY:
            verdict, reason = "supported", None
        elif eligibility == ELIGIBILITY_UNSUPPORTED:
            verdict, reason = "unsupported", eligibility
        else:
            verdict, reason = "unknown", str(eligibility)
        return {"verdict": verdict, "reason": reason,
                "providerConfigId": row["id"], "configVersion": version}

    def choose_for_session(
        self, target: Mapping[str, Any], choice: Mapping[str, Any],
        operation_key: str, expected_overlay_revision: str | None = None,
    ) -> dict[str, Any]:
        """Queue the next-turn intent. Queuing applies nothing and sends
        nothing (MP-05); the queue's own validation refuses unsupported or
        unverifiable selections instead of parking a doomed intent."""
        key = _session_key(target)
        row = self._validate_choice(key[1], choice)
        if self._harness is None:
            raise ServerError(
                SELECTION_UNSUPPORTED,
                "no harness-config adapter port; eligibility is unknown and cannot be queued",
                status=422,
            )
        eligibility = self._harness.eligibility(
            key[1], {"providerConfigId": row["id"], "version": int(row["version"])},
            dict(target))
        if eligibility != ELIGIBILITY_READY:
            raise ServerError(
                SELECTION_UNSUPPORTED, f"eligibility={eligibility}", status=422)
        if expected_overlay_revision is not None and self._overlay_port is None:
            # An explicitly requested overlay CAS cannot be verified: fail
            # closed, never queue against a guessed overlay state (MP-08).
            raise ServerError(
                REFERENCE_STATE_UNKNOWN,
                "overlay revision requested but the overlay port is absent",
                status=409,
            )
        #: The Profile overlay registry is Profile's (Z1); injected via the
        #: composition when present. Queueing a *session* override does not
        #: need it; only the explicit revision check above does.
        digest_payload = {
            "target": dict(target), "choice": dict(choice),
            "expectedOverlayRevision": expected_overlay_revision,
        }
        body = {
            "outcome": OUTCOME_PENDING, "target": dict(target),
            "choice": dict(choice), "operationKey": operation_key,
        }
        if self._idempotency is not None:
            from ordessa_server.records import canonical, digest

            request_digest = digest(digest_payload)
            prior = self._idempotency.get(_QUEUE_SCOPE, operation_key, request_digest)
            if prior:
                return prior[1]
        sequence = self._selector.queue(
            dict(target),
            {"providerConfigId": row["id"], "modelId": choice["modelId"],
             "version": int(row["version"])},
            source="session-override")
        body["sequence"] = sequence
        self._operations[sequence] = (key, dict(target), dict(choice))
        self._revisions[key] = sequence
        # -- §6b.4(a) + §6c F2: offer the frozen intent to the bound-mode
        #    bridge. The sink answers three ways: True (the Profile overlay
        #    took it), False (genuinely unbound - the queue keeps the
        #    authority), or a typed handover failure/unknown (the intent stays
        #    queued WITH the mark; the submit gate will refuse it). Only an
        #    honest False may read as independent - a failure never folds.
        route, intent_reason = INTENT_ROUTE_INDEPENDENT, None
        if self._intent_sink is not None:
            offer = getattr(self._intent_sink, "offer_turn_intent", None)
            if callable(offer):
                try:
                    offered = bool(offer(dict(target), operation_key=operation_key,
                                         sequence=sequence,
                                         intent={"sequence": sequence,
                                                 "source": "session-override",
                                                 "choice": {"providerConfigId": row["id"],
                                                            "modelId": choice["modelId"],
                                                            "version": int(row["version"])}}))
                except TurnIntentHandoverError as error:
                    # §6c F2.1: bound but the handover failed or is unknown.
                    self._handover_failed[key] = sequence
                    self._routed.pop(key, None)
                    route = INTENT_ROUTE_HANDOVER_FAILED
                    intent_reason = str(error) or HANDOVER_UNRESOLVED
                except Exception as error:  # noqa: BLE001 - unknown is never "unbound"
                    self._handover_failed[key] = sequence
                    self._routed.pop(key, None)
                    route = INTENT_ROUTE_HANDOVER_FAILED
                    intent_reason = f"{type(error).__name__}: {error}"
                else:
                    # a newer pick supersedes any older handover-failure mark
                    self._handover_failed.pop(key, None)
                    if offered:
                        self._routed[key] = sequence
                        route = INTENT_ROUTE_PROFILE_OVERLAY
        body["intentRoute"] = route
        if intent_reason is not None:
            body["intentReason"] = intent_reason
        if self._idempotency is not None:
            from ordessa_server.records import digest

            self._idempotency.save(
                _QUEUE_SCOPE, operation_key, digest(digest_payload), 200, body)
        return body

    def handover_for_native(self, *, harness_id: str, native_session_id: str, accept) -> None:
        """Transfer an older independent intent before a new Profile pick.

        No native effect, no new queue and no guessed server identity: this
        instance must have exactly one matching, validated pending target.
        The recipient writes idempotently; only that exact sequence is marked.
        """
        candidates = {}
        for key, target, _choice in self._operations.values():
            if key[1:3] == (harness_id, native_session_id):
                intent = self._selector.intent(target)
                if intent is not None:
                    candidates[key] = (target, intent)
        if len(candidates) > 1:
            raise TurnIntentHandoverError("ambiguous native model intent")
        for key, (target, intent) in candidates.items():
            sequence = int(intent["sequence"])
            if self._routed.get(key) == sequence:
                return
            if self._handover_failed.get(key) == sequence or self._selector.blocked(target):
                raise TurnIntentHandoverError(HANDOVER_UNRESOLVED)
            stale = self._stale_intent(intent["choice"])
            if stale:
                raise TurnIntentHandoverError(stale)
            accept(sequence, dict(intent["choice"]))
            current = self._selector.intent(target)
            if current is None or current["sequence"] != sequence:
                raise TurnIntentHandoverError("model intent changed during handover")
            self._routed[key] = sequence

    def inspect(self, target: Mapping[str, Any]) -> dict[str, Any]:
        key = _session_key(target)
        pending = self._selector.pending(target)
        fact = self._confirmed.get(key)
        sequence = self._revisions.get(key)
        # History is not the current native configuration. In particular a
        # Profile (or native UI) can change the model without this queue.
        current = None
        try:
            observed = self._harness.read_back(target)
            if isinstance(observed.get("model"), str) and observed["model"]:
                current = {"modelId": observed["model"],
                           "provider": observed.get("provider")}
        except Exception:
            pass  # Unknown read-back never falls back to a historical fact.
        return {
            "current": current,
            "desired": dict(pending) if pending else None,
            "lastConfirmed": dict(fact) if fact else None,
            "revision": self._revisions.get(key),
            # §6c F2.2: the newest intent's handover fate, for the frontend's
            # send adjudication (None when nothing is queued).
            "intentRoute": self._intent_route(key) if pending else None,
        }

    def _intent_route(self, key: tuple[str, ...],
                      sequence: int | None = None) -> str | None:
        """The route mark of the session's queued intent (§6c F2.2)."""
        if sequence is None:
            sequence = self._revisions.get(key)
        if sequence is None:
            return None
        if self._handover_failed.get(key) == sequence:
            return INTENT_ROUTE_HANDOVER_FAILED
        if self._routed.get(key) == sequence:
            return INTENT_ROUTE_PROFILE_OVERLAY
        return INTENT_ROUTE_INDEPENDENT

    def reconcile(self, target: Mapping[str, Any], operation_id: int) -> dict[str, Any]:
        """Decide an operation's outcome from observed state; nothing here
        retries or re-sends (MP-07)."""
        key = _session_key(target)
        confirmed = self._confirmed.get(key)
        if confirmed is not None and confirmed.get("sequence") == int(operation_id):
            return {"outcome": OUTCOME_CONFIRMED, "turnFact": dict(confirmed)}
        operation = self._operations.get(int(operation_id))
        if self._harness is None:
            return {"outcome": OUTCOME_UNKNOWN, "reason": ADAPTER_MISSING,
                    "promptAllowed": False}
        if operation is None:
            return {"outcome": OUTCOME_UNKNOWN, "reason": OPERATION_UNKNOWN,
                    "promptAllowed": False}
        operation_key, session_ref, choice = operation
        if operation_key != key:
            # another session's sequence: reconcile observes, it never reports
            # across sessions (M09/M12).
            return {"outcome": OUTCOME_UNKNOWN, "reason": OPERATION_UNKNOWN,
                    "promptAllowed": False}
        try:
            read_back = self._harness.read_back(dict(session_ref))
        except SessionConfigError as error:
            return {"outcome": OUTCOME_UNKNOWN, "reason": error.code,
                    "promptAllowed": False}
        if not isinstance(read_back, Mapping):
            return {"outcome": OUTCOME_UNKNOWN, "reason": OPERATION_UNKNOWN,
                    "promptAllowed": False}
        if read_back.get("model") != choice.get("modelId"):
            # the observation proves it did not apply: the unsafe state clears
            # and the intent stays for an explicit retry (FR-06).
            self._selector.observe(dict(session_ref), int(operation_id),
                                   outcome=OBSERVED_MISMATCH)
            return {"outcome": OUTCOME_REFUSED, "reason": VERIFICATION_MISMATCH,
                    "promptAllowed": False}
        fact = self._record_confirmed(key, session_ref, choice, int(operation_id))
        return {"outcome": OUTCOME_CONFIRMED, "turnFact": fact}

    # -- the submit gate (frozen appendix §2) --------------------------------

    def begin_turn_application(self, target: Mapping[str, Any], operation_key: str,
                               expected_sequence: int | None = None,
                               ) -> dict[str, Any]:
        """Consume this session's frozen intent through the one real application.

        The plugin decides *what* to apply and *whether* the answer may be
        believed; the injected ``TurnApplicationPort`` performs the single
        application. Nothing here applies, restarts or prompts on its own, and
        the intent is consumed only by a ``ready`` answer that carries real
        evidence references.
        """
        target = _submission_target(target)
        key = _session_key(target)
        digest_payload = {"target": dict(target), "expectedSequence": expected_sequence}
        if self._idempotency is not None:
            from ordessa_server.records import digest

            request_digest = digest(digest_payload)
            prior = self._idempotency.get(_SUBMIT_SCOPE, operation_key, request_digest)
            if prior:
                return prior[1]  # replay: zero new effects (P10)

        def answer(outcome: str, *, reason: str | None = None,
                   sequence: int | None = None,
                   application: Mapping[str, Any] | None = None) -> dict[str, Any]:
            body = {
                "outcome": outcome, "target": dict(target),
                "operationKey": operation_key, "sequence": sequence,
                "reason": reason, "application": application,
            }
            if self._idempotency is not None:
                from ordessa_server.records import digest

                self._idempotency.save(_SUBMIT_SCOPE, operation_key,
                                       digest(digest_payload), 200, body)
            return body

        # -- a blocked session answers unknown with zero prompt, and does so
        #    without reaching the port: the unsafe state is settled by an
        #    observation, never by a second apply (FR-06, M08).
        blocked = self._selector.blocked(target)
        if blocked is not None:
            return answer(SUBMIT_UNKNOWN, reason=blocked["reason"],
                          sequence=blocked["sequence"])

        intent = self._selector.intent(target)
        if intent is None:
            return answer(SUBMIT_NO_INTENT)

        sequence = int(intent["sequence"])
        choice = dict(intent["choice"])
        if expected_sequence is not None and int(expected_sequence) != sequence:
            # the client named a different intent: a newer pick replaced it, or
            # the answer is out of order. Neither may consume the queued one.
            return answer(SUBMIT_REFUSED, reason=TARGET_STALE, sequence=sequence)

        if self._handover_failed.get(key) == sequence:
            # §6c F2.4: this intent's bound handover failed or is unknown. It
            # must never reach the port (that would be a SECOND apply chain
            # behind the Profile pipeline's back) and never degrade to
            # no-intent: typed refusal, intent kept for an explicit re-pick.
            return answer(SUBMIT_REFUSED, reason=HANDOVER_UNRESOLVED,
                          sequence=sequence)

        if self._routed.get(key) == sequence:
            # §6b.4(a): the Profile session overlay owns this intent (bound
            # mode). The queue entry is a UI projection; the Profile pipeline
            # applies it, so this gate answers no-intent and applies nothing -
            # one real application per send, even against a stale client.
            probe = getattr(self._intent_sink, "is_bound", None)
            try:
                bound = callable(probe) and probe(target)
            except Exception:
                bound = False
            if not bound:
                return answer(SUBMIT_REFUSED, reason=HANDOVER_UNRESOLVED,
                              sequence=sequence)
            return answer(SUBMIT_NO_INTENT, sequence=sequence)

        if self._turn_application is None:
            # No real application entry: refuse typed, apply nothing, keep the
            # intent for an explicit retry. The legacy pseudo read-back port is
            # NOT a fallback (B.2).
            return answer(SUBMIT_REFUSED, reason=ADAPTER_MISSING, sequence=sequence)

        # -- the frozen plan must still describe the catalogue (M10): a
        #    reconfigured/archived/dropped provider config refuses the stale
        #    plan instead of applying a plan built for another version.
        refusal = self._stale_intent(choice)
        if refusal is not None:
            return answer(SUBMIT_REFUSED, reason=refusal, sequence=sequence)

        routing = observed_routing_identity(self._turn_application, target)
        key_for_port = submission_operation_key(
            operation_key, target, sequence=sequence,
            config_version=int(choice["version"]), routing_identity=routing)
        try:
            result = self._turn_application.submit(
                dict(target), operation_key=key_for_port,
                expected_sequence=sequence, intent=dict(intent))
        except SessionConfigError as error:
            if error.code == SESSION_CONFIG_OUTCOME_UNKNOWN:
                return self._undecided(answer, target, sequence, error.code)
            return answer(SUBMIT_REFUSED, reason=error.code, sequence=sequence)
        except Exception as error:  # noqa: BLE001 - undecided, never a crash path
            return self._undecided(
                answer, target, sequence, f"{type(error).__name__}: {error}")

        return self._settled(answer, target, key, sequence, choice, result, routing)

    def _stale_intent(self, choice: Mapping[str, Any]) -> str | None:
        """Why this frozen intent no longer describes the catalogue, if it does
        not. ``None`` means the plan may be submitted."""
        provider_config_id = str(choice.get("providerConfigId") or "")
        model_id = str(choice.get("modelId") or "")
        try:
            row = self._catalog.records.get(provider_config_id)
        except ServerError as exc:
            if exc.code == "PROVIDER_MODEL_NOT_FOUND":
                return PROVIDER_NOT_FOUND
            return OPERATION_UNKNOWN
        if row["archived_at"] is not None:
            return PROVIDER_ARCHIVED
        if int(row["version"]) != int(choice["version"]):
            return CONFIG_REVISION_CONFLICT
        if model_id not in self._catalog.model_ids(provider_config_id):
            return MODEL_NOT_FOUND
        return None

    def _undecided(self, answer, target, sequence, reason) -> dict[str, Any]:
        """Record the unsafe state: the intent is kept and the session is
        blocked against any further submission until it is observed."""
        self._selector.block(dict(target), sequence, reason)
        return answer(SUBMIT_UNKNOWN, reason=reason, sequence=sequence)

    def _settled(self, answer, target, key, sequence, choice, result, routing) -> dict[str, Any]:
        """Adjudicate the port's answer; only a fenced, evidenced ``ready``
        consumes the intent."""
        outcome = getattr(result, "outcome", None)
        if outcome not in PORT_OUTCOMES:
            return self._undecided(answer, target, sequence, OPERATION_UNKNOWN)
        echoed = getattr(result, "sequence", None)
        if echoed is not None and int(echoed) != int(sequence):
            # the port answered for another intent: cross-route, never consumed
            return self._undecided(answer, target, sequence, TARGET_STALE)
        reason = getattr(result, "reason", None)
        if outcome == SUBMIT_UNKNOWN:
            return self._undecided(answer, target, sequence, str(reason or OPERATION_UNKNOWN))
        if outcome == SUBMIT_REFUSED:
            return answer(SUBMIT_REFUSED, reason=None if reason is None else str(reason),
                          sequence=sequence)
        try:
            application = validated_application(getattr(result, "application", None))
        except ApplicationEvidenceError as error:
            # ready without real evidence is not ready (B.2/M13)
            return self._undecided(answer, target, sequence, str(error))
        if routing is not None and not same_routing_identity(routing, application["nativeTarget"]):
            # the application ran against another channel/owner/generation
            return answer(SUBMIT_REFUSED, reason=TARGET_STALE, sequence=sequence)
        if not self._selector.observe(dict(target), sequence, outcome=OBSERVED_CONFIRMED):
            # the intent moved on while the application ran: the real application
            # happened, but it must not consume the newer pick (FR-04, M12)
            return answer(SUBMIT_READY, sequence=sequence, application=application)
        self._confirmed[key] = self._submission_fact(target, choice, sequence, application)
        self._revisions[key] = sequence
        return answer(SUBMIT_READY, sequence=sequence, application=application)

    def _submission_fact(self, target, choice, sequence, application) -> dict[str, Any]:
        """The session's confirmed fact, citing the real evidence references."""
        fact = self._fact_projection(TurnFact(
            harness_id=target["harnessId"],
            provider_config_id=choice["providerConfigId"],
            model_id=choice["modelId"],
            provider_config_version=int(choice["version"]),
            profile_revision=None,
            evidence={"source": "turn-application",
                      "applied": "read-back-verified",
                      "operationId": application["operationId"],
                      "evidenceRef": application["evidenceRef"]},
        ), source=None)
        fact["sequence"] = sequence
        fact["application"] = application
        return fact

    # -- the submit gate's entry (production wiring is REQ-Z3-2, OPEN) --------

    def resolve_next_turn(self, target: Mapping[str, Any], *,
                          profile_revision: str | None = None):
        """Run the full send-time pipeline for this session's queued choice
        and book an ``applied`` resolution as the session's confirmed fact.
        The gate consumes this; the wire never calls it."""
        key = _session_key(target)
        resolution = self._selector.resolve_next_turn(
            dict(target), profile_revision=profile_revision)
        if resolution.outcome == "applied" and resolution.turn_fact is not None:
            # the resolution names the sequence it actually froze; a pick made
            # during the application keeps its own identity (FR-04, M12)
            sequence = resolution.sequence
            fact = self._fact_projection(resolution.turn_fact, source=None)
            fact["sequence"] = sequence
            self._confirmed[key] = fact
            if sequence is not None:
                self._revisions[key] = sequence
        return resolution

    # -- internals ------------------------------------------------------------

    @property
    def _overlay_port(self):
        return getattr(self, "_overlay", None)

    def _validate_choice(self, harness_id: str, choice: Mapping[str, Any]) -> dict[str, Any]:
        provider_config_id = choice.get("providerConfigId")
        if not provider_config_id or not isinstance(provider_config_id, str):
            raise ServerError(PROVIDER_NOT_FOUND, "choice names no provider config", status=404)
        try:
            row = self._catalog.records.get(provider_config_id)
        except ServerError as exc:
            if exc.code == "PROVIDER_MODEL_NOT_FOUND":
                raise ServerError(
                    PROVIDER_NOT_FOUND, "Provider config was not found", status=404) from exc
            raise
        if row["archived_at"] is not None:
            raise ServerError(PROVIDER_ARCHIVED, "Provider config is archived", status=409)
        model_id = choice.get("modelId")
        if not model_id or model_id not in self._catalog.model_ids(row["id"]):
            raise ServerError(MODEL_NOT_FOUND, "Model is not in the provider config", status=404)
        if row["harness_type"] is not None and row["harness_type"] != harness_id:
            raise ServerError(
                SELECTION_UNSUPPORTED,
                "the config is bound to a different Harness", status=422)
        return row

    def _record_confirmed(self, key, session_ref, choice, sequence) -> dict[str, Any]:
        version = self._catalog.config_version(choice["providerConfigId"])
        turn_fact = TurnFact(
            harness_id=key[1], provider_config_id=choice["providerConfigId"],
            model_id=choice["modelId"], provider_config_version=version,
            profile_revision=None,
            evidence={"source": "session-override", "applied": "reconcile-verified"},
        )
        fact = self._fact_projection(turn_fact, source="session-override")
        fact["sequence"] = sequence
        self._confirmed[key] = fact
        self._revisions[key] = sequence
        self._routed.pop(key, None)  # the projection is settled; no routing mark left
        self._handover_failed.pop(key, None)  # a settled observation clears the mark too
        # The observation consumes *its own* sequence: a pick made while the
        # application was running stays queued for the next turn (M12).
        self._selector.observe(dict(session_ref), sequence,
                               outcome=OBSERVED_CONFIRMED)
        return fact

    @staticmethod
    def _fact_projection(fact, *, source) -> dict[str, Any]:
        return {
            "harnessId": fact.harness_id,
            "providerConfigId": fact.provider_config_id,
            "modelId": fact.model_id,
            "providerConfigVersion": fact.provider_config_version,
            "profileRevision": fact.profile_revision,
            "evidence": dict(fact.evidence),
            **({"source": source} if source else {}),
        }
