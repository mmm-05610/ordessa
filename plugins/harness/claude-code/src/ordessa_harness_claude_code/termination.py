"""Claude family termination consumption over the frozen unified face.

stop/release walk the frozen ledger sequence exactly once per (Unit, action):
``begin_termination`` consumes the ORIGINAL cleanup invocation, the actual
native effect runs, the owner termination evidence port proves what this owner
observed, and ``record_termination`` stores only the port's provenance refs.

Safety invariants (termination-face-freeze): an unknown outcome keeps the
attempt, the hold and the live ticket and never releases any Usage or process
automatically; only units present in this owner's owned-channel registry reach
the effect — borrowed or unknown units are always refused, never killed, never
released. Reconcile is cold recovery: an authorized query may conclude a
retained attempt with owner-observed evidence; it never re-arms a dispatch.
"""
from __future__ import annotations

from typing import Mapping

from ordessa_environment_api.operations import safe_json, sealed_mapping

from .ownership import ClaudeChannelRefused, complete_unit_ref

TERMINATION_ACTIONS = ("stop", "release")


class ClaudeTerminationRefused(RuntimeError):
    code = "CLAUDE_TERMINATION_REFUSED"


def _correlation(facts):
    try:
        return safe_json({"request": facts["request"], "operationRef": facts["operationRef"],
                          "stepId": facts["stepId"]})
    except (KeyError, TypeError, ValueError) as error:
        raise ClaudeTerminationRefused("original invocation correlation unavailable") from error


class ClaudeTerminationEffects:
    """The provider's REAL stop/release effect over its owned channel registry.

    Every effect is identity-bound: only the entry this owner registered for
    this exact unit reference is acted on, and the observation recorded by the
    owner termination evidence port is born inside the effect — the caller can
    never substitute it afterwards.
    """

    def __init__(self, channels, evidence, *, close_timeout: float = 15.0):
        self.channels, self.evidence = channels, evidence
        if not callable(getattr(channels, "release", None)) or not callable(getattr(channels, "is_owned", None)):
            raise ClaudeTerminationRefused("owned channel registry required for termination effects")
        if not callable(getattr(evidence, "observe", None)):
            raise ClaudeTerminationRefused("owner termination evidence port required")
        self.close_timeout = close_timeout

    def is_owned(self, unit_ref) -> bool:
        """Ownership gate for destructive lifecycle, for this owner's units only."""
        return bool(self.channels.is_owned(unit_ref))

    def has_live_process(self, unit_ref) -> bool:
        return bool(self.channels.has_live_process(unit_ref))

    def termination_effect(self, unit, action, context):
        """Perform the actual effect on this owner's OWNED channel entry only.

        An absent registry entry is a typed ownership refusal. Declining
        release of a unit that still runs happens through the coordinator's
        pre-begin check; this effect itself maps genuinely unobservable
        outcomes to unknown through the caller, never to a fake confirmation.
        """
        try:
            self.channels.entry(unit.public_ref)
        except ClaudeChannelRefused:
            raise ClaudeTerminationRefused(
                "unit is not owned by this native effects owner; never kill borrowed or unknown") from None
        correlation = _correlation(dict(context.facts))
        if action == "release":
            self.channels.release(unit.public_ref)
            observation = {"outcome": "confirmed", "handleReleased": "1"}
            self.evidence.observe(unit, action, correlation, observation)
            return observation
        entry = self.channels.entry(unit.public_ref)
        if not entry.channel.is_alive():
            observation = {"outcome": "confirmed", "alreadyExited": "1"}
            self.evidence.observe(unit, action, correlation, observation)
            return observation
        try:
            code = entry.channel.close(timeout=self.close_timeout)
        except Exception:
            # The effect could not be observed: nothing is confirmed, released
            # or deleted; the attempt stays with its hold (unknown).
            return {"outcome": "unknown"}
        if type(code) is not int or isinstance(code, bool) or entry.channel.is_alive():
            return {"outcome": "unknown"}
        observation = {"outcome": "confirmed", "exitCode": str(code), "reaped": "1"}
        self.evidence.observe(unit, action, correlation, observation)
        return observation

    def reobserve_termination(self, unit, action):
        """Late observation of an owned channel after an unknown outcome.

        Confirmable only when the owned process is, in fact, gone now; nothing
        is re-sent, re-killed or released by a late confirmation. The exit code
        is intentionally absent from a late observation: only "gone" is meant.
        """
        if action not in TERMINATION_ACTIONS:
            raise ClaudeTerminationRefused("termination reobservation covers stop and release only")
        if not self.channels.is_owned(unit.public_ref):
            return None
        try:
            entry = self.channels.entry(unit.public_ref)
        except ClaudeChannelRefused:
            return None
        if entry.channel.is_alive():
            return None
        return {"outcome": "confirmed", "observedLate": "1"}

    def bind_observation(self, unit, action, context, observation) -> Mapping:
        """Birth-record the late observation under the original correlation."""
        return self.evidence.observe(unit, action, _correlation(dict(context.facts)), observation)


