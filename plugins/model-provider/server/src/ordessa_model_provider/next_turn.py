# migrated from plugins/model-provider@9305563719d25e04076b9221a7284660bd8f8642 (src/ordessa_model_provider/next_turn.py, verbatim)
"""The next-turn selection pipeline: queue today, apply before the next turn.

Ordering frozen from the spec (002 §4): read the profile revision / session
override, synthesize the ModelChoice, validate capability and connection
version, apply in the owning session, verify the read-back, freeze the turn
facts - and only then may a prompt leave. Any earlier failure returns
``refused`` with the draft untouched and ``prompt_allowed=False``; an outcome
that cannot be confirmed returns ``unknown-outcome`` and blocks further sends
until someone recovers or verifies it. Nothing here retries on its own.

Queue consumption is fenced (spec 021 appendix §5, FR-04/FR-06): a resolution
freezes ``(session, sequence)`` *before* the pipeline runs, only a genuinely
applied resolution consumes that exact sequence, a refusal keeps the intent, an
undecided application keeps it and blocks the session, and a late or foreign
sequence never lands on any state (M08/M12).

Isolation is structural: the queue is keyed by the full session reference
``(serverInstanceId, harnessId, acpSessionId)`` plus any routing identity the
caller carries (channel/owner/canonical UID/generation); a resolution for one
session can never observe or consume another's queued choice, and no API here
reaches any harness-global configuration.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
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

#: Optional routing identity factors. When a caller carries any of them on the
#: session reference (a native channel, the observed owner, the canonical UID
#: or the run generation), they become part of the queue's identity: the same
#: ``acpSessionId`` reached through another channel, under another owner or in
#: another generation is a *different* session for every read, write and
#: late result here (M09/C02). The wire's frozen target carries only the three
#: keys above, so for it these factors are simply absent.
ROUTING_FACTOR_KEYS = ("channel", "owner", "canonicalUid", "generation")

_SOURCE_SESSION = "session-override"
_SOURCE_PROFILE = "profile"

#: The observation vocabulary that may settle a blocked session. Both are
#: *observations*; neither retries an application (FR-06, M08).
OBSERVED_CONFIRMED = "confirmed"
OBSERVED_MISMATCH = "mismatch"


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
    zero-prompt gate: callers must not send while it is False.

    ``sequence`` names the *frozen* intent this resolution is about - the one
    that was applied, or the one that is now blocking the session. It is
    ``None`` when no intent was frozen at all. A resolution never names a
    sequence other than the one it froze, which is what keeps an old result
    from speaking for a newer pick (M12)."""

    outcome: str
    reason: str | None = None
    turn_fact: TurnFact | None = None
    prompt_allowed: bool = False
    associated_options: Mapping[str, Any] = field(default_factory=dict)
    sequence: int | None = None


@dataclass(frozen=True)
class _Queued:
    session_ref: Mapping[str, str]
    choice: Mapping[str, str]
    source: str
    sequence: int


@dataclass(frozen=True)
class _Blocked:
    """A session whose last application could not be decided. The unsafe state
    and the identity of both the old and the new intent are kept; every further
    resolve answers ``unknown`` with zero prompt until an observation settles
    it (FR-06, M08)."""

    sequence: int
    reason: str


def session_key_of(session_ref: Mapping[str, Any]) -> tuple[str, ...]:
    """The queue's identity for a session reference.

    The three native reference keys plus every routing identity factor the
    caller carries (see :data:`ROUTING_FACTOR_KEYS`). Missing reference keys
    are a ``KeyError`` - a session that cannot be named exactly is not a
    session this queue may act on. Exported because the choice service must
    key its confirmed/operation records by *exactly* the same identity.
    """
    missing = [key for key in SESSION_REF_KEYS if not session_ref.get(key)]
    if missing:
        raise KeyError("session reference missing " + ", ".join(missing))
    key = [session_ref[name] for name in SESSION_REF_KEYS]
    key.extend(
        f"{name}={session_ref[name]}"
        for name in ROUTING_FACTOR_KEYS if session_ref.get(name) is not None
    )
    return tuple(key)


