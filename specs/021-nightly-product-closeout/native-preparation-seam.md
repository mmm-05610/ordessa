# Native first-submission preparation — implementation seam

Approved product behavior remains unchanged: draft/selection creates nothing;
first explicit submit initializes one dedicated channel, prepares its Profile
provider, calls session/new once, registers the observed owner, applies the C4
configuration and only then prompts. Existing live submissions never rerun
initial preparation. Unknown results are queried, not replayed blindly.

This is implementation work within the existing closeout tree, not another
work-order system. The incremental-work-order setup is waived in favour of
the existing Spec Kit plan/progress document; its ownership, counterexample
and primary-agent re-verification requirements apply. Main is the only
contract/progress/git writer. Up to three bounded subagents, depth one,
no new worktree/goal, no real models, no installation or global state changes.

## Fixed public contract

Agent contracts provide optional `AgentNativePreparation.beforeCreate` with
only `{attemptId, serverInstanceId, connectionId, harnessId, workspaceId}`.
ACP invokes it after managed channel initialize and before session/new.
It is public, typed plugin glue, not private transport interception. It has
no Profile-specific fields. An existing prepared owner bypasses this hook.
Failure before session/new retains the channel/attempt and allows an explicit
retry; once session/new is attempted its promise (including unknown failure)
remains cached and never creates again. Concurrent same-attempt calls join.

Profile client/backend expose `profiles.v2.prepareNativeCreation` with exact
`{connectionId, profileId, operationId}`. Operation ID is `create:<attemptId>`.
Response is exactly `{state, operationId, connectionId, profileId, harnessId,
profileRevision}`; state is prepared / not-required / unknown. It is never
an applied receipt, native identity or credential projection. Glue validates
all identity fields; unknown or malformed response prevents creation/send.
Selected Codex/Claude with no preparation service is unsupported, not fallback.
Pi may keep its existing validated launch configuration (not-required);
its actual C4 apply still verifies routing after observed creation.

## Backend invariants

- Require active backend channel, supported installed route, local nonarchived
  matching-Harness Profile, complete non-conflicting model choice resolution.
- Resolve secret references only at trusted backend preparation; Harness owns
  protocol/provider/header dialect. Never publish/store secrets in evidence.
  Missing secret store/reference fails closed before effects.
- Reserve operation identity and resolved Profile/catalogue revisions before
  effects. Reuse only identical inputs; changed references/revisions refused.
  Once an effect may have happened query retained owner-only operation instead
  of resending prepare. Unknown blocks session/new.
- Require dedicated empty channel; channel ended/replaced/shared or already
  native-owned cannot receive initial preparation. No native session creation
  by Profile, no canonical identity until register observes session/new.
- Startup credential evidence is backend-private and fenced to channel and
  preparation. C4 must not simply drop credentialRef to bypass its guard.
  Supporting that later apply is separate from a startup ACK.

## Independent units / file ownership

1. Backend: products/server Profile preparation/session files and new tests;
   Profile Python server_plugin.py/test_server_plugin.py; model-provider
   server credential application helper/tests; Harness Python initial model
   preparation helper/tests. No frontend/host/core/source manifest edits.
2. Frontend: agent/sessions model and tests; connectors/acp client and tests;
   Profile integrations/chat glue/tests. No public contract edits.
3. Evidence: new native-profile Python real-adapter C4 probe only. Synthetic
   loopback provider rejects inference; isolated HOME, no prompt, cleanup own
   children, separate actual adapter evidence from full Server/Profile UI.

Required counterexamples: preparation failure/unknown -> zero session/new and
zero prompt; same attempt concurrency -> one creation; native creation unknown
never retries; mismatched channel/Profile/realm/revisions -> zero effects;
retained startup query has no secret; supported native model + wrong endpoint
never confirms; actual C4 native receipt and independent owner readback, not
setter ACK. Primary agent reruns relevant suites and reviews the integration.
