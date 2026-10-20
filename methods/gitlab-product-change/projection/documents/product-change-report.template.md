# GitLab Product Change — Complete Flow Report

> This is a report format for externally performed work. Fill every section, including explicit `not_started`, `skipped`, `deferred`, `blocked`, or `not_applicable` states where applicable. A skipped or deferred phase needs a recorded rationale and decision owner. Record source links and exact observed versions. This document contains authored claims; it does not itself prove that Git, CI, review, or deployment events occurred.

## Issue and ownership

- Project / issue URL and title:
- Work type and product area:
- Primary DRI and phase-specific roles:
- Issue state model, exact observed value, and observation time:
- Source links:

## Validation track

- Problem validation: status, owner, evidence, hypothesis, decision, rationale:
- Design: status, owner, design refs, accessibility/security/privacy considerations, decision:
- Solution validation: status, owner, research / experiment evidence, success metric, decision:
- If skipped or shortened: work-type reason, confidence basis, approver, follow-up:

## Build track

- Plan and prioritization: scope/MVC, weight, milestone, dependency, owner, decision:
- Development: status, source revision / commit refs, owner, blockers:
- Testing: required checks, results, environment, exact evidence refs:
- Review: merge requests, reviewers, approvals, pipeline references, remaining issues:
- Verification: staging / production verification and exact deployed version:
- If skipped or deferred: rationale, approving DRI, next review time:

## Validation/build coordination

- Links showing which activities overlapped, handed off, blocked, or informed each other:
- Work-type-specific decisions to skip or shorten either track:

## Blockers and rework

- Each blocker: cause, owner, opened time, expected resolution, actions, escalation, resolution:
- Each rework: trigger, source phase, new issue/revision, exit criteria, outcome:
- Deferred/cancelled/rejected decision, approver, reason, and next action:

## Deployment and version binding

- Target: GitLab.com, self-managed, both, another target, or not selected; rationale:
- GitLab.com path events, if applicable (environment, version, outcome, time, evidence):
- Self-managed upstream stable/tag/release/package publication and availability (version, outcome, time, evidence):
- Separately, optional named Self-Managed target instance installation/upgrade and live-version verification:
- Post-deployment migrations and their completion evidence:
- Merge commit(s) are recorded separately from deployed/live version:
- Deployment owner, production/staging verification decision, exact evidence:

## Result and follow-up

- Evaluation window and metric definitions:
- Baseline, target, observed outcome, source, owner (integers as JSON integers; decimal values as exact decimal strings such as `0.70`, or `null` when unknown):
- Customer / operational feedback:
- Decision: continue, iterate, rollback, abandon, restart validation, extend measurement, unknown, or not applicable:
- Follow-up issues, owners, and dates:
- Closure / postponement / cancellation decision and approver:

## Method/source identity

- Exact released method ref used in method-bound content:
- Exact product-flow handbook URL and observation date:
- Version/status-model differences relevant to this report:
