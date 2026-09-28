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
"""
from __future__ import annotations

from typing import Any, Mapping

from ordessa_server.errors import ServerError
from ordessa_model_provider.next_turn import (
    OUTCOME_PENDING, SESSION_REF_KEYS, NextTurnSelector,
)
from ordessa_model_provider.ports import (
    ELIGIBILITY_READY, ELIGIBILITY_UNSUPPORTED, REFERENCE_STATE_UNKNOWN,
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


def _session_key(target: Mapping[str, Any]) -> tuple[str, ...]:
    missing = [key for key in SESSION_REF_KEYS if not target.get(key)]
    if missing:
        raise ServerError(
            "REQUEST_INVALID",
            "target must carry native " + ", ".join(SESSION_REF_KEYS), status=422,
        )
    return tuple(target[key] for key in SESSION_REF_KEYS)


class ModelChoiceService:
    """Queue/inspect/reconcile for per-session ModelChoices, plus the paged
    catalogue. The pending queue is the ``NextTurnSelector`` (migrated,
    unchanged); this service adds the wire-facing validation and facts."""

    def __init__(self, catalog, *, harness_config_port=None, idempotency=None,
                 overlay_port=None) -> None:
        self._catalog = catalog
        self._harness = harness_config_port
        self._idempotency = idempotency
        self._overlay = overlay_port
        self._selector = NextTurnSelector(harness_config_port, catalog)
        #: sequence -> (session_key, session_ref, choice); the reconcile's
        #: operation index (the selector keeps only the newest intent/session).
        self._operations: dict[int, tuple[tuple[str, ...], Mapping[str, Any], Mapping[str, Any]]] = {}
        self._confirmed: dict[tuple[str, ...], dict[str, Any]] = {}
        self._revisions: dict[tuple[str, ...], int] = {}

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
            dict(target), {"providerConfigId": row["id"], "modelId": choice["modelId"]},
            source="session-override")
        body["sequence"] = sequence
        self._operations[sequence] = (key, dict(target), dict(choice))
        self._revisions[key] = sequence
        if self._idempotency is not None:
            from ordessa_server.records import digest

            self._idempotency.save(
                _QUEUE_SCOPE, operation_key, digest(digest_payload), 200, body)
        return body

    def inspect(self, target: Mapping[str, Any]) -> dict[str, Any]:
        key = _session_key(target)
        pending = self._selector.pending(target)
        fact = self._confirmed.get(key)
        return {
            "desired": dict(pending) if pending else None,
            "lastConfirmed": dict(fact) if fact else None,
            "revision": self._revisions.get(key),
        }

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
        _key, session_ref, choice = operation
        read_back = self._harness.read_back(dict(session_ref))
        if not isinstance(read_back, Mapping):
            return {"outcome": OUTCOME_UNKNOWN, "reason": OPERATION_UNKNOWN,
                    "promptAllowed": False}
        if read_back.get("model") != choice.get("modelId"):
            return {"outcome": OUTCOME_REFUSED, "reason": VERIFICATION_MISMATCH,
                    "promptAllowed": False}
        fact = self._record_confirmed(key, session_ref, choice, int(operation_id))
        return {"outcome": OUTCOME_CONFIRMED, "turnFact": fact}

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
            sequence = self._revisions.get(key)
            fact = self._fact_projection(resolution.turn_fact, source=None)
            fact["sequence"] = sequence
            self._confirmed[key] = fact
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
        from ordessa_model_provider.next_turn import TurnFact

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
        pending = self._selector.pending(session_ref)
        if pending and pending.get("modelId") == choice.get("modelId"):
            self._selector.cancel(session_ref)
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
