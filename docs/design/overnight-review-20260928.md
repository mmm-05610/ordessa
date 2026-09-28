# 011 overnight delivery review — 2026-09-28

## Verdict and scope

There are substantial reusable implementations, but no accepted integrated product delivery yet.
Do not merge the current C0 worktree wholesale: it has an unfinished merge with four unmerged Sandbox files.
Root main remains `cd7d31f3cfba6a0e1ec65f9a13014c6b9751540b`.

This review started around 09:38 Asia/Shanghai. No new agents, implementation, installations,
model calls, merges, branch changes or service operations were performed. Running Q1/Q3/Q4/Q5
were inspected read-only; their reports are not independently reproduced acceptance evidence.
The stopped Z1/Z2/Z3/Q2 worktrees were clean before and after the tests below.
C0 tests touched only the unaffected Pacthold/Harness test scope, not its conflicted Sandbox files.

## Independently reproduced tests

All commands below exited 0. These are package/controlled tests, not real-Harness product E2E.

| Worktree / reviewed HEAD | Command | Passed |
| --- | --- | ---: |
| Z1 `29445bc50b` | `.venv/bin/python -m pytest plugins/profile/tests -q` | 140 |
| Z1 | `npm run --workspace plugins/profile/api test` | 9 |
| Z1 | `npm run --workspace plugins/profile/integrations/chat test` | 10 |
| Z1 | `npm run --workspace plugins/profile/frontend test` | 9 |
| Z2 `f65a43d34f` | `npm run --workspace plugins/chat/api test` | 15 |
| Z2 | `npm run --workspace plugins/chat/frontend test` | 35 |
| Z3 `30c851f440` | `.venv/bin/python -m pytest plugins/assets/model-provider -q` | 137 |
| Z3 | `npm run --workspace plugins/assets/model-provider/desktop test` | 10 |
| Z3 | `npm run --workspace plugins/assets/model-provider/chat-contribution test` | 21 |
| Q2 `edffd54caf` | `.venv/bin/python -m pytest plugins/assets/prompts plugins/assets/command-templates -q` | 232 |
| C0 HEAD `080396ecaf`, merge in progress | `.venv/bin/python -m pytest packages/pacthold/tests/platform/test_us1_lifecycle_negatives.py packages/pacthold/tests/platform/test_us1_resource_lifecycle.py -q` | 28 |
| C0, same scope | `PYTHONPATH=plugins/harness/api/src .venv/bin/python -m pytest plugins/harness/tests/test_configuration_service_controlled.py plugins/harness/tests/test_server_acp_admission_binding.py -q` | 37 |

Total: **783 passed**. The initial Profile Chat command used the wrong directory (`chat-glue`);
npm correctly rejected it. The actual `integrations/chat` package was subsequently run and passed.
No full-server suite, new isolated install, browser geometry or real-model run was performed in this review.

## Concrete yield

- Foundation: an earlier immutable `codex/011-foundation-ready` checkpoint exists, naming implementation
  `8229e20824aa7db95ed8615a3d5122c2fbf81305`. It integrates the platform work and sidebar.
  Producer wheel-isolation/full-baseline evidence is recorded, but was not independently rerun here.
  Current C0 lifecycle tests independently confirm the tested stop/resource safeguards.
- Harness: public adapter API, configuration application service and journal, controlled application/readback
  and channel-admission bindings exist. This is more than DTO-only work; 37 selected tests passed.
  Native product authority and complete production submission wiring are nevertheless unfinished.
- Profile: storage/overlay/facet machinery, management UI and Chat contribution are implemented and tested.
  This does not establish that the default product can switch a real Harness Profile.
- Chat: ZCode-derived body/thought/tool components, project dialog, shared plus/slash input panel and
  attachment presentation exist. `upstream-manifest.json` records source commit and adaptations.
- Model-provider: server logic, adapters, settings and Chat contribution exist; controlled package tests pass.
  Real same-session provider changes/resume are not established by those tests.
- Q2: Prompts and command-template domain cores are substantial and pass 232 tests, despite the line stopping
  before UI, dependency consumption and runtime integration were complete.

## Consolidated blocking findings

### 1. C0 is not a mergeable delivery

`MERGE_HEAD=458add4f1b5ea00723d4b5d1c1e5d0aeca74e5a6`.
Unmerged files under `plugins/assets/sandbox/adapters/`:
`src/ordessa_sandbox_adapters/__init__.py`, `points.py`, `seam.py`, `tests/test_c3_seam.py`.
There are also staged Q5 changes. Preserve this state; do not reset or blindly accept either side.
Future recovery must reconcile C0 carrier binding with Q5's updated adapters and rerun their joint tests.

### 2. Published dependency snapshots and final branches disagree

The published `codex/011-profile-api-ready` still imports `AgentBoxProfileV1` from
`pacthold.resource_contracts`; Q1's consumed Profile copy has that same import at `plugin.py:17`.
Z1's final branch already imports it from `pacthold_runtime_compat.resource_contracts` at line 21.
Thus the reported consumer import blocker is not evidence that Z1's final implementation still needs
the same repair. Publish a corrected, reviewed successor checkpoint with correct dependencies and let
consumers consume that fixed SHA. Do not resurrect business exports in Pacthold to hide this mismatch.
The original Profile checkpoint also uses its feature branch as `planAnchorRef` and has empty `dependsOn`;
repair the publication metadata rather than silently moving an immutable ready ref.

### 3. Production next-submission gate remains unavailable

C0 `apps/server/src/ordessa_server/acp_admission.py:312` explicitly returns `False` from `ready`.
Its docstring says product authority and native/generation evidence are not wired.
Q5's report independently acknowledges the same product gap and an authority/private-host-type coupling.
Resolve the public authority boundary and wire the actual production evidence producer before claiming
Profile/model changes or permission checks are enforced on real submissions. Do not simply flip `ready`.

### 4. Chat presentation is delivered, product activation and transport are not

C0 `products/desktop/extensions.json` still enables the old agent-conversation chain, not the new Chat packages.
Z2 `plugins/chat/frontend/src/adapters/agent.ts` still uses `service.send(snapshot.text)`;
`facadeAttachmentCapability.supported` is false and the native command catalog returns absent.
Before activation, supply stable submission identity/outcome, actual attachment references and native command
directory through the service boundary. Then switch the product once, retire duplicate UI ownership and test
the integrated chain. UI fixture passes must not be promoted to transport/E2E passes.

### 5. Running lines are partial deliverables, not accepted product features

- Q1: Skills implementation exists; its committed report names six Profile integration reds plus missing native loading evidence.
- Q3: subagent-definition implementation exists; report records settings TypeScript failure and UI test failures,
  alongside hundreds of Python passes. Ready revision names do not establish whole-line completion.
- Q4: MCP storage/probe/managed clients and controlled integration exist; report claims 508 Python passes,
  but product assembly, Profile binding and authenticated principal injection remain open.
- Q5: policy/approval/Sandbox adapters and controlled admission tests exist; default-product enforcement and
  native evidence remain open. Its report discloses an earlier nonexistent test citation, subsequently replaced
  with actual tests; verify referenced artifacts rather than accepting historical green labels.

These active-line observations come from committed reports/source inspection, not independent execution.
Do not disturb their current tests or worktrees. Their final SHAs need a bounded follow-up acceptance.

## Why the rollout stalled and how to salvage it

The dispatch plan made C0 responsible for baseline, Harness, connectors, permissions integration, attachment/
command transport, all shared assembly, compat retirement and final integration. That exceeded the user's
intended initial-baseline role and concentrated most cross-line dependencies on one long-running session.
Z1's report records roughly 155 minutes and 60+ bounded polls waiting on Harness publication. This is direct
evidence of waiting overhead, not a token-usage measurement. Several ZCode reports also disclose subagent
quota failures and direct implementation fallback; no independent-review credit is assigned to those claims.

Recommended finite recovery sequence (not dispatched by this review):

1. Preserve the verified domain commits and separate the already published foundation from unfinished C0 integration.
2. Resolve only the current merge and publish corrected dependency snapshots; do not restart broad goals.
3. Give the production Harness/submission/authority chain a separate, bounded implementation owner instead of
   treating it as incidental baseline cleanup. Existing C0 code is an input, not a rewrite target.
4. Let each domain owner finish its own consumer wiring against that fixed checkpoint; final integrator only
   assembles, removes duplicate old ownership and runs the agreed integration gates.

No whole-rollout merge approval is issued. Z1/Z2/Z3 and Q2 domain cores have independently confirmed package
test evidence and are worth preserving; that is not equivalent to product readiness or complete code audit.
