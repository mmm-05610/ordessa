# migrated from plugins/model-provider@9305563719d25e04076b9221a7284660bd8f8642 (src/ordessa_model_provider/next_turn.py, verbatim)
"""The next-turn selection pipeline: queue today, apply before the next turn.

Ordering frozen from the spec (002 §4): read the profile revision / session
override, synthesize the ModelChoice, validate capability and connection
version, apply in the owning session, verify the read-back, freeze the turn
facts - and only then may a prompt leave. Any earlier failure returns
``refused`` with the draft untouched and ``prompt_allowed=False``; an outcome
that cannot be confirmed returns ``unknown-outcome`` and blocks further sends
until someone recovers or verifies it. Nothing here retries on its own.

Isolation is structural: the queue is keyed by the full session reference
``(serverInstanceId, harnessId, acpSessionId)``; a resolution for one session
can never observe or consume another's queued choice, and no API here reaches
any harness-global configuration.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from ordessa_model_provider.ports import (
    ELIGIBILITY_READY,
    SESSION_CONFIG_OUTCOME_UNKNOWN,
    SessionConfigError,
)

OUTCOME_PENDING = "pending-next-turn"
OUTCOME_APPLIED = "applied"
OUTCOME_REFUSED = "refused"
OUTCOME_UNKNOWN = "unknown-outcome"

#: The session reference keys; all three must match for anything to count as
#: "the same session" (spec FR-SESSION-4).
SESSION_REF_KEYS = ("serverInstanceId", "harnessId", "acpSessionId")

_SOURCE_SESSION = "session-override"
_SOURCE_PROFILE = "profile"


@dataclass(frozen=True)
class TurnFact:
    """The per-turn frozen projection (data-model.md §1). Non-sensitive by
    construction: evidence carries outcome codes and read-back values, never
    credentials."""

    harness_id: str
    provider_config_id: str
    model_id: str
    provider_config_version: int
    profile_revision: str | None
    evidence: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class NextTurnResolution:
    """The pipeline's only output shape. ``prompt_allowed`` is the program's
    zero-prompt gate: callers must not send while it is False."""

    outcome: str
    reason: str | None = None
    turn_fact: TurnFact | None = None
    prompt_allowed: bool = False
    associated_options: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class _Queued:
    session_ref: Mapping[str, str]
    choice: Mapping[str, str]
    source: str
    sequence: int


def _session_key(session_ref: Mapping[str, Any]) -> tuple[str, ...]:
    missing = [key for key in SESSION_REF_KEYS if not session_ref.get(key)]
    if missing:
        raise KeyError("session reference missing " + ", ".join(missing))
    return tuple(session_ref[key] for key in SESSION_REF_KEYS)


class NextTurnSelector:
    """Queues model choices per session and resolves them at the next turn."""

    def __init__(self, harness_port, catalog_view, *, sequence_start: int = 0) -> None:
        self._harness = harness_port
        self._catalog = catalog_view
        self._queued: dict[tuple[str, ...], _Queued] = {}
        self._sequence = sequence_start

    # -- queueing (the current turn never changes) -------------------------

    def queue(self, session_ref: Mapping[str, Any], choice: Mapping[str, Any],
              *, source: str) -> int:
        """Queue one choice as *next turn's* model for this exact session.

        Queuing mutates nothing the running turn can observe. A re-queue for
        the same session replaces the earlier entry (the newest intent wins);
        other sessions are untouched.
        """
        if source not in (_SOURCE_SESSION, _SOURCE_PROFILE):
            raise ValueError("source must be 'session-override' or 'profile'")
        key = _session_key(session_ref)
        self._sequence += 1
        self._queued[key] = _Queued(
            session_ref=dict(session_ref), choice=dict(choice), source=source,
            sequence=self._sequence,
        )
        return self._sequence

    def cancel(self, session_ref: Mapping[str, Any]) -> bool:
        return self._queued.pop(_session_key(session_ref), None) is not None

    def pending(self, session_ref: Mapping[str, Any]) -> Mapping[str, Any] | None:
        """The queued choice for exactly this session, or None."""
        queued = self._queued.get(_session_key(session_ref))
        return dict(queued.choice) if queued else None

    def late_result(self, session_ref: Mapping[str, Any], sequence: int) -> bool:
        """Whether a late-arriving result belongs to this session's queued
        choice. A mismatched identity - other session, other server instance,
        other native session id, or a stale sequence - is dropped by returning
        False; it never lands on any session's state."""
        queued = self._queued.get(_session_key(session_ref))
        return queued is not None and queued.sequence == sequence

    # -- the next-turn pipeline ---------------------------------------------

    def resolve_next_turn(self, session_ref: Mapping[str, Any], *,
                          profile_revision: str | None = None,
                          ) -> NextTurnResolution:
        """Run the send-time pipeline for this session's queued choice.

        The choice is always validated against the provider config's *latest*
        revision (R1: the next turn resolves the newest revision; an
        incompatible new revision blocks the turn, it never falls back).
        Every failure path returns a resolution; nothing raises to the caller
        (an unexpected error is a conservative ``refused``). ``prompt_allowed``
        is True only for ``applied`` and for a session with no queued choice.
        """
        key = _session_key(session_ref)
        queued = self._queued.pop(key, None)
        if queued is None:
            return NextTurnResolution(
                outcome=OUTCOME_PENDING, prompt_allowed=True,
                reason="no queued model choice",
            )
        try:
            return self._pipeline(session_ref, queued, profile_revision=profile_revision)
        except SessionConfigError as error:
            if error.code == SESSION_CONFIG_OUTCOME_UNKNOWN:
                return NextTurnResolution(
                    outcome=OUTCOME_UNKNOWN, reason=error.code, prompt_allowed=False)
            return NextTurnResolution(
                outcome=OUTCOME_REFUSED, reason=error.code, prompt_allowed=False)
        except Exception as error:  # noqa: BLE001 - conservative refusal, never a crash path
            return NextTurnResolution(
                outcome=OUTCOME_REFUSED, reason=f"{type(error).__name__}: {error}",
                prompt_allowed=False,
            )

    # -- pipeline steps ------------------------------------------------------

    def _pipeline(self, session_ref, queued, *, profile_revision) -> NextTurnResolution:
        choice = queued.choice
        provider_config_id = choice.get("providerConfigId")
        model_id = choice.get("modelId")
        harness_id = choice.get("harnessId") or queued.session_ref.get("harnessId")
        if not provider_config_id or not model_id or not harness_id:
            return NextTurnResolution(outcome=OUTCOME_REFUSED,
                                      reason="incomplete ModelChoice", prompt_allowed=False)

        # -- resolve the config's LATEST revision (R1) and validate against it --
        try:
            version = self._catalog.config_version(provider_config_id)
        except Exception as error:  # missing record is a typed refusal
            return NextTurnResolution(outcome=OUTCOME_REFUSED,
                                      reason=f"PROVIDER_MODEL_NOT_FOUND: {error}",
                                      prompt_allowed=False)
        if self._catalog.is_archived(provider_config_id):
            return NextTurnResolution(outcome=OUTCOME_REFUSED,
                                      reason="provider config archived", prompt_allowed=False)
        if model_id not in self._catalog.model_ids(provider_config_id):
            return NextTurnResolution(outcome=OUTCOME_REFUSED,
                                      reason="model not in the provider config", prompt_allowed=False)

        # -- the harness adapter's readiness verdict (the five evidences) --
        eligibility = self._harness.eligibility(
            harness_id, {"providerConfigId": provider_config_id, "version": version},
            dict(session_ref),
        )
        if eligibility != ELIGIBILITY_READY:
            return NextTurnResolution(outcome=OUTCOME_REFUSED,
                                      reason=f"eligibility={eligibility}",
                                      prompt_allowed=False)

        # -- apply, then verify by read-back (a receipt without a verified
        #    read-back is an unknown outcome, never a success) --
        associated = dict(choice.get("associated") or {})
        receipt = self._harness.apply(dict(session_ref), {
            "providerConfigId": provider_config_id, "modelId": model_id,
            "version": version,
        })
        read_back = receipt.get("readBack")
        if not isinstance(read_back, Mapping):
            return NextTurnResolution(
                outcome=OUTCOME_UNKNOWN, reason=SESSION_CONFIG_OUTCOME_UNKNOWN,
                prompt_allowed=False)
        applied_model = read_back.get("model")
        if applied_model != model_id:
            return NextTurnResolution(
                outcome=OUTCOME_UNKNOWN, reason=SESSION_CONFIG_OUTCOME_UNKNOWN,
                prompt_allowed=False)

        # -- associated settings re-read (FR-SESSION-5): an old value that is
        #    no longer offered must refuse - never silently kept, never
        #    silently defaulted. --
        options = receipt.get("configOptions")
        if not isinstance(options, Mapping):
            return NextTurnResolution(
                outcome=OUTCOME_UNKNOWN, reason=SESSION_CONFIG_OUTCOME_UNKNOWN,
                prompt_allowed=False)
        for option_id, wanted in associated.items():
            if option_id not in options:
                return NextTurnResolution(
                    outcome=OUTCOME_REFUSED,
                    reason=f"associated option {option_id!r} disappeared",
                    prompt_allowed=False)
            if options[option_id] != wanted:
                return NextTurnResolution(
                    outcome=OUTCOME_REFUSED,
                    reason=f"associated option {option_id!r} not applied",
                    prompt_allowed=False)

        fact = TurnFact(
            harness_id=harness_id, provider_config_id=provider_config_id,
            model_id=model_id, provider_config_version=version,
            profile_revision=profile_revision,
            evidence={"source": queued.source, "applied": "read-back-verified"},
        )
        return NextTurnResolution(
            outcome=OUTCOME_APPLIED, turn_fact=fact, prompt_allowed=True,
            associated_options=options,
        )