class ClaudeTerminationCoordinator:
    """Original ledger-driven stop/release for the claude family.

    Sequence per the frozen face: owned-only pre-begin gate → begin (consumes
    the original cleanup invocation) → actual effect → owner evidence port
    verification (inside the ledger transaction) → reply carrying the
    owner-read termination projection. Any post-begin failure records the
    attempt unknown — the hold, the ticket and any remainders stay in place.
    """

    def __init__(self, *, records, verifier, projection, effects):
        self.records, self.verifier, self.projection, self.effects = records, verifier, projection, effects
        ledger_methods = ("begin_termination", "record_termination", "reconcile_termination",
                          "owner_read_termination")
        if any(not callable(getattr(records, name, None)) for name in ledger_methods):
            raise ClaudeTerminationRefused("original termination ledger methods required")
        if not callable(getattr(records.termination_evidence, "verify_termination", None)):
            raise ClaudeTerminationRefused("owner termination evidence port required")
        if not callable(getattr(projection, "read_unit", None)):
            raise ClaudeTerminationRefused("owner projection required for termination reads")
        if any(not callable(getattr(effects, name, None))
               for name in ("is_owned", "has_live_process", "termination_effect")):
            raise ClaudeTerminationRefused("owned native termination effects required")

    @property
    def ready(self) -> bool:
        return True

    def stop(self, unit_ref, invocation_context):
        return self._run(unit_ref, invocation_context, "stop")

    def release(self, unit_ref, invocation_context):
        return self._run(unit_ref, invocation_context, "release")

    # -- one attempt per (unit, action) -------------------------------------------
    def _run(self, unit_ref, context, action):
        if action not in TERMINATION_ACTIONS:
            raise ClaudeTerminationRefused("termination action must be stop or release")
        unit = self.projection.read_unit(unit_ref, context)
        if not complete_unit_ref(unit.public_ref):
            raise ClaudeTerminationRefused("original unit source reference differs")
        # Ownership is decided BEFORE any consume attempt: unknown or borrowed
        # units never reach a begin, never reach the effect, never get killed.
        if not self.effects.is_owned(unit.public_ref):
            raise ClaudeTerminationRefused(
                "destructive lifecycle requires this owner's owned live unit; "
                "borrowed or unknown units are never killed")
        if action == "release" and self.effects.has_live_process(unit.public_ref):
            raise ClaudeTerminationRefused("release does not stop running units; stop the unit first")
        ticket = self.records.begin_termination(unit.unit_ref, context,
            input_digest=context.facts["inputDigest"], action=action)
        try:
            observation = self.effects.termination_effect(unit, action, context)
            if isinstance(observation, Mapping) and observation.get("outcome") == "confirmed":
                outcome = self.records.record_termination(ticket, expected_source_revision=1,
                    state="confirmed", evidence=dict(observation))
            else:
                outcome = self.records.record_termination(ticket, expected_source_revision=1,
                    state="unknown")
        except BaseException as exc:
            try:
                self.records.record_termination(ticket, expected_source_revision=1, state="unknown")
            except Exception:
                # A concurrently concluded original attempt is never downgraded.
                pass
            if not isinstance(exc, Exception):
                raise
            return self._reply(unit_ref, unit, action)
        return self._reply(unit_ref, unit, action, outcome)

    def _reply(self, unit_ref, unit, action, outcome=None):
        projection = self.records.owner_read_termination(unit.unit_ref, action)
        reply = {"unitRef": unit.public_ref, "action": action,
                 "state": "unknown" if projection is None else projection["state"],
                 "termination": projection}
        if outcome is not None:
            reply["sourceRevision"] = outcome["sourceRevision"]
        try:
            return sealed_mapping(reply)
        except (TypeError, ValueError) as error:
            raise ClaudeTerminationRefused("termination reply projection is not sealable") from error

    # -- cold recovery / late evidence ------------------------------------------------
    def reconcile(self, unit_ref, action, query_context):
        """Conclude a retained attempt with owner-observed evidence; never re-dispatch."""
        if action not in TERMINATION_ACTIONS:
            raise ClaudeTerminationRefused("termination action must be stop or release")
        unit = self.projection.read_unit(unit_ref, query_context)
        existing = self.records.owner_read_termination(unit.unit_ref, action)
        if existing is None:
            raise ClaudeTerminationRefused("termination attempt was never claimed")
        facts = query_context.facts
        if facts.get("query") is not True:
            raise ClaudeTerminationRefused("cold termination reconciliation requires query authority")
        if _correlation(facts) != existing["identity"]["correlation"]:
            raise ClaudeTerminationRefused("query is not the original termination attempt")
        if existing["state"] == "confirmed":
            return self._reply(unit_ref, unit, action)
        observation = self.effects.reobserve_termination(unit, action)
        if observation is None:
            return self._reply(unit_ref, unit, action)
        self.effects.bind_observation(unit, action, query_context, observation)
        result = self.records.reconcile_termination(unit.unit_ref, query_context,
            input_digest=existing["identity"]["inputDigest"], action=action,
            expected_source_revision=existing["sourceRevision"], state="confirmed",
            evidence=dict(observation))
        return self._reply(unit_ref, unit, action, result)
