"""T12 — drive the complete managed set through one submit permit, then send once.

This module is an **orchestrator** over C0's published `ConfigurationService`
port (`ordessa_harness_api.application`), not a second implementation of it.
It freezes the ordering the design requires (`contracts.md` §C4, §C5 and
`verification.md` gates G18/G19/G20) and is deliberately honest about which
half can actually run in this tree today.

What is real here
-----------------
* :class:`ApplyCoordinator` accepts a host-injected, `ConfigurationService`
  **Protocol**-shaped collaborator (`inspect/plan/apply/query/reconcile`,
  `plugins/harness/api/src/ordessa_harness_api/application.py:211-217`) and the
  host-supplied `ApplicationTarget` + `TargetHandle`. It calls
  ``service.plan`` then ``service.apply`` (the same two calls C0's controlled
  service exposes at
  `plugins/harness/src/ordessa_harness/application/configuration_service.py:202,239`)
  and maps each returned DTO — `Confirmed` / `Refused` / `Unknown`
  (`application.py:130-181`) — onto the send-gate. It never writes a file,
  spawns a process, opens a network endpoint or speaks ACP itself (FR08); the
  effectful steps stay C0's.

Today's reality check (the honest default)
------------------------------------------
The default product's ACP admission port reports ``ready=False``: no one-use
execution permit, no native runtime generation and no operation-bound native
receipt are wired in this tree, and C0's own checkpoint says restart reconcile
must therefore remain Unknown
(`specs/011-plugin-rollout/checkpoints/harness-api.json` §limitations,
`specs/011-q3-subagents/api-requests.md` SR-2 / SR-3b / SR-12). So with no
injected service, :meth:`ApplyCoordinator.plan_apply` returns a **typed refusal
naming the missing port** — never a simulated success. There is deliberately no
fake "permit" object standing in for the missing authority. A flow that actually
reaches ``Confirmed`` and releases a message requires a *controlled fixture*
service (as C0's own tests build); the fixture-level tests in
`tests/test_apply_t12.py` are labelled L1/L2 and are **not** production
G18/G19/G20 evidence.

Single-use send (G18)
---------------------
:class:`MessageRelease` carries the original message and hands it out exactly
once by *moving the payload off the object* — there is no boolean flag and no
stored message left to re-send. ``plan_apply`` releases at most once per
`operationKey` (replays short-circuit before reaching the effect path), and a
`Refused`/`Unknown` result never releases at all.

Same-session resume (G19)
-------------------------
The caller supplies the host-observed native session identity together with the
pinned one; a missing or mismatched identity — including a fresh ``session/new``
identity — is refused with a named reason. A new session is never accepted as
restoration.

Busy / unload ordering (G20)
----------------------------
An unsettled (`Unknown`) operation marks its target busy: a superseding plan on
that target and an unload request are both refused `PROVIDER_BUSY`. The current
generation is pinned from the host's `TargetHandle.generation`; a plan carrying
an older generation is refused and never applied, so a late plan cannot land
after the adapter it depended on has gone away.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Mapping, Sequence

from ordessa_harness_api import (
    ApplicationResult,
    ApplicationTarget,
    ConfigurationService,
    Confirmed,
    DesiredFragment,
    NotFound,
    OperationRecord,
    Plan,
    PlanResult,
    Refused,
    TargetHandle,
    Unknown,
)

from . import errors

if TYPE_CHECKING:  # pragma: no cover - import for typing only, never at runtime
    # The orchestrator treats the pinned snapshot as an opaque host-supplied
    # input (it never reads its fields), so this stays a typing-only import:
    # it keeps `apply` free of the resolution/ceiling chain at runtime and
    # robust while the adapters/resolution seam is being remapped elsewhere.
    from .resolution import DefinitionSnapshot

FACET_ID = "assets.native-subagents"

#: A native session identity the host uses to denote a freshly created session
#: (the ``session/new`` shape C0's checkpoint warns must never pass as
#: restoration — verification.md G19 negative). Any identity that merely differs
#: from the pinned one is refused too; this sentinel makes the negative explicit.
NEW_SESSION_SENTINEL = "session:new"

#: The production collaborators that must be wired before any ``plan_apply`` can
#: reach a real ``Confirmed``. The default product's admission port reports
#: ``ready=False`` and none of these are present in this tree today
#: (harness-api.json limitations; SR-2 / SR-3b / SR-12).
PRODUCTION_COLLABORATORS: tuple[tuple[str, str], ...] = (
    ("acp_admission_port_ready",
     "the ACP admission port must report ready=True (default product: ready=False)"),
    ("one_use_execution_permit",
     "a one-use submission execution permit minted and verified by the host "
     "(no Q5 production verifier is installed)"),
    ("native_runtime_generation",
     "an instance-private native runtime generation to activate (SR-2)"),
    ("operation_bound_native_receipt",
     "an operation-bound native readback receipt so restart reconcile can be "
     "decided rather than left Unknown (SR-2 / SR-12)"),
)


def missing_production_collaborators() -> tuple[str, ...]:
    """Machine-checkable seam report: the exact production collaborators absent
    in this tree today. The main agent can cite this list instead of hand-waving.

    It is a *static* description of the wiring gap (the admission port is
    ``ready=False`` here); it is not a runtime probe and does not claim a brand
    works.
    """
    return tuple(name for name, _ in PRODUCTION_COLLABORATORS)


def production_gap_detail() -> Mapping[str, str]:
    return dict(PRODUCTION_COLLABORATORS)


class ApplyStatus(str, Enum):
    """Outcome of one orchestration step, orthogonal to C0's result DTO."""

    CONFIRMED = "confirmed"
    REFUSED = "refused"
    UNKNOWN = "unknown"
    ABSENT = "absent"  # no injected ConfigurationService -> the honest default


