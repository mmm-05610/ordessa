"""The one real-application seam behind ``modelProvider.beginTurnApplication``.

Frozen by ``specs/021-nightly-product-closeout/zcode-profile-model-appendix.md``
§2 (the wire DTO) and §3.3 (single real application). The plugin only
*consumes a frozen intent*; the actual native application is delegated to one
composition-injected ``TurnApplicationPort``, whose product implementation
binds to the neutral ``native.configuration`` C4 owner-plan entry (one apply,
shared journal, fresh read-back).

This module therefore defines the port, its result shape, the evidence
validation and the version-bearing submission key — it implements **no** apply
of its own, and it never falls back to the legacy
``harness_binding.ConfigurationServiceHarnessPort`` pseudo read-back (B.2:
fixed target, request-synthesized read-back, version-less operation key).

Two fail-closed rules live here because every consumer needs them:

- a ``ready`` outcome without complete, real evidence references is not a
  ready outcome - it degrades to ``unknown`` and blocks the prompt gate;
- the operation key handed to the port always carries the frozen provider
  config version (and the sequence, plus the routing generation when the port
  can observe one), so an unversioned ``mp-`` plan can never be replayed after
  the catalogue, credentials or adapter publication changed (M10).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable

#: The wire outcome vocabulary of the frozen §2 response DTO.
SUBMIT_READY = "ready"
SUBMIT_REFUSED = "refused"
SUBMIT_UNKNOWN = "unknown"
SUBMIT_NO_INTENT = "no-intent"

#: Outcomes a port may answer. ``no-intent`` is decided by the plugin (nothing
#: was frozen for this exact target) and is never a port answer.
PORT_OUTCOMES = frozenset({SUBMIT_READY, SUBMIT_REFUSED, SUBMIT_UNKNOWN})

#: The application evidence references of the §2 response ``application``
#: object. Every one of them is a *reference* the real application produced;
#: the plugin synthesizes none of them.
EVIDENCE_FIELDS = ("operationId", "nativeTarget", "appliedRevision", "evidenceRef")

#: The native identity the C4 operation ran against (C02: a new run owns a new
#: generation; a reference from the previous run is dead).
NATIVE_TARGET_FIELDS = ("owner", "canonicalUid", "generation")


class ApplicationEvidenceError(ValueError):
    """A ``ready`` answer whose evidence references are absent or malformed.

    The caller degrades this to ``unknown`` with zero prompt: a receipt without
    a real read-back reference is not a confirmation (the same rule the
    next-turn pipeline applies to ``HarnessConfigPort.apply``).
    """


class TurnIntentHandoverError(RuntimeError):
    """A bound-target intent handover FAILED or is UNKNOWN (021 appendix §6c
    F2.1, codex review F2).

    The composition-injected :class:`TurnIntentSink` raises this when the
    target IS a registered Profile session but the overlay write failed, or
    when the bridge cannot tell. Folding such an outcome into ``False``
    ("unbound") would silently re-route the send onto the old model - exactly
    the leak the review forbids. The choice surface marks the queued intent
    ``handover-failed`` instead: the intent is kept, and the submit gate
    answers the typed :data:`HANDOVER_UNRESOLVED` refusal until a newer
    successful pick supersedes the mark.
    """


#: The ``intentRoute`` vocabulary of the queue answer (§6c F2.2). The value
#: states which authority now owns the newest intent:
#: - ``profile-overlay``: a registered Profile session took it (the sink wrote
#:   the overlay); the queue entry is a UI projection and the Profile pipeline
#:   applies it;
#: - ``independent``: the queue keeps the authority (no sink, or the target is
#:   genuinely unbound) and the submit gate applies it;
#: - ``handover-failed``: the target was bound but the handover failed or is
#:   unknown — the intent stays with the mark and the submit gate refuses.
INTENT_ROUTE_PROFILE_OVERLAY = "profile-overlay"
INTENT_ROUTE_INDEPENDENT = "independent"
INTENT_ROUTE_HANDOVER_FAILED = "handover-failed"
INTENT_ROUTES = frozenset({
    INTENT_ROUTE_PROFILE_OVERLAY, INTENT_ROUTE_INDEPENDENT, INTENT_ROUTE_HANDOVER_FAILED,
})

#: The submit-gate refusal reason for an intent whose bound handover never
#: resolved (§6c F2.4): zero prompt, intent kept, never a second apply.
HANDOVER_UNRESOLVED = "HANDOVER_UNRESOLVED"


@dataclass(frozen=True)
class SubmitResult:
    """What one ``TurnApplicationPort.submit`` answers.

    ``sequence`` echoes the intent sequence the port actually applied. It is
    optional (a port that does not track the queue leaves it ``None``), but
    when present it must equal the plugin's frozen sequence or the answer is
    discarded as cross-route (M09/M12). ``application`` is non-``None`` only
    for ``ready`` and must carry every :data:`EVIDENCE_FIELDS` entry.
    """

    outcome: str
    reason: str | None = None
    sequence: int | None = None
    application: Mapping[str, Any] | None = None


@runtime_checkable
class TurnApplicationPort(Protocol):
    """The single real application entry for an unbound model's next turn.

    Implementations are supplied by the product composition, not by this
    plugin. The plugin consumes the result; it never synthesizes one.
    """

    def submit(
        self,
        target: Mapping[str, Any],
        *,
        operation_key: str,
        expected_sequence: int | None,
        intent: Mapping[str, Any],
    ) -> SubmitResult:
        """Apply the frozen ``intent`` for exactly ``target``.

        ``target`` is the exact native session reference
        ``{"serverInstanceId", "harnessId", "acpSessionId"}`` the intent was
        queued for - the caller never resolves "the first match".
        ``operation_key`` is the plugin-derived, version-bearing key (see
        :func:`submission_operation_key`); the implementation must pass it
        through to the shared journal so a replay is free.
        ``expected_sequence`` is the frozen queue sequence, or ``None`` when the
        client did not name one.
        ``intent`` is the frozen intent projection: ``{"sequence", "source",
        "choice": {"providerConfigId", "modelId", "version"}}``.

        Returns a :class:`SubmitResult`. Raising is not the failure channel;
        an implementation that cannot answer returns ``unknown`` (or raises,
        which the caller maps to ``unknown`` and blocks).
        """
        ...


@runtime_checkable
class RoutingIdentityPort(Protocol):
    """OPTIONAL companion of :class:`TurnApplicationPort`.

    A port that can observe the *current* native owner binding for a target
    implements ``routing_identity``; the plugin then
    (a) folds the observed ``owner``/``canonicalUid``/``generation`` into the
    submission operation key, and
    (b) refuses a ``ready`` answer whose ``nativeTarget`` does not match the
    identity observed at admission - a result routed to another channel, owner
    or generation never lands on this session's state (M09/C02).

    A port without this method is still honest: it simply moves those fences
    into its own C4 plan/journal, which the plugin cannot inspect.
    """

    def routing_identity(self, target: Mapping[str, Any]) -> Mapping[str, Any] | None:
        """The observed ``{"owner", "canonicalUid", "generation"}`` for this
        exact target, or ``None`` when it cannot be observed (never a guess)."""
        ...


def validated_application(application: Any) -> dict[str, Any]:
    """The §2 ``application`` evidence object, or a typed refusal.

    Every field is a reference the real application produced. A missing,
    mistyped or empty field raises :class:`ApplicationEvidenceError` rather
    than being filled in here - a synthesized evidence reference is exactly
    the pseudo read-back this contract forbids (B.2/M13).
    """
    if not isinstance(application, Mapping):
        raise ApplicationEvidenceError("application evidence is absent")
    operation_id = application.get("operationId")
    evidence_ref = application.get("evidenceRef")
    for name, value in (("operationId", operation_id), ("evidenceRef", evidence_ref)):
        if not isinstance(value, str) or not value.strip():
            raise ApplicationEvidenceError(f"application.{name} must be a non-empty reference")
    native_target = application.get("nativeTarget")
    if not isinstance(native_target, Mapping):
        raise ApplicationEvidenceError("application.nativeTarget must be an object")
    for name in NATIVE_TARGET_FIELDS:
        value = native_target.get(name)
        if name == "generation":
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ApplicationEvidenceError(
                    "application.nativeTarget.generation must be a non-negative integer")
            continue
        if not isinstance(value, str) or not value.strip():
            raise ApplicationEvidenceError(
                f"application.nativeTarget.{name} must be a non-empty reference")
    applied_revision = application.get("appliedRevision")
    if applied_revision is not None and not isinstance(applied_revision, str):
        raise ApplicationEvidenceError("application.appliedRevision must be a string or null")
    return {
        "operationId": operation_id,
        "nativeTarget": {name: native_target[name] for name in NATIVE_TARGET_FIELDS},
        "appliedRevision": applied_revision,
        "evidenceRef": evidence_ref,
    }


def same_routing_identity(left: Mapping[str, Any] | None,
                          right: Mapping[str, Any] | None) -> bool:
    """Whether two native identities are the same owner/UID/generation.

    ``None`` on both sides means "nothing to fence"; ``None`` on one side
    only is a mismatch, because an unobserved answer is never treated as the
    observed one.
    """
    if left is None or right is None:
        return left is None and right is None
    try:
        return all(left[name] == right[name] for name in NATIVE_TARGET_FIELDS)
    except (KeyError, TypeError):
        return False


def observed_routing_identity(port: Any, target: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """The optional ``routing_identity`` of ``port``, normalized or ``None``.

    An absent method, a refusal or a malformed answer all read as "not
    observed" - never as a default identity.
    """
    reader = getattr(port, "routing_identity", None)
    if not callable(reader):
        return None
    try:
        raw = reader(dict(target))
    except Exception:  # noqa: BLE001 - an unobserved identity is never a guess
        return None
    if not isinstance(raw, Mapping):
        return None
    identity: dict[str, Any] = {}
    for name in NATIVE_TARGET_FIELDS:
        value = raw.get(name)
        if name == "generation":
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                return None
            identity[name] = value
            continue
        if not isinstance(value, str) or not value.strip():
            return None
        identity[name] = value
    return identity


def submission_operation_key(client_key: str, target: Mapping[str, Any], *,
                              sequence: int, config_version: int,
                              routing_identity: Mapping[str, Any] | None = None) -> str:
    """The version-bearing operation key handed to the port.

    The client's ``operationKey`` stays the submission's idempotency key; the
    key that reaches the real application is *derived* from it plus the frozen
    ``sequence``, the frozen provider-config ``config_version`` and - when the
    port can observe one - the native ``owner``/``canonicalUid``/
    ``generation``. Two plans therefore differ as soon as any of those
    changed, and an unversioned legacy ``mp-`` key can never address this
    submission (appendix §5, M10).
    """
    basis = "|".join((
        client_key,
        *(str(target[key]) for key in sorted(target)),
        f"s{sequence}", f"v{config_version}",
        *(f"{name}={routing_identity[name]}"
          for name in NATIVE_TARGET_FIELDS if routing_identity is not None),
    ))
    digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32]
    return f"mp-turn-s{sequence}-v{config_version}-{digest}"


__all__ = [
    "SUBMIT_READY", "SUBMIT_REFUSED", "SUBMIT_UNKNOWN", "SUBMIT_NO_INTENT",
    "PORT_OUTCOMES", "EVIDENCE_FIELDS", "NATIVE_TARGET_FIELDS",
    "ApplicationEvidenceError", "TurnIntentHandoverError", "SubmitResult",
    "TurnApplicationPort", "RoutingIdentityPort", "validated_application",
    "same_routing_identity", "observed_routing_identity", "submission_operation_key",
    "INTENT_ROUTE_PROFILE_OVERLAY", "INTENT_ROUTE_INDEPENDENT",
    "INTENT_ROUTE_HANDOVER_FAILED", "INTENT_ROUTES", "HANDOVER_UNRESOLVED",
]
