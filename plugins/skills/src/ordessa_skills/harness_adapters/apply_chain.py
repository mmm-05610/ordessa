"""T13 — Q1's half of "下一次用户提交时先应用再发送", on published types.

The published seam (harness-api `ordessa_harness_api`): the Skills side
freezes the resolved snapshot into `DesiredFragment`s, asks the Harness's
`ConfigurationService` for a `Plan` bound to the expected revision, and —
only on a `Plan` — applies it with the caller-supplied submission permit
before the next user message is sent. Everything physical (HOME writes,
generation publication, spawn, restart, prompt sending) is Harness-owned;
this module only sequences the published DTOs and never interprets an
`Unknown` as success.

Conflict pre-check against the model/Prompts intent sets: the published
API offers NO seam to enumerate another facet's staged intents (the
harness `HarnessContributionRegistry` conflict authority compares
descriptor claims at REGISTRATION time — `FieldClaim` overlap — but no
public "plan-vs-plan" query exists in this tree). The Skills facet
declares content-directory claims disjoint from other facets, so the
registration-time guard is the pre-check that exists today; a live
plan-time cross-facet pre-check is registered as an API request
(api-requests.md §G2 follow-up), not faked here.

Honest rules (all pinned in tests):

* revisions moved → the service answers `Refused` (`STALE_PLAN`) and the
  chain performs NO write and consumes NO permit; a refusal preserves the
  original state (profile overrides untouched);
* an `Unknown` application outcome is reported as unknown — the effect
  level ceiling stays `projected` and the caller must re-`query`,
  never re-assume;
* a terminal execution is not revived: resume is only attempted with a
  published `ResumeRequest` whose instance/native identity/generation all
  match the frozen observation, and a refused/unknown resume never falls
  back to a fresh session;
* the resume verdict is by published TYPE, not shape: only the published
  positive-confirmation type (`RuntimeConfirmed`) can mark `applied`; a
  `NotFound`, an unknown kind, or any duck-typed object — even one with
  `kind == "confirmed"` — stays `unknown` with a typed reason (contracts.md
  §可用性最少区分: nothing unobserved impersonates success);
* the `plan` argument of `apply_before_send` is validated against the
  published `Plan` type BEFORE any service call: a non-`Plan` (a `Refused`,
  a duck-typed shape) raises the family's typed domain error
  (`HarnessAdapterError`, same fail-closed style as the stale/mismatched
  version refusals in `base.assess`) — never an untyped `AttributeError`;
* reload vs restart-and-resume comes from the adapter's assessed
  capability (`decide_reconfiguration`), unknown resume ⇒ `unsupported`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ordessa_harness_api import (
    ApplicationResult, ApplicationTarget, Confirmed, DesiredFragment,
    ErrorCode, NotFound, Plan, PlanResult, Refused, ReconfigurationDecision,
    ResumeRequest, RuntimeConfirmed, RuntimeRefused, Unknown,
)

from ..api import evidence as ladder
from .base import (
    RESTART_RESUME, REFUSE, HarnessAdapterError, decide_reconfiguration,
    decide_update_strategy,
)
from .capabilities import CapabilityStatement, statement_for
from .contribution import SKILLS_FACET_ID


@dataclass(frozen=True)
class SubmissionOutcome:
    """What Q1 reports for one 先应用再发送 round. `effect_level` is the
    strongest the evidence ladder can honour for THIS result — a Confirmed
    apply of placement content is still at most `projected` until a brand
    gains an evidenced load port."""

    state: str  # "applied" | "refused" | "unknown"
    result: ApplicationResult | PlanResult | None
    effect_level: str
    reason: str | None = None

    @property
    def may_send(self) -> bool:
        """Only an applied (or already-consistent) configuration lets the
        submission proceed; refusals and unknowns stop before the send."""
        return self.state == "applied"


def fragments_for(*, item_ids: Sequence[str], schema_version: str,
                  business_refs: Sequence[str], source_revision: str,
                  operation: str = "set") -> tuple[DesiredFragment, ...]:
    """Freeze the resolved snapshot into published desired fragments — one
    per managed asset, all pinned to the same `source_revision` face."""
    if len(item_ids) != len(business_refs):
        raise ValueError("item ids and business refs must pair up")
    return tuple(
        DesiredFragment(
            facet_id=SKILLS_FACET_ID, item_id=item_id,
            schema_version=schema_version, business_ref=business_ref,
            source_revision=source_revision, operation=operation)
        for item_id, business_ref in zip(item_ids, business_refs))


def plan_at_submission(service, target: ApplicationTarget,
                       fragments: tuple[DesiredFragment, ...],
                       expected_revision: str) -> PlanResult:
    """Freeze-snapshot -> plan. The service owns the revision fence; a
    moved face answers `Refused(STALE_PLAN)` before any reservation."""
    return service.plan(target, fragments, expected_revision)


def apply_before_send(service, *, plan: Plan, operation_key: str,
                      submission_permit: str,
                      statement: CapabilityStatement) -> SubmissionOutcome:
    """Apply an already-planned change; classify the published result.

    The caller only invokes this with a `Plan` (a `Refused` plan result
    means NO write and NO permit — that is the refuse-then-no-write
    rule). The argument is TYPE-VALIDATED first: anything that is not the
    published `Plan` raises the typed `HarnessAdapterError` before the
    service is touched — no untyped `AttributeError`, no apply, no permit
    consumed. The returned outcome never promotes an `Unknown` and never
    out-grades the evidence ceiling.
    """
    if not isinstance(plan, Plan):
        raise HarnessAdapterError(
            "HARNESS_APPLY_PLAN_REQUIRED",
            "apply_before_send requires the published `Plan` type, got "
            f"{type(plan).__name__}; a Refused or duck-typed plan-result is "
            "a typed refusal before any service call")
    result = service.apply(plan.plan_id, operation_key, submission_permit)
    ceiling = ladder.PROJECTED  # skills placement today; see base.evidence_ceiling
    if isinstance(result, Confirmed):
        return SubmissionOutcome(
            state="applied", result=result,
            effect_level=_capped(ladder.PROJECTED, ceiling),
            reason=None)
    if isinstance(result, Refused):
        return SubmissionOutcome(
            state="refused", result=result, effect_level=ladder.UNKNOWN,
            reason=f"{result.code.value}: original state preserved="
                   f"{result.original_state_preserved}")
    if isinstance(result, Unknown):
        return SubmissionOutcome(
            state="unknown", result=result, effect_level=ladder.UNKNOWN,
            reason=f"phase={result.phase} allowed_next={result.allowed_next_action}")
    return SubmissionOutcome(state="unknown", result=None,
                             effect_level=ladder.UNKNOWN,
                             reason="unrecognised application result")


def _capped(claimed: str, ceiling: str) -> str:
    order = {ladder.STORED: 0, ladder.SELECTED: 1, ladder.PROJECTED: 2,
             ladder.LOADED: 3, ladder.USED: 4}
    return claimed if order[claimed] <= order[ceiling] else ceiling


def reconfiguration_for(statement: CapabilityStatement,
                        affected_instance_refs: Sequence[str]
                        ) -> ReconfigurationDecision:
    """Reload vs restart-and-resume vs unsupported, on the published type."""
    return decide_reconfiguration(statement,
                                  affected_instance_refs=affected_instance_refs)


def resume_after_reconfiguration(
    runtime, decision: ReconfigurationDecision, *, instance_ref: str,
    expected_native_session_identity: str, expected_generation: int,
) -> SubmissionOutcome:
    """Restart-and-resume WITHOUT a blank-session fallback.

    Only a `restart-resume` decision reaches the runtime's `resume`; a
    `reload` decision is session-local for the affected instances and
    needs no restart; `unsupported` refuses here — the harness must not
    start a fresh native session behind the user's back (恢复失败不另起
    空会话代替). Only the published confirmation type (`RuntimeConfirmed`)
    can mark applied — a `NotFound`, an unknown kind or any duck-typed
    object, even one shaped with `kind == "confirmed"`, stays `unknown`
    with a typed reason."""
    if decision.mode == "reload":
        return SubmissionOutcome(state="applied", result=None,
                                 effect_level=ladder.PROJECTED,
                                 reason="reload is session-local; no restart")
    if decision.mode != "restart-resume":
        return SubmissionOutcome(
            state="refused", result=None, effect_level=ladder.UNKNOWN,
            reason=f"reconfiguration mode {decision.mode!r} does not "
                   "evidence a resume; refusing instead of a blank session")
    try:
        request = ResumeRequest(
            instance_ref=instance_ref,
            expected_native_session_identity=expected_native_session_identity,
            expected_generation=expected_generation)
    except Exception as exc:  # ContractError: identity/generation not proven
        return SubmissionOutcome(state="refused", result=None,
                                 effect_level=ladder.UNKNOWN,
                                 reason=f"resume unprovable: {exc}")
    result = runtime.resume(request)
    if isinstance(result, RuntimeRefused) or getattr(result, "kind", "") == "refused":
        return SubmissionOutcome(
            state="refused", result=result, effect_level=ladder.UNKNOWN,
            reason="resume refused; the terminal/unknown execution stays terminal")
    if isinstance(result, RuntimeConfirmed):
        # THE only path to applied: the published positive-confirmation
        # type. A shape with kind="confirmed" that is not this type — or a
        # NotFound, or anything else unobserved — never counts (fails
        # closed to unknown, never open to applied).
        return SubmissionOutcome(state="applied", result=result,
                                 effect_level=ladder.PROJECTED, reason=None)
    observed = getattr(result, "kind", None)
    observed = observed if isinstance(observed, str) else type(result).__name__
    return SubmissionOutcome(
        state="unknown", result=result, effect_level=ladder.UNKNOWN,
        reason=f"resume result {observed!r} is not the published "
               "confirmation type (RuntimeConfirmed); unobserved stays "
               "unknown — query/reconcile only, never re-assume")