@dataclass(frozen=True)
class ApplyOutcome:
    """The recorded result for one ``operationKey``.

    ``release`` is the single-use :class:`MessageRelease` handed out only on a
    first ``Confirmed``; ``None`` on every other path (a refusal never carries
    one). ``service_result`` keeps C0's returned DTO (or the replayed
    ``OperationRecord``) so an ``Unknown`` stays queryable.
    """

    status: ApplyStatus
    reason_code: str | None = None
    detail: str | None = None
    service_result: object | None = None
    release: "MessageRelease | None" = None
    item_diagnostics: tuple[str, ...] = ()

    @property
    def released(self) -> bool:
        return self.release is not None


@dataclass(frozen=True)
class PlanApplyRequest:
    """One submission's frozen input, all supplied by the host.

    The orchestrator never derives a target, a generation or a session identity
    itself: they are inputs (§C3 "targets owned by Harness"; §C4 the submit gate
    freezes profile/assignment/revision/target generation). ``fragments`` are the
    real C0 `DesiredFragment`s the (separately-owned) adapters compiled for the
    *complete* managed collection (§C3 one-shot).
    """

    snapshot: DefinitionSnapshot
    target: ApplicationTarget
    handle: TargetHandle
    fragments: tuple[DesiredFragment, ...]
    operation_key: str
    submission_permit: str
    expected_revision: str
    pinned_session_identity: str
    host_session_identity: str | None
    original_message: str

    def __post_init__(self) -> None:
        if not isinstance(self.target, ApplicationTarget):
            raise errors.refused(errors.TARGET_CONFLICT, detail="target must be an ApplicationTarget")
        if not isinstance(self.handle, TargetHandle):
            raise errors.refused(errors.TARGET_CONFLICT, detail="target must carry a host TargetHandle")
        if not isinstance(self.fragments, tuple) or not self.fragments:
            raise errors.refused(
                errors.DEFINITION_INVALID,
                detail="plan_apply needs the complete collection as nonempty DesiredFragments",
            )
        if any(not isinstance(item, DesiredFragment) for item in self.fragments):
            raise errors.refused(errors.DEFINITION_INVALID, detail="every fragment must be a DesiredFragment")
        if not self.operation_key or not self.original_message:
            raise errors.refused(errors.DEFINITION_INVALID, detail="operation_key and message must be non-empty")


class MessageRelease:
    """A single-use authorization to send the original user message exactly once.

    The payload is *moved off* the object on release, so a second ``release()``
    returns ``None``. There is no boolean flag and no copy of the message kept
    reachable: switching this to a boolean-and-stored-message design would let a
    later caller re-send, which is precisely the G18 negative this type exists to
    make structurally impossible.
    """

    __slots__ = ("_payload",)

    def __init__(self, message: str) -> None:
        if not isinstance(message, str) or not message:
            raise errors.refused(errors.DEFINITION_INVALID, detail="a release only exists for a real message")
        self._payload: str | None = message

    def release(self) -> str | None:
        """Return the message the first time, ``None`` on every call after that."""
        payload, self._payload = self._payload, None
        return payload

    @property
    def spent(self) -> bool:
        return self._payload is None