class NextTurnSelector:
    """Queues model choices per session and resolves them at the next turn."""

    def __init__(self, harness_port, catalog_view, *, sequence_start: int = 0) -> None:
        self._harness = harness_port
        self._catalog = catalog_view
        self._queued: dict[tuple[str, ...], _Queued] = {}
        self._blocked: dict[tuple[str, ...], _Blocked] = {}
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
        key = session_key_of(session_ref)
        self._sequence += 1
        self._queued[key] = _Queued(
            session_ref=dict(session_ref), choice=dict(choice), source=source,
            sequence=self._sequence,
        )
        return self._sequence

    def cancel(self, session_ref: Mapping[str, Any]) -> bool:
        return self._queued.pop(session_key_of(session_ref), None) is not None

    def pending(self, session_ref: Mapping[str, Any]) -> Mapping[str, Any] | None:
        """The queued choice for exactly this session, or None."""
        queued = self._queued.get(session_key_of(session_ref))
        return dict(queued.choice) if queued else None

    def late_result(self, session_ref: Mapping[str, Any], sequence: int) -> bool:
        """Whether a late-arriving result belongs to this session's queued
        choice. A mismatched identity - other session, other server instance,
        other native session id, or a stale sequence - is dropped by returning
        False; it never lands on any session's state.

        A blocked session never answers True either: an undecided application
        is settled by an observation, not by a late result (FR-06)."""
        key = session_key_of(session_ref)
        if key in self._blocked:
            return False
        queued = self._queued.get(key)
        return queued is not None and queued.sequence == sequence

    def intent(self, session_ref: Mapping[str, Any]) -> Mapping[str, Any] | None:
        """The frozen intent for exactly this session, with its sequence.

        ``None`` when nothing is queued. This is the read the submit gate
        freezes before delegating; it never consumes and never resolves.
        """
        queued = self._queued.get(session_key_of(session_ref))
        if queued is None:
            return None
        return {"sequence": queued.sequence, "source": queued.source,
                "choice": dict(queued.choice)}

    def blocked(self, session_ref: Mapping[str, Any]) -> Mapping[str, Any] | None:
        """The session's blocking state (``sequence``, ``reason``), or None."""
        state = self._blocked.get(session_key_of(session_ref))
        return None if state is None else {"sequence": state.sequence,
                                           "reason": state.reason}

    def block(self, session_ref: Mapping[str, Any], sequence: int,
              reason: str) -> None:
        """Block a session whose application could not be decided.

        The frozen intent stays queued - the unsafe state keeps the identity of
        both the applied attempt and the intent behind it - and every further
        resolve answers ``unknown`` with zero prompt until :meth:`observe`
        settles *this* sequence. A newer pick does not clear the block.
        """
        self._blocked[session_key_of(session_ref)] = _Blocked(
            sequence=int(sequence), reason=str(reason))

    def observe(self, session_ref: Mapping[str, Any], sequence: int, *,
                outcome: str) -> bool:
        """Settle a session from an *observed* fact. Never applies anything.

        ``outcome`` is ``confirmed`` (the read-back really matches this frozen
        intent: the intent is consumed, and only if it is still the current
        one) or ``mismatch`` (the observation proves it did not apply: the
        unsafe state clears and the intent is kept for an explicit retry).
        Anything else, and any sequence that is neither the blocked one nor the
        currently queued one, returns False - an out-of-order or foreign result
        never consumes or clears anything (FR-06, M12).
        """
        if outcome not in (OBSERVED_CONFIRMED, OBSERVED_MISMATCH):
            return False
        key = session_key_of(session_ref)
        frozen = int(sequence)
        queued = self._queued.get(key)
        blocked = self._blocked.get(key)
        if blocked is not None:
            if blocked.sequence != frozen:
                return False
            # the unsafe state is settled by the observation, nothing more
            self._blocked.pop(key, None)
            if outcome == OBSERVED_MISMATCH:
                return True                        # intent kept for an explicit retry
            self._consume(key, frozen)             # a newer pick is never consumed
            return True
        if queued is None or queued.sequence != frozen:
            return False
        if outcome == OBSERVED_MISMATCH:
            return True
        return self._consume(key, frozen)

    def _consume(self, key: tuple[str, ...], sequence: int) -> bool:
        """Drop the queued intent only if it is still the frozen one.

        The compare-and-set is what keeps an application that ran while the
        user picked again from consuming the newer pick (FR-04/FR-06, M12).
        """
        queued = self._queued.get(key)
        if queued is None or queued.sequence != sequence:
            return False
        del self._queued[key]
        return True

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

        The queue is **not** popped before the pipeline runs (FR-06, M08):
        ``(session, sequence)`` is frozen first, and only a genuinely applied
        resolution consumes that exact sequence. A refusal keeps the intent for
        an explicit retry; an undecided application keeps it *and* blocks every
        further resolve of this session with zero prompt until an observation
        settles it - so a blocked session can never degrade into the "no queued
        choice" path that would let the prompt through.
        """
        key = session_key_of(session_ref)
        blocked = self._blocked.get(key)
        if blocked is not None:
            return NextTurnResolution(
                outcome=OUTCOME_UNKNOWN, reason=blocked.reason,
                prompt_allowed=False, sequence=blocked.sequence)
        queued = self._queued.get(key)
        if queued is None:
            return NextTurnResolution(
                outcome=OUTCOME_PENDING, prompt_allowed=True,
                reason="no queued model choice",
            )
        try:
            resolution = self._pipeline(session_ref, queued, profile_revision=profile_revision)
        except SessionConfigError as error:
            if error.code == SESSION_CONFIG_OUTCOME_UNKNOWN:
                self._block(key, queued, error.code)
                return NextTurnResolution(
                    outcome=OUTCOME_UNKNOWN, reason=error.code, prompt_allowed=False,
                    sequence=queued.sequence)
            return NextTurnResolution(
                outcome=OUTCOME_REFUSED, reason=error.code, prompt_allowed=False,
                sequence=queued.sequence)
        except Exception as error:  # noqa: BLE001 - conservative refusal, never a crash path
            return NextTurnResolution(
                outcome=OUTCOME_REFUSED, reason=f"{type(error).__name__}: {error}",
                prompt_allowed=False, sequence=queued.sequence,
            )
        if resolution.outcome != OUTCOME_APPLIED:
            # refused or unknown: the intent stays queued under its own
            # sequence. An unknown additionally blocks the session.
            if resolution.outcome == OUTCOME_UNKNOWN:
                self._block(key, queued, resolution.reason or SESSION_CONFIG_OUTCOME_UNKNOWN)
            return replace(resolution, sequence=queued.sequence)
        # Applied with a real read-back: consume this exact sequence. A pick
        # made during the application survives and waits for the next turn.
        self._consume(key, queued.sequence)
        return replace(resolution, sequence=queued.sequence)

    def _block(self, key: tuple[str, ...], queued: _Queued, reason: str) -> None:
        self._queued.setdefault(key, queued)
        self._blocked[key] = _Blocked(sequence=queued.sequence, reason=reason)

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