class ApplyCoordinator:
    """Order C0's ``plan -> apply`` and gate the message send on the outcome.

    The service is injected, never constructed here: the real C0
    ``ConfigurationApplicationService`` needs a carrier, a controlled runtime, a
    permit verifier and a journal (all host-owned authorities), and none of them
    exist as production collaborators in this tree today. Absent a service, the
    honest default is a typed refusal, not a simulated run.
    """

    def __init__(self, *, service: ConfigurationService | None = None,
                 outbox: list[str] | None = None) -> None:
        self._service = service
        self._outbox: list[str] = outbox if outbox is not None else []
        # Recorded per operation key -> the source of replay idempotency.
        self._outcomes: dict[str, ApplyOutcome] = {}
        # Target -> the operation key still unsettled (Unknown) -> busy (G20).
        self._busy: dict[ApplicationTarget, str] = {}
        # handle_id -> highest generation the coordinator has landed (G20 pin).
        self._generations: dict[str, int] = {}

    # -- seam report ----------------------------------------------------------

    @property
    def has_service(self) -> bool:
        return self._service is not None

    @property
    def outbox(self) -> tuple[str, ...]:
        return tuple(self._outbox)

    def release_for(self, operation_key: str) -> MessageRelease | None:
        outcome = self._outcomes.get(operation_key)
        return outcome.release if outcome is not None else None

    # -- main flow ------------------------------------------------------------

    def plan_apply(self, request: PlanApplyRequest) -> ApplyOutcome:
        if not isinstance(request, PlanApplyRequest):
            raise errors.refused(errors.DEFINITION_INVALID, detail="plan_apply needs a PlanApplyRequest")

        # 1. honest default: no injected ConfigurationService -> typed refusal
        #    naming the missing production port; never a simulated success.
        if self._service is None:
            return ApplyOutcome(
                ApplyStatus.ABSENT,
                reason_code=errors.NATIVE_ENTRY_UNAVAILABLE,
                detail=(
                    "no ConfigurationService collaborator is wired: the default product's "
                    "ACP admission port reports ready=False, so there is no one-use execution "
                    f"permit, no native runtime generation and no operation-bound receipt; "
                    f"missing collaborators: {', '.join(missing_production_collaborators())}"
                ),
                item_diagnostics=missing_production_collaborators(),
            )

        operation_key = request.operation_key

        # 2. idempotent replay by operationKey: return the recorded outcome,
        #    do not re-plan, do not re-apply, do not re-send.
        prior = self._outcomes.get(operation_key)
        if prior is not None:
            return prior

        # 3. busy (G20): an unsettled operation on this target blocks a
        #    *superseding* plan (a different operation key on the same target).
        busy_op = self._busy.get(request.target)
        if busy_op is not None and busy_op != operation_key:
            return ApplyOutcome(
                ApplyStatus.REFUSED,
                reason_code=errors.PROVIDER_BUSY,
                detail=(f"target is busy: operation {busy_op!r} is unsettled; a superseding plan "
                        f"({operation_key!r}) is refused before any native effect so reset/reconcile "
                        "keeps an owner"),
            )

        # 4. same-session resume (G19): require and compare the native identity.
        session_refusal = self._check_session(request)
        if session_refusal is not None:
            return session_refusal

        # 5. generation pin (G20): a stale generation cannot land.
        current_gen = self._generations.get(request.handle.handle_id)
        if current_gen is not None and request.handle.generation < current_gen:
            return ApplyOutcome(
                ApplyStatus.REFUSED,
                reason_code=errors.REVISION_STALE,
                detail=(f"plan for generation {request.handle.generation} is older than the landed "
                        f"generation {current_gen}; a late plan is marked stale and never applied"),
            )

        # 6. drive C0's plan -> apply.
        plan_result: PlanResult = self._service.plan(
            request.target, request.fragments, request.expected_revision)
        if isinstance(plan_result, Refused):
            # Refusal before any native effect; previous applied state untouched,
            # reason surfaced per item, no release.
            return self._record(operation_key, ApplyOutcome(
                ApplyStatus.REFUSED,
                reason_code=plan_result.code.value,
                detail="configuration plan refused before any native effect",
                service_result=plan_result,
                item_diagnostics=plan_result.diagnostics,
            ))

        if not isinstance(plan_result, Plan):
            return self._record(operation_key, ApplyOutcome(
                ApplyStatus.UNKNOWN,
                reason_code=errors.OPERATION_UNKNOWN,
                detail="plan returned neither a Plan nor a Refusal; treated as Unknown",
            ))

        result: ApplicationResult = self._service.apply(
            plan_result.plan_id, operation_key, request.submission_permit)
        return self._finish(request, result)

    def reconcile(self, operation_key: str) -> ApplyOutcome:
        """Re-query an operation; an Unknown stays queryable, never silently
        resolved to success (§C4/§C5: unknown results must be queryable, no
        auto-retry of the prompt)."""
        if self._service is None:
            return ApplyOutcome(
                ApplyStatus.ABSENT,
                reason_code=errors.NATIVE_ENTRY_UNAVAILABLE,
                detail="cannot reconcile without a ConfigurationService (admission port ready=False)",
                item_diagnostics=missing_production_collaborators(),
            )
        record = self._service.query(operation_key)
        if isinstance(record, NotFound):
            return ApplyOutcome(
                ApplyStatus.REFUSED,
                reason_code=errors.OPERATION_UNKNOWN,
                detail=f"operation {operation_key!r} not found",
                service_result=record,
            )
        return self._finish_for_key(operation_key, record.target, record.result)

    def request_unload(self, target: ApplicationTarget) -> ApplyOutcome:
        """Ask to unload the adapter/provider for a target. While an operation on
        it is unsettled the unload is refused PROVIDER_BUSY (§C5: an active target
        that still needs reset/reconcile must be busy, not unloaded-then-orphaned).
        """
        if not isinstance(target, ApplicationTarget):
            raise errors.refused(errors.TARGET_CONFLICT, detail="unload needs an ApplicationTarget")
        busy_op = self._busy.get(target)
        if busy_op is not None:
            return ApplyOutcome(
                ApplyStatus.REFUSED,
                reason_code=errors.PROVIDER_BUSY,
                detail=(f"cannot unload: operation {busy_op!r} on the target is unsettled and still "
                        "owns reset/reconcile; unloading first would leave no owner (G20 negative)"),
            )
        return ApplyOutcome(ApplyStatus.CONFIRMED, detail="no unsettled operation; unload may proceed")

    # -- internals ------------------------------------------------------------

    def _check_session(self, request: PlanApplyRequest) -> ApplyOutcome | None:
        pinned = request.pinned_session_identity
        observed = request.host_session_identity
        if observed is None or not observed.strip():
            return ApplyOutcome(
                ApplyStatus.REFUSED,
                reason_code=errors.NATIVE_ENTRY_UNAVAILABLE,
                detail=("resume needs the host-observed native session identity; it is absent, so the "
                        "result is Unknown and no message is sent (never treated as a fresh session)"),
            )
        if observed == NEW_SESSION_SENTINEL or observed != pinned:
            return ApplyOutcome(
                ApplyStatus.REFUSED,
                reason_code=errors.NATIVE_ENTRY_UNAVAILABLE,
                detail=(f"observed native session identity {observed!r} is not the pinned "
                        f"{pinned!r}: a new/`session/new` session is never accepted as restoration (G19)"),
            )
        return None

    def _finish(self, request: PlanApplyRequest, result: ApplicationResult) -> ApplyOutcome:
        return self._finish_for_key(request.operation_key, request.target, result,
                                    request=request)

    def _finish_for_key(self, operation_key: str, target: ApplicationTarget,
                        result: ApplicationResult, *,
                        request: PlanApplyRequest | None = None) -> ApplyOutcome:
        prior = self._outcomes.get(operation_key)
        if prior is not None:
            return prior

        if isinstance(result, Confirmed):
            if request is None:
                # Reconcile reaching a Confirmed without the original message in
                # hand must not fabricate a second send; require the request.
                outcome = ApplyOutcome(
                    ApplyStatus.UNKNOWN,
                    reason_code=errors.OPERATION_UNKNOWN,
                    detail="reconciled Confirmed without the original submission context",
                    service_result=result,
                )
                return self._record(operation_key, outcome)
            release = MessageRelease(request.original_message)
            sent = release.release()  # structurally once
            if sent is not None:
                self._outbox.append(sent)
            if request.handle is not None:
                landed = self._generations.get(request.handle.handle_id)
                gen = request.handle.generation
                self._generations[request.handle.handle_id] = gen if landed is None else max(landed, gen)
            self._busy.pop(target, None)  # settled -> target no longer busy
            outcome = ApplyOutcome(
                ApplyStatus.CONFIRMED,
                service_result=result,
                release=release,
            )
            return self._record(operation_key, outcome)

        if isinstance(result, Unknown):
            # No release, no auto retry, no overwrite-clear; stay busy and queryable.
            self._busy[target] = operation_key
            outcome = ApplyOutcome(
                ApplyStatus.UNKNOWN,
                reason_code=errors.OPERATION_UNKNOWN,
                detail=("configuration result is Unknown: no message is sent, no retry, no overwrite "
                        "clear; the operation stays queryable by operationKey"),
                service_result=result,
            )
            return self._record(operation_key, outcome)

        if isinstance(result, Refused):
            outcome = ApplyOutcome(
                ApplyStatus.REFUSED,
                reason_code=result.code.value,
                detail="configuration apply refused; previous applied state untouched, no message",
                service_result=result,
                item_diagnostics=result.diagnostics,
            )
            return self._record(operation_key, outcome)

        return self._record(operation_key, ApplyOutcome(
            ApplyStatus.UNKNOWN,
            reason_code=errors.OPERATION_UNKNOWN,
            detail="unrecognised configuration result; treated as Unknown, no send",
        ))

    def _record(self, operation_key: str, outcome: ApplyOutcome) -> ApplyOutcome:
        self._outcomes[operation_key] = outcome
        return outcome
