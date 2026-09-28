# C — Frontend platform

Status: IMPLEMENTATION_REVIEW_READY (C lane only; T024 is a shared A/B/C checkbox and stays unticked here)
Source baseline: cd7d31f3cf (verified: branch codex/010-platform-frontend, merge-base with baseline = cd7d31f3cf; only docs commit 42bf446370 on top)
Head: the lane tip is the `_(this commit)_` row of the revision ledger at the bottom; the last
  fully-sha-pinned phase commit is `28eca02683` (T019). Nothing here is pushed — `main` merge is T025.

## Consistency check (speckit-analyze, C lane scope)

0 CRITICAL. MEDIUM findings resolved by in-lane interpretation (shared artifacts left untouched):
- T006 names `packages/workbench/api` before T017 moves the plugin → T006 creates the `packages/workbench` API-only scaffold (incl. workspace entry + shared-module mapping + real-build Token counterexample) at the new path; T017 migrates implementation onto it. Extension id `ordessa.workbench` preserved either way.
- Contract C4 "Chat" has no `plugins/chat` directory → resolves to `plugins/agent/conversation` (id `ordessa.agent-conversation`); "Connections" = `plugins/connections`; "connectors/acp" = `plugins/connectors/acp`; Server client = `plugins/connectors/ordessa`.
- T024 is one shared checkbox for A/B/C → C records its share here as C-DONE but does NOT tick T024 (all-lane gate); avoids fake green.
- LOW: apps/desktop/AGENTS.md L6–7 pins Token contracts to contracts/foundation + contracts/agent-ui; will be updated inside T018/T019 commits (file is C-owned).

## T003 — Frozen baseline (cd7d31f3cf + docs-only child)

### Environment
- node v22.22.1, npm 9.2.0 (root lockfile), Linux x64. `npm ci` at root and in `tests/acp-connector` both exit 0.

### Test ledger (vitest, serial per AGENTS.md)

| Suite | Command | Files | Tests | Pass | Fail | ID ledger |
| --- | --- | --- | --- | --- | --- | --- |
| apps/desktop renderer | `npx vitest run --maxWorkers=1` in apps/desktop | 13 | 146 | 146 | 0 | C-baseline/desktop.ids.txt |
| plugins/workbench | `npx vitest run --maxWorkers=1` in plugins/workbench | 3 | 27 | 27 | 0 | C-baseline/workbench.ids.txt |
| native-bridge | `npx vitest run` in packages/desktop-platform/native-bridge | 1 | 13 | 13 | 0 | C-baseline/native-bridge.ids.txt |
| tests/acp-connector | `npx vitest run --config tests/acp-connector/vitest.config.ts` (root) | 9 | 79 | 79 | 0 | C-baseline/acp-connector.ids.txt |
| **Total vitest** | | 26 | **265** | **265** | **0** | |

Baseline reds: none. Evidence JSON: /tmp/ordessa-C-evidence/T003-*.json (session-local; per-ID ledgers copied into reports/C-baseline/).

### Electron / script tests (frozen commands; exit codes verified this session unless noted)

| Script | Root command | Backend? |
| --- | --- | --- |
| empty-host smoke | `npm run test:electron` → apps/desktop/scripts/smoke-electron.mjs (temp userData, ORDESSA_EMPTY_HOST=1, test-only --no-sandbox) | none |
| agent-ui example | `npm run test:agent-ui` | none (example extension) |
| ui-preview | `npm run test:ui-preview` (writes docs/ui-preview artifacts) | none (fixture connectors) |
| agent-shell | `npm run test:agent-shell` (full 9-extension product, loopback fake server) | loopback fake only |
| extensions loader | `npm run test:extensions` | none |
| storage-restart / wire-redirect / pair-network-gate / ordessa-event-stream | direct `node apps/desktop/scripts/test-*.mjs` | local/loopback, WebSocket stubbed |
| test-native-two-turn.mjs / test-native-paired-no-send.mjs | direct, require external ready-file | REAL private Server — NOT run (no authorization this session; registered as untested) |

### Build gates (verified on this baseline, evidence /tmp/ordessa-C-evidence/T003-build-gates.txt)
- `npm run typecheck` → exit 0 (tsc --noEmit, apps/desktop).
- `npm run build:foundations` → exit 0, "Built 9 enabled extensions into products/desktop/dist".
- `npm run build` → exit 0 (same 9 extensions via apps/desktop build).
- `npm run test:electron` → exit 0; empty-host assertion output: ready=true, pages=[], rootMounted=false, emptyHost=true, errors=[], nodeAbsent=true, bridgeKeys=["read"].
- `npm run test:ui-preview` → exit 0. ui-preview regenerated docs/ui-preview PNGs; restored to committed values (local renderer pixel churn, no semantic change; registered as exit-code-only verification).
- CORRECTION (found during T017): an earlier draft of this report claimed `test:extensions` / `test:agent-ui` / `test:agent-shell` all exited 0 at the T003 baseline. That measurement was wrong — the shell pipeline `{ cmd | tail; echo $? }` reported tail's status. Re-measured with true exit codes (`cmd >log 2>&1; echo $?`) at baseline commit d4943cb229 (throwaway worktree, since removed): all three are **inherited reds on main**, per-ID classification:
  - `test:extensions`: red at case "enabled standalone React Hook page" — asserts pages ['Hello']; shell 7ff4ae99d2 ("single view renders bare") removed the tab-strip button for one-view regions, and the smoke probe derived pages only from `[role="group"]` tab buttons. Also requires `npm run build:examples` as a prerequisite not recorded in T003 commands (first run failed ENOENT examples/dist).
  - `test:agent-ui`: same selector drift for the single 'Agent UI 验证' view; needs `build:examples`.
  - `test:agent-shell`: same drift for single-view 'Conversation'/'Sessions'; needs `build:examples`. agentShell inner flags were green at baseline; only the pages assertions failed.
  No assertions were deleted; the fix landed in T017 (below).
- Determinism note: repeated `build:foundations` yields byte-identical bundles (cmp verified). Committed extensions.lock.json workbench entry.js digest was stale (lock last written at graft commit cd24ddd87d, before Workbench source commits de2af393d5/5ff2af966a/7ff4ae99d2); regenerated with the tool this session, per plan "锁由工具生成".

### Build & consumption paths (frozen)
- Typecheck: `npm run typecheck` (delegates to apps/desktop). Foundations build: `npm run build:foundations` → tooling/build-all.mjs scans roots `packages/desktop-platform/contracts` + `plugins` for `ordessa.id` package.json, admits only ids listed in products/desktop/extensions.json, builds into products/desktop/dist/extensions/<id>, writes extensions.lock.json (sha256). App build: `npm run build` (apps/desktop).
- Extension ids (9, = products/desktop/extensions.json enabled list): ordessa.contracts, ordessa.agent-contracts, ordessa.commands, ordessa.workbench, ordessa.agent-connections, ordessa.agent-sessions, ordessa.agent-server, ordessa.agent-acp, ordessa.agent-conversation.
- DI Token construction (all @lumino/coreutils Token, re-exported by extension-api):
  - CommandsToken 'ordessa.commands.v1' — packages/desktop-platform/contracts/commands/src/commands.ts:9
  - WorkbenchToken 'ordessa.workbench.v1' — packages/desktop-platform/contracts/workbench/src/workbench.ts:59
  - AgentConnectionsToken 'ordessa.agent.connections.v1' — packages/desktop-platform/contracts/connections/src/connections.ts:12
  - AgentSessionsToken 'ordessa.agent.sessions.v1' — packages/desktop-platform/contracts/agent/src/agent.ts:207
  - example GreetingToken — examples/service-contract/src/contract.ts:3; ad-hoc Tokens only in loader/host tests.
- Single-instance mechanism: consumers import `@extensions/<id>/contract.js`; esbuild externals keep it unbundled (tooling/build-extension.mjs, build-examples.mjs); extension-host/src/main/extension-protocol.ts injects import map @extensions/<id>/ → `ordessa:/extensions/<id>/` (one URL → one module instance). Test/type aliases mirror the same files (apps/desktop tsconfig+vitest, plugins/workbench vitest, tests/acp-connector vitest + acp-ts-hooks.mjs, test-ui-preview.mjs).
- contracts/foundation = platform-neutral re-export of contracts/{commands,workbench}; contracts/agent-ui = business re-export of contracts/{connections,agent} (this is the FR-009 target of T018: business types currently live in the platform package).
- contracts/{commands,workbench,connections,agent} are source-only dirs without package.json; only foundation and agent-ui are npm packages/extensions.
- plugins/workbench: package @ordessa/plugin-workbench, entry src/entry.tsx, `shared/` = registry.ts + boundary.tsx; byte-identical registry.ts copies exist in plugins/commands/shared and plugins/connections/service/shared (per-extension bundled, no runtime cross-import).

### apps/desktop/AGENTS.md compliance (T003 check)
- Host API v2 small/scope-bound: extension-host + extension-api verified against rules in later phase commits; "contracts/foundation + contracts/agent-ui" line will drift after T018 (see LOW finding above). No business imports in app.tsx verified at baseline; product defaults live in products/desktop/extensions.json. User extensions.json = complete override, never overwritten (extension-host/src/main/extensions.ts). Tests serial: all commands above use --maxWorkers=1 or single-file node scripts. Electron smoke: temp userData + test-only --no-sandbox confirmed in launch-smoke.mjs.

### Concept → owner map (resolves C2 ambiguity for T018)
| C4 term | Directory | Extension id |
| --- | --- | --- |
| Agent protocol (ACP) | plugins/connectors/acp | ordessa.agent-acp |
| Server client contract | plugins/connectors/ordessa | ordessa.agent-server |
| Chat | plugins/agent/conversation | ordessa.agent-conversation |
| Sessions (agent UI domain) | plugins/agent/sessions | ordessa.agent-sessions |
| Connections (generic mechanism) | packages/desktop-platform/connections (C6) | ordessa.connections (new built-in) |
| Agent connections facade/UI | plugins/agent/connections (C6, from plugins/connections/service) | ordessa.agent-connections (id kept) |
| Workbench / Commands (platform-neutral) | stay platform (packages/workbench / contracts/commands) | ordessa.workbench / ordessa.commands |

## C6 revision receipt (Connections → frontend platform)

- Checkpointed T003 at d4943cb229 and T006 at a31e4387d7 first; then cherry-picked docs-only commit e406625d9a cleanly (no tasks.md conflict; C-lane boxes kept, T026–T029 added). Revision commit in this branch: 649dfa5d66.
- Supersedes this report's earlier owner-map row "Connections → plugins/connections" (corrected above per contracts/connections-platform.md §1). T018's "connections" portion is now delivered through T027/T028; T018 keeps agent/chat/connectors type ownership.
- New completion condition: T024-C and review-readiness now require T026–T029 (CN-01–CN-08). Execution order adopted: T017 → T026/T027 → T028 → T018 → T019 → T020/T021 → T029 → T024-C, single-writer per package.

## T006 — Workbench API ownership + real-build Token counterexample

Implementation delegated to single-package subagent (no git), reviewed and re-verified by the main C session.

- New workspace package `packages/workbench` (`@ordessa/workbench`, private, no `ordessa.id` yet): subpath export `./api` → `api/workbench.ts` holds the Workbench public types and THE single `new Token('ordessa.workbench.v1')` construction site; `api/workbench.typecheck.ts` pins moved verbatim (both @ts-expect-error cases intact). Old `packages/desktop-platform/contracts/workbench/` deleted.
- `contracts/foundation/src/contract.ts` re-points to the new source (foundation remains the runtime carrier bundling the one shared copy; consumers keep importing `@extensions/ordessa.contracts/contract.js`, so plugins/host/runtime import map untouched). `apps/desktop/tsconfig.json` gains `../../packages/workbench/api` include. Root `package.json` workspaces += `packages/workbench`; lock regenerated via `npm install --package-lock-only` only.
- Real-build guard (`packages/workbench/tests/`, `node --test`, scanner `token-scan.mjs` reusable for T020/T021):
  - positive: builds product via tooling/build-all.mjs, scans every dist bundle; `ordessa.workbench.v1` and `ordessa.commands.v1` each constructed exactly once and only inside the `ordessa.contracts` bundle; presence asserted first so the gate cannot pass vacuously.
  - counterexample: a temp-dir rogue extension importing the api SOURCE directly (same esbuild externals as the real pipeline) yields a second bundled construction; scanner must report duplicate==2. Proves typecheck alone cannot satisfy the Token gate (quickstart gate "Token 反例").
  - `tests/index.js` works around the registered node v22.22.1 `node --test <dir>` quirk (plugins/harness/TEST-REVIEW.md) and auto-loads future T020/T021 suites.
- Main-session re-verification after review: `npm run typecheck` 0; `node --test packages/workbench/tests/` 2 pass / 0 fail; apps/desktop vitest 146/146 (13 files); plugins/workbench vitest 27/27 (3 files); `npm run build:foundations` 0 (9 extensions); `npm run test:electron` 0 with empty-host assertions unchanged. No test IDs lost (contracts/workbench had no runtime test files; type pins still in tsc program, verified via --listFiles).
- Residual historical doc mentions of the old path (docs/desktop-workbench-composition.md, docs/migration/desktop-migration-table.md) left as-is: history documents per AGENTS.md rule 6; root docs updated only at final integration.

## T017 — plugins/workbench → packages/workbench (platform package)

Move delegated to a single-package subagent (no git); main session reviewed file-by-file and re-ran every gate personally.

- Full package move, content-verified: `git show HEAD:plugins/workbench/<f>` vs `packages/workbench/<f>` is byte-identical for src/entry.tsx, src/model.ts, src/shell.tsx (before this section's fix), src/popover.ts, src/styles.ts, shared/{boundary,registry}, build.mjs, manifest.json, tests/popover.test.ts. The only deltas are path rewrites forced by the new location: tests/{composition,host-integration}.test.tsx import `../../../plugins/commands/src/entry`; vitest.config.ts aliases `../desktop-platform/contracts/...`. No assertion added or removed by the move; all 27 test IDs carried over (maps 1:1, plugins/workbench → packages/workbench, same file names).
- Identity preserved: extension id `ordessa.workbench`, manifest contribution points, WorkbenchToken construction stays in `@ordessa/workbench/api` (T006). plugins/workbench deleted, no alias left. Root package.json workspaces += packages/workbench (T006 had added it for api-only; now also carries the extension). tooling/build-all.mjs: discovery roots += `packages/workbench`, and scan() now indexes the scan root itself (comment explains why) — admission is still by products/desktop/extensions.json, lock rewritten by the tool (workbench entry.js digest changes; `git diff products/desktop/extensions.lock.json` shows only that entry). apps/desktop foundation.test.tsx imports repointed to packages/workbench/src; tsconfig include += packages/workbench/src.
- Inherited-red fix (see T003 correction): shell 7ff4ae99d2 intended "a single view renders bare" but left the view unopenable/unrendered when nothing selected it — the product never exercised this (module activation selects), extension examples did, so the three Electron script gates were red on main. Fix in packages/workbench/src/shell.tsx: `activeOf()` renders a one-view region's view by default UNLESS a module claims it as home/sidebar (preserves the registered counterexample "a sidebar-less activation must not inherit another module's sidebar"); the same helper now drives ViewSurface mounting. Test-only observation hook: region `<section>` carries `data-active-view` for one-view regions, and apps/desktop/electron/main.ts smoke probe adds those titles to `pages` and captures the unselected main-region content into `views` (one increment click, same as the tab loop). No assertion in any script was deleted or weakened.
- Main-session verification (true exit codes, logs /tmp/t17-*.log, all after `npm run build:examples && npm run build:foundations && npm run build`): packages/workbench `test` → vitest 27/27 + node --test token guard 2/2, exit 0; apps/desktop vitest 146/146 (13 files), exit 0; `npm run typecheck` 0; `npm run test:electron` 0; `npm run test:agent-ui` 0; `npm run test:extensions` 0 (all nine loader cases incl. host build digest unchanged); `npm run test:agent-shell` 0 (both no-handoff and loopback fake-server passes, hello called exactly twice); `npm run test:ui-preview` 0 (regenerated PNGs restored again, same registered churn note).
- Scratch cleanup: baseline triage worktree /tmp/c-t003-truth removed via `git worktree remove`; stash 'C-T017-wip-lane-only-worktree' popped and dropped.

## T020 + C6/T026 + C6/T027 — Workbench verification gaps, Connections tests-first and platform (eb52ece569, this commit)

Delegated to single-package subagents (no git, no co-written files); main session reviewed each diff, applied its own fixes, and re-ran every gate personally with true exit codes.

### T026 (commit 61ef0d66b2) — tests-first, honestly red
- `packages/desktop-platform/connections/{package.json,vitest.config.ts,api/connections.ts,src/index.ts,tests/connections.test.ts}` created by the package subagent; `@ordessa/connections` (id `ordessa.connections`) registered in the root lock (`npm install --package-lock-only`, +10 lines).
- Frozen shapes of the pre-existing Agent connection tests and their close/release call chain: `reports/C-baseline/connections-freeze.md` (12 IDs verbatim, per-step chain, CN-07 may/may-not list, mapping to the new platform tests).
- Main-session re-run: `npx vitest run --maxWorkers=1 --root packages/desktop-platform/connections` → 14 failed / 14, single distinct error `Connections platform not implemented (T027)` (no vacuous pass, no skip), `npm run typecheck` 0.
- Contract-ambiguity rulings accepted from the subagent and recorded here: `whenSettled()` is service-level (scope objects are plain `ResourceScope`); `open` gained `options.signal` because §2 requires cancelling a not-yet-finished open; a successfully closed instance leaves the platform snapshot while a `close_failed` record stays (§5.6).

### T027 (this commit) — platform implementation + built-in extension enabled
- `src/index.ts` implements §3/§5: gate-before-open, `===` kind identity, platform-owned abort signal, late/aborted resolve closed exactly once and never surfaced, no pooling, coalescing close, honest `close_failed` with explicit-only retry, cumulative settlement report. Package tests 17/17 (14 CN + 3 added).
- Two main-session review fixes over the subagent's version, each with a new test in `tests/lifecycle-details.test.ts` (assertions only added, none relaxed):
  1. §5.5 read literally — every failed local release is recorded in `whenSettled().closeFailures`, including one an explicit `handle.close()` reported to its awaiter; the subagent had scoped the report to dispose-started cleanups only.
  2. §5.2/§5.3 — the platform-owned connector signal is now aborted when a caller scope closes or a registrant unmounts after the open had landed, matching the `Connector.open` doc comment; previously only the not-yet-landed path aborted.
- Built-in extension: `extension/entry.ts` (`autoStart: true`, `provides: ConnectionsToken`, activate → `createConnections(context.resources)`; kept outside `src/` so the CN-01 import wall over api+src stays literal), `manifest.json` `{"id":"ordessa.connections","version":"0.1.0","hostApi":"2","entry":"entry.js"}`, `build.mjs`, and `tooling/build-all.mjs` discovery roots += `packages/desktop-platform/connections`.
- Token single instance: the shared copy rides the contracts foundation carrier (`foundation/src/contract.ts` re-exports `connections/api/connections`), the same mechanism `ordessa.workbench.v1` uses — deliberately not a private per-bundle copy. Product admits it: `products/desktop/extensions.json` 9 → 10 (`ordessa.connections` before `ordessa.agent-connections`), lock regenerated by the tool (4 lines: new enabled id + carrier digest).
- Real-build evidence (main session, `/tmp/g-*` and `/tmp/h-*` logs): `build:foundations` → "Built 10 enabled extensions"; `grep -r ordessa.connections.v1 products/desktop/dist/extensions` → exactly 1 hit, in `ordessa.contracts/contract.js`; `ordessa.connections/entry.js` imports it through `@extensions/ordessa.contracts/contract.js` (unbundled).
- Gates after enabling, all exit 0: `typecheck`; `node --test products/desktop/tests/` 2/2; `test:electron` (empty-host probe `ready:true, errors:[], emptyHost:true, nodeAbsent:true`); `test:extensions`; `test:agent-ui`; `test:agent-shell`; apps/desktop vitest 146/146 (13 files); packages/workbench 34 vitest + 3 node --test; connections 17/17. `test:ui-preview` not re-run in this batch (no product UI surface changed; registered as exit-code-only from T003/T017).

### T020 (commit eb52ece569) — verification gaps closed
- Token guard made watch-list driven over all four product token literals with per-token owner bundle, a source↔watchlist drift test, and a per-token rogue-bundle counterexample; mutation probe (drop one watch entry) went red and was restored. `ordessa.connections.v1` is intentionally NOT yet in the watchlist — its source lives outside `TOKEN_SOURCE_DISCOVERY_ROOTS`, so the drift test cannot see it; T029 must add one watchlist entry (+ a roots entry) and prove the guard catches a duplicate `ordessa.connections` Token. Registered as remaining work, not a pass.
- New suites: `empty-workbench.test.tsx` (3), `contributor-unload.test.tsx` (host-runtime unload + late-contribution rejection), `single-view-fallback.test.tsx`, and the product-admission guard `products/desktop/tests/product-bundles.test.mjs` (runs a fresh real build so it cannot pass against a stale dist).
- Main-session design ruling on the subagent's `KNOWN-SRC-GAP` report: `model.close(id)` only drops the selection pointing at a view and never unregisters a contributor's view, so for a single unclaimed view × is a deliberate no-op — dismissing it would leave a region with no tab strip and no nav entry that nothing can reopen. The comment in `single-view-fallback.test.tsx` now records it as a design ruling (assertions unchanged); it is not a src defect and no behaviour was weakened to make a test pass.

## C6/T028 (this commit) — Agent connections facade relocated to plugins/agent/connections
- Move: `plugins/connections/service/**` deleted (no reverse re-export, no alias), `plugins/agent/connections/**` added with the extension id unchanged (`ordessa.agent-connections`, `requires: [WorkbenchToken, ConnectionsToken]`, `provides: AgentConnectionsToken`). The generic half now comes from the platform: `asPlatformConnector()` adapts the frozen `AgentConnector.connect()` shape to `Connector<AgentClient>` whose `closeLocal` performs `client.dispose()`, `connect()` takes a platform `ConnectionHandle` and `release()` closes through it (`entry.tsx:32,72,86`).
- Agent-domain semantics kept intact: `src/status.tsx` is byte-identical to the old file; `src/workspace.ts` differs in exactly three semantic points — the registry facade gained `release`, `lifetime.add(client)` was removed so the platform handle is the ONE close owner (contract §4), and eviction awaits `connections.release(id)` instead of `evicted?.dispose()` — everything else is rationale comment. Managed-release lifecycle (seed → subscribe → `releasesSettled` → explicit retry) stayed Agent-side.
- `packages/desktop-platform/contracts/connections/src/connections.ts`: only addition is `AgentClientConnectionKind = createConnectionKind<AgentClient>('ordessa.agent-client')` built through the shared carrier factory, so the kind identity and the `ConnectionsToken` exist exactly once at runtime.
- Consumers repointed: 7 `apps/desktop/renderer/*.test.*` files and the 2 `tests/acp-connector/ui/*.test.tsx` files; 22 call sites now pass `createConnections(scope)` as the second argument of `createAgentConnections`. `git diff -U0` over the moved tests shows **0 removed `expect(` lines** — relocation changed paths and constructor args only.
- Product/assembly: `products/desktop/extensions.lock.json` regenerated by `tooling/build-all.mjs` (agent-connections bundle digest + carrier digest); `apps/desktop/scripts/test-ui-preview.mjs` fixture `enabled` list += `ordessa.connections` (the UI-preview fixture carries its own list, so enabling a built-in extension must be registered there too). `package-lock.json` refreshed by `npm install` to repoint `@ordessa/plugin-agent-connections` to the new path; npm left one `"plugins/connections/service": { "extraneous": true }` record in the lock — registered, not hand-edited.
- ACP rig red diagnosed rather than assumed: after the relocation `tests/acp-connector` went 7-failed/72-passed, every failure `TARGET_MISSING: … Unknown file extension ".ts" for packages/workbench/…`. Root cause is a chain introduced by this task (`acp/src/entry.ts` → agent-contracts carrier → `contracts/connections/src/connections.ts` → `@extensions/ordessa.contracts/contract.js` → foundation → `../../../../workbench/api/workbench`), which the rig's native-loader `TS_DIRS` never covered because nothing reached the Workbench public API before. Fix is rig plumbing only — `TS_DIRS` += `packages/workbench/api/` — the seam still executes the production module against the production contracts; no skip, xfail or fixture-only substitution. First attempt at a HEAD baseline used `git archive` + a symlinked `node_modules` and was discarded as invalid evidence (workspace symlinks resolve back into the live tree, so the "baseline" was not HEAD).
- Main-session verification, true exit codes, logs `/tmp/{batt,gate,cn07,mutant2}-*.log`, all after `npm run typecheck` (0) / `build:examples` (0) / `build:foundations` (0 → "Built 10 enabled extensions"): `npx vitest run --root tests/acp-connector` → 79/79 (9 files) exit 0; `test:extensions` 0; `test:agent-ui` 0; `test:agent-shell` 0; `test:ui-preview` 0 (`consoleErrors: []`, PNGs regenerated — registered churn); `test:electron` 0 (`emptyHost:true, errors:[]`); apps/desktop 146/146 (13 files); packages/workbench 34/34; connections 17/17.
- CN-07 (frozen tests not weakened): all 12 IDs from `reports/C-baseline/connections-freeze.md` still exist and pass verbatim (`--reporter=verbose agent-connections` → 12 passed, exit 0). Independent mutation probe by the main session: `closeLocal` in `entry.tsx:32` made a no-op → 5 failed / 7 passed, exit 1, and the failures are exactly frozen IDs 5–8 and 12 (the release/settlement ones), proving the Agent facade really routes local release through the platform handle; the file was restored from a `/tmp` copy and the full desktop suite re-confirmed 146/146 exit 0. (The relocation subagent reported 7 red for the same mutation; it had run the whole desktop suite, this probe was scoped to the two connections files — 5 is the number for that scope.)

## C6/T029 (this commit) — CN-08 real-build guards, the CN-01 coupling gate, and the variant-build seam

Guard work was delegated to a single-package subagent (no git, no shared files); the main
session reviewed it, **replaced its core seam**, added the missing CN-01 gate, and re-ran
every number below personally.

- **Review fix — the variant-build seam moved off `build-all.mjs`.** The delivery mirrored
  `buildExtension()` inside `tooling/build-all.mjs` and `eval`-ed each package's `build.mjs`
  options literal, because `tooling/build-extension.mjs` pinned `outputRoot` as a module
  constant. That is a drift hazard (two bundlers for one product). Fix: `outputRoot` is now
  `ORDESSA_PRODUCT_OUTPUT_ROOT`-overridable at the single writer of extension artifacts
  (`tooling/build-extension.mjs:5`), so variant mode executes each package's **real**
  `build.mjs` as a child with the env inherited; the mirror, the `eval` and the esbuild
  import in `build-all.mjs` are gone. `ORDESSA_PRODUCT_MANIFEST` stays as the enabled-list
  override, and the lock write stays real-mode only.
- **Review fix — one lock for all three real-build guards.** The new
  `tooling/real-build-lock.mjs` (cross-process mkdir mutex keyed by repo root) was only held
  by the two `products/desktop` guards; `packages/workbench/tests/token-single-instance.test.mjs`
  rebuilt the shared dist unlocked, so a parallel run of the two directories could scan a
  half-written tree. The helper moved out of `products/desktop/tests/support/` into `tooling/`
  and all three guards now acquire it for their build+scan lifetime.
- **CN-08 first clause (Token/kind single instance in the real build)** —
  `packages/workbench/tests/token-single-instance.test.mjs` **7/7, exit 0**: 5 watched tokens
  (incl. the newly admitted `ordessa.connections.v1`, owner `ordessa.contracts`) and the newly
  watched kind `ordessa.agent-client` (owner `ordessa.agent-contracts`) each construct exactly
  once in the real `products/desktop/dist`, inside their owner bundle; source↔watchlist sync is
  presence-checked before set-equality so a regressed scanner cannot pass vacuously; per-literal
  rogue direct-source imports bundle a second copy and are reported as 2 across 2 bundles with
  the owner check still seeing exactly 1; kind identity semantics are executed against the
  **real built carriers** (`createConnectionKind('x') !== createConnectionKind('x')`, while the
  same built module hands out one shared instance) — which is why a duplicated kind is a
  functional break (`Connections.open` matches kinds by `===`), not cosmetics.
- **CN-08 second clause (implemented-but-not-enabled API still importable)** —
  `products/desktop/tests/connections-platform-isolation.test.mjs` **6/6, exit 0**: a real
  `build-all` run of the enabled list minus `ordessa.connections` exits 0 (admission,
  `@extensions/*` dependency and built-set-equals-enabled checks all still pass), produces no
  `ordessa.connections/` directory, and its `ordessa.contracts/contract.js` — imported in Node
  through a host-loader-shaped shim — still exports a usable Connections API
  (`ConnectionsToken.name === 'ordessa.connections.v1'`, frozen working per-construction kind
  factory); all 5 tokens + 1 kind remain exactly-once in their owners in that variant; the real
  `dist` + `extensions.lock.json` are byte-identical around every variant run
  (lock md5 `0af774cc80ea1d24aee97fed1412c18d` before and after).
- **New: CN-01's structural half had no gate.** The contract row reads "无 Agent/Workbench 的
  非 Agent connector 完整生命周期 | 导入 Agent 或必须启用 Workbench 时门禁红"; T026 covered the
  first clause, nothing covered the second. Added both sides:
  `packages/desktop-platform/connections/tests/platform-isolation.test.ts` (3 tests — relative
  imports may not escape the package, bare specifiers are limited to the host extension API, the
  package's own api subpath and the `ordessa.contracts` carrier, and no Agent/Workbench
  token/kind literal may appear in platform sources), plus "the built platform bundle reaches no
  business extension" in the product guard (derived from the product manifest, presence-checked
  so the business list cannot rot). Writing it found my own allow-list wrong first: the guard
  went red on `entry.ts`'s carrier import (a multi-line `import … from` my grep had missed),
  which is the sanctioned channel — the allow-list was widened deliberately, not to silence the
  test but because the carrier is the C6 ruling.
- **Mutation probes run by the main session (3, all red, all restored and re-verified):**
  (1) second `createConnectionKind<AgentClient>('ordessa.agent-client')` in
  `contracts/connections/src/connections.ts` → workbench guard exit 1, `not ok 4` "kind
  'ordessa.agent-client' must be constructed by exactly one source site, found 2", `not ok 5`
  "must be constructed exactly once, found 2", `not ok 6` (counterexample) — 4 pass / 3 fail;
  (2) carrier `export * from '../../../connections/api/connections'` removed from
  `contracts/foundation/src/contract.ts` → product guard exit 1, `not ok 1` fails at
  `carrier.ConnectionsToken` ("Cannot read properties of undefined (reading 'name')") — the
  not-enabled-importable claim is really being executed; (3) business carrier import + relative
  escape appended to `packages/desktop-platform/connections/src/index.ts` → connections suite
  exit 1 with both violation classes named. All three files restored from `/tmp` copies and
  verified byte-identical (`git diff --stat` empty), then the product rebuilt.
- **CN-01–CN-08 re-run mapping** (every row re-executed in this commit, true exit codes):

  | CN | Evidence re-run here | Result |
  | --- | --- | --- |
  | CN-01 | `connections.test.ts` CN-01 lifecycle + `platform-isolation.test.ts` (3) + product guard "built platform bundle reaches no business extension" | green, probe (3) red |
  | CN-02 | `connections.test.ts` CN-02 rejection gates (4) | green |
  | CN-03 | CN-03 late resolve (2) | green |
  | CN-04 | CN-04 instance independence (1) | green |
  | CN-05 | CN-05 close semantics (2) | green |
  | CN-06 | CN-06 transport ownership (1) | green |
  | CN-07 | 12 frozen IDs (`agent-connections.test.ts` 11 + `agent-connections-status.test.tsx` 1) inside apps/desktop 146/146; T028 `closeLocal` mutation receipt | green, unchanged |
  | CN-08 | workbench guard 7/7 + product guard 6/6 + connections suite 20/20 | green, probes (1)(2) red |
- **Full battery after the fixes, true exit codes**: `typecheck` 0 · `build:examples` 0 ·
  `build:foundations` 0 ("Built 10 enabled extensions") · `build` 0 · `node --test
  packages/workbench/tests/` 0 (7/7) · `node --test products/desktop/tests/` 0 (6/6) ·
  connections vitest 0 (20/20, 3 files) · workbench vitest 0 (34/34) · apps/desktop 0 (146/146,
  13 files) · `tests/acp-connector` 0 (79/79, 9 files) · `test:electron` / `test:extensions` /
  `test:agent-ui` / `test:agent-shell` / `test:ui-preview` all 0. The root aggregate
  (`tooling/test-all.mjs`, T021 — built during this verification pass but committed with T021, the next
  commit) then ran all 15 suites in one pass: **15/15 green, exit 0**.
- **Registered, not hidden**: `test:ui-preview` screenshots proved non-byte-stable across two
  runs of identical code (three PNGs changed; one run captured `02-history.png` mid
  connector-switch) while the gate's DOM assertions passed both times — recorded in
  `docs/known-issues.md` §Desktop as preview-driver capture timing, with the assertions named as
  the authority. The committed PNGs are from the run whose content matches HEAD's.

## T021 (this commit) — the root JS test entry really aggregates the repo

**What was actually wrong before**: root `package.json` had `"test": "npm run --workspace apps/desktop
test"`. So `docs/baseline.md`'s documented entry point ran one package's 146 tests and nothing else —
the Workbench guards, the connections platform suite, native-bridge, the product real-build guard, the
ACP rig and all five temporary-Electron gates were reachable only by memorising commands, and a suite
that nobody re-ran by hand could rot silently. That is exactly the "假绿" shape FR-012 warns about, so
the fix had to be an entry point that cannot drop a suite quietly.

**Composition (`tooling/test-all.mjs`, 15 suites, serial)** — `npm test -- --list` prints it verbatim:

| Group | Suites |
| --- | --- |
| Prerequisites (real builds first; Electron gates read built output) | `typecheck`, `build:examples`, `build:foundations`, `build:app` |
| Discovered npm workspaces with their own `test` script | `apps/desktop`, `packages/desktop-platform/connections`, `packages/desktop-platform/native-bridge`, `packages/workbench` |
| Non-workspace roots (presence-checked) | `node-test:products/desktop`, `rig:tests/acp-connector` |
| Temporary Electron gates | `test:electron`, `test:extensions`, `test:agent-ui`, `test:agent-shell`, `test:ui-preview` |

**Why it cannot pass vacuously** (each of these is a throw, not a skip):

- Workspace suites are **discovered** from the root `workspaces` glob patterns (negation honoured), so a
  new package that declares `test` is aggregated without editing this file; a floor of
  `workspaces.length >= 4` throws because an empty discovery would otherwise be a free pass.
- The two non-workspace roots are probed on disk first; a moved suite must be re-declared, not dropped.
- A name filter that matches nothing throws (`no suite matches filter …  — nothing was verified`)
  instead of exiting 0 over an empty suite list.
- Every suite runs even after a failure and keeps its own exit code; the summary prints
  `PASS/FAIL exit=<n> <secs> <name>`, then `n/m suites green`, then the failed names, and only then
  `process.exitCode = 1`.

**Failure-collection proof (injection, then removed)**: two deliberately failing tests were written into
`workspace:packages/desktop-platform/connections` and `workspace:packages/desktop-platform/native-bridge`.
The run continued past both and reported `13/15 suites green` +
`Failed: workspace:packages/desktop-platform/connections (exit 1),
workspace:packages/desktop-platform/native-bridge (exit 1)` with `PROBE_EXIT=1` — the suites that sort
after the failures still executed. The probe files were deleted and the aggregate re-run clean.

**A real bug the aggregate surfaced** (not a hypothetical): running `node --test products/desktop/tests/`
as part of the same sequence exposed an `ENOENT` race in `tooling/real-build-lock.mjs` — the lock holder
can `rm` the directory between our failed `mkdir` and the follow-up `stat` used for stale detection, so
the waiter died with `A resource … generated asynchronous activity after the test ended … stat
'/tmp/ordessa-real-build-….lock'`. `stat` now tolerates `ENOENT` and simply retries. The lock itself was
relocated from `products/desktop/tests/support/` into `tooling/` in the T029 commit so the Workbench guard
and the product guard share one mutex around the shared real product output.

**Final run for this commit, true exit codes** (`AGGREGATE_EXIT=0`, 15/15 green, ~85 s wall):

```
PASS exit=0     3.9s  typecheck                PASS exit=0     9.4s  node-test:products/desktop
PASS exit=0     0.6s  build:examples           PASS exit=0    12.8s  rig:tests/acp-connector
PASS exit=0     2.9s  build:foundations        PASS exit=0     1.4s  electron:test:electron
PASS exit=0     3.2s  build:app                PASS exit=0     6.6s  electron:test:extensions
PASS exit=0    13.9s  workspace:apps/desktop   PASS exit=0     2.9s  electron:test:agent-ui
PASS exit=0     1.8s  workspace:…:connections  PASS exit=0     2.5s  electron:test:agent-shell
PASS exit=0     1.2s  workspace:…native-bridge PASS exit=0    10.1s  electron:test:ui-preview
PASS exit=0    11.6s  workspace:packages/workbench
```

**Boundary kept honest**: the aggregate starts no real Server, no real model and touches no run data —
the gates drive fake/loopback peers and fixture connectors, and it covers the JS side only (Python
server/harness suites stay B's). FR-012 is served by making the counterexample-bearing suites part of one
enforced entry point; FR-014 by including the suites that own the unmount / close-settlement / stop
checks (`packages/workbench`, `packages/desktop-platform/connections/tests/lifecycle-details.test.ts`,
`test:agent-shell`) rather than by re-asserting those semantics here.

**Docs touched so the entry point matches reality**: `docs/baseline.md` now documents `npm test` as the
15-suite root JS aggregate with `npm test -- --list`, and corrects `npm run build` from "9 extensions" to
"10 enabled extensions + electron app" (drift from enabling `ordessa.connections` in T027/T028); the stale
"not part of root npm test" comment in
`packages/desktop-platform/native-bridge/vitest.config.ts` now points at the aggregator.

## T018 (commit `e6e3eb195f` + this commit) — contract ownership: the domain carrier left the platform umbrella

**The violation, stated plainly**: `packages/desktop-platform/contracts/` — the platform umbrella —
hosted the Agent-domain declarations (`agent/src/agent.ts`, the Agent connection facade
`connections/src/connections.ts` and the `ordessa.agent-contracts` carrier `agent-ui/`), so the
platform owned business types (FR-009) and every domain consumer's public contract was reachable
through a platform path.

**The move** (`e6e3eb195f`): the whole carrier became the workspace package **`plugins/agent/contracts`**
(package name `@ordessa/agent-contracts`, extension id `ordessa.agent-contracts`, manifest byte-identical),
`src/{agent.ts,connections.ts,contract.ts,entry.ts}`. Verified after the fact: `src/agent.ts` and
`src/entry.ts` moved byte-for-byte; `connections.ts`, `contract.ts` and `build.mjs` differ only in the
path strings the move requires; nothing else changed. The umbrella now holds exactly `commands/` +
`foundation/`.

**Blast radius (the whole point of doing it in one commit)**: consumers import the shared channel
`@extensions/<id>/contract.js`, not a path, so 26 consumer files needed no edit. Only the mapping sites
moved — `tooling/vitest-extensions.mjs` (the single alias map), `apps/desktop/tsconfig.json` paths, the
ACP rig's `TS_DIRS` transpile whitelist (without it the rig dies on `Unknown file extension ".ts"`), the
CN-08 `TOKEN_/KIND_SOURCE_DISCOVERY_ROOTS` in `packages/workbench/tests/token-scan.mjs`, and 8 type/value
import specifiers in tests. Proven non-destructive: `git diff -U0` over those test files shows **only**
import lines and **zero** removed `expect(`/`it(`/`test(` lines. `docs/architecture.md` and
`apps/desktop/AGENTS.md` now state the ownership rule (and the architecture map caught up with T017/C6
while at it). The product lock re-digests the two carrier artifacts because esbuild embeds the source
path as a `// <path>` banner — a build-output fact, not a behavior change.

**Guards added (`products/desktop/tests/contract-ownership.test.mjs`, 5 tests, this commit)** — the wall
cannot silently fall back:
1. **Platform purity (source)**: no Agent/Chat domain declaration from a **frozen 26-name list**
   (extracted from the real carrier exports) may be declared anywhere under
   `packages/desktop-platform/**`, and no `ordessa.agent*` Token/kind literal may be constructed there;
   all breaches are reported at once via `deepEqual(violations, [])`.
2. **No reverse re-export (source)**: no platform source may reference a `plugins/**` path, the
   `@extensions/ordessa.agent*` channel, or a relative specifier that resolves outside the platform root
   — except the documented C4 workbench-api channel the foundation carrier exists to re-export.
   Load-time floor: fewer than 15 scanned platform sources throws instead of passing vacuously.
3. **Ownership + persistent identity**: carrier lives at `plugins/agent/contracts`, no
   `agent`/`connections`/`agent-ui` stub may reappear, umbrella dirs `deepEqual ['commands','foundation']`,
   id/name/`ordessa.id` still the persistent ones.
4. **Real build, right owner**: reusing CN-08's watchlists, each domain token/kind is constructed exactly
   once and inside `ordessa.agent-contracts/`, while the built `ordessa.contracts` platform carrier
   constructs **zero** domain literals.
5. **FR-009's last clause, domain side**: with the three Agent *implementations* removed from the enabled
   list the build still exits 0, their directories are absent, and the built domain carrier still imports
   as a usable API (token names, frozen kind with `displayName`, `hasOpenRun`/`hasAwaitingInteraction`
   behavior probed) — and both variant builds leave the real `products/desktop/dist` +
   `extensions.lock.json` byte-identical (digest before/after).

**Mutation probes run by the main session (3, each red with the expected message, all restored and
md5-verified)**:
`export interface AgentSnapshot {…}` in `contracts/commands/src/commands.ts` → guard test 1 exit 1,
`commands.ts:11 declares domain name 'AgentSnapshot'`; `export * from
'@extensions/ordessa.agent-contracts/contract.js'` there → test 2 exit 1 with the reverse-re-export
message naming the file; `new Token<{p:1}>('ordessa.agent.probe.v1')` there → test 1 exit 1 via the
`ordessa.agent*` literal clause (a domain literal under a *different* binding name is still caught).
After restoring the sources the product was rebuilt and the lock verified unchanged. (The FR-010 wall
probe belongs to T019 and is recorded there.)

**Honest gaps of these guards**: non-exported or aliased domain declarations are invisible to the name
scan (only `export …` declarations and `ordessa.agent*` literals are matched); `test`/`tests` directories
are excluded from the purity scan so a wall test may name what it forbids (which also means a
misbehaving platform *test* file is not scanned); a wall test placed at `…/src/index.test.ts` (the one
existing exception to the `tests/` convention, in native-bridge) IS scanned and is currently clean.
`package-lock.json` keeps `packages/desktop-platform/contracts/agent-ui` as an `"extraneous": true`
entry: `npm install --package-lock-only` and `npm prune --package-lock-only` both leave it, the same
pre-existing npm residue class as `plugins/connections/service` — the lock is tool-generated, so it was
not hand-edited.

## T019 (this commit) — 110 business test IDs out of the Electron shell, 36 host IDs stay

FR-010: business code and its unit tests must not live in the app shell. The T003 freeze recorded 146 IDs
over 13 files in `apps/desktop/renderer`; they now split **110 migrated / 36 staying** with the ID set
conserved exactly (36 + 110 = 146, re-frozen from the actual runs, not assumed).

| source (`apps/desktop/renderer/…`) | IDs | target (owning package) |
| --- | --- | --- |
| `agent-connections.test.ts` | 11 | `plugins/agent/connections/tests/` (facade moved there in T028) |
| `agent-connections-status.test.tsx` | 1 | `plugins/agent/connections/tests/` |
| `agent-conversation.test.tsx` | 18 | `plugins/agent/conversation/tests/` |
| `agent-sessions-draft.test.ts` | 16 | `plugins/agent/sessions/tests/` |
| `agent-sessions.test.ts` | 3 | `plugins/agent/sessions/tests/` |
| `agent-sessions.test.tsx` | 7 | `plugins/agent/sessions/tests/` |
| `agent-acp-wiring.test.ts` | 10 | `plugins/connectors/acp/tests/` |
| `agent-ordessa-connector.test.ts` | 18 | `plugins/connectors/ordessa/tests/` |
| `agent-ordessa.test.ts` | 23 | `plugins/connectors/ordessa/tests/` |
| `agent-ui-probe.test.tsx` | 3 | `products/desktop/ui-tests/` (see deviation note) |
| `foundation.test.tsx` (6), `host.test.tsx` (11), `loader.test.ts` (19) | 36 | stay: host contract/carrier, Lumino startup, loader confinement |

Per-ID map, verbatim in target file order:
### plugins/agent/connections/tests/agent-connections.test.ts (11)
1. lets independent adapters register and releases each with its own scope
2. gate predicates match run/interaction state only, across every connection
3. switching views over live work keeps the previous client, its run and its approvals alive
4. gates reconnect with the same authority as switching and restores it once live work clears
5. a release that fails after the reconnect completed reaches the subscriber and the snapshot on its own, and the explicit passes settle it
6. a cleanup pass started while the first release is in-flight joins that request and keeps the reference for the failure that follows
7. a release that failed before the eviction is seeded into the host view the moment the reference is taken over
8. a client whose first release confirms while another channel is still acquiring is forgotten only after that later release settles
9. evicting a client without the managed-release lifecycle retains nothing to confirm
10. re-evaluates the gate once a held handshake lands, so reconnect cannot cancel a run started during it
11. leaves the connecting indicator owned by the handshake that is still pending

### plugins/agent/connections/tests/agent-connections-status.test.tsx (1)
1. the status bar shows a late release failure automatically, with no selection or click after it lands

### plugins/agent/conversation/tests/agent-conversation.test.tsx (18)
1. keeps an unknown run outcome distinct from a failure (gate 1)
2. renders no model entry in the conversation while other options survive (gate 2)
3. hides thinking and effort alongside the model while a supported option survives (gate 3)
4. labels each tool outcome with the state the connector reported (gate 4)
5. opens a readable draft without touching the client, and blocks send until a project is valid (gate 5)
6. sends a draft once through createAndSend and clears only on snapshot confirmation (gate 6)
7. keeps the rejected text verbatim and resends only on an explicit second press (gate 7)
8. continues an existing session under its own project while the draft gate is closed (gate 8)
9. keeps Enter as send and Shift+Enter as a line break (gate 9)
10. keeps the composed text across a lost connection and a send attempted while disconnected (gate 10)
11. gives every session its own unsent text across switching and sends nothing on a switch (gate 11)
12. keeps the same session id on two connections apart and sends nothing on a connection switch (gate 12)
13. keeps a draft across a connection round trip, and empties it on discard and after a confirmed send (gate 13)
14. blocks a mid-draft invalidation whose stale selection the connector clears, without costing the text (gate 14)
15. mirrors an invalidation the connector does not report: the send is offered and the typed refusal keeps the text (gate 15)
16. gives the pane, the key and the session identity to a draft that overlaps a live selection (gate 16)
17. resumes a stepped-away draft and routes its first send to createAndSend, never the selected session (gate 17)
18. keeps both unsent buffers when opening the same session that was selected before the draft (gate 18)

### plugins/agent/sessions/tests/agent-sessions-draft.test.ts (16)
1. New session and Discard produce zero backend calls and never a temporary session (FC-0021)
2. first send is blocked without a valid project and reaches no client create (拦截反例)
3. restores the last valid project for the same Server instance and revalidates it on selection
4. an invalid restored project clears the selection and blocks sends until reselect
5. project records are isolated per Server instance, never shared across connections (跨连接不串)
6. an unknown first-send outcome keeps one requestId and never creates a second session id
7. continuing an existing session never consults the draft gate or a new create (续聊沿原项目)
8. the last valid project survives a simulated renderer restart and is revalidated before use (FC-0030)
9. a record never restores across Server identities, and storage loss forces manual selection (不串+缺storage)
10. a stored id no longer listed unarchived blocks sends without opening it, and nothing restores without identity
11. an accepted-but-unverifiable first send never lists a ghost session and keeps the same requestId for the retry (FC-0031)
12. draft first send reaches createAndSend exactly once and never the previously open session (C-0030 拦截反例)
13. discardDraft restores the previously selected session in place and reports endedBy discarded (恢复定义)
14. openSession during an active draft ends it as opened and sends nothing (可区分下游语义)
15. an unknown draft outcome with an old session selected keeps the requestId and never falls back to it (unknown 不降级)
16. switching connections with a live draft sends nothing on either side (切换零发送)

### plugins/agent/sessions/tests/agent-sessions.test.ts (3)
1. keeps separate clients alive on selection changes and disposes them with the connections service scope
2. projects sessions into ordered workspace groups with the standalone group last (P2-3 projection)
3. derives per-session badge state through the shared gate predicates over all items

### plugins/agent/sessions/tests/agent-sessions.test.tsx (7)
1. groups sessions by workspace with the standalone group last and pinned first (P2-3 grouping)
2. keeps the flat list shape while no session carries a workspace (single standalone group)
3. badges every session by scanning all its runs and interactions, not only the last run (FC-0015 predicates)
4. renders the five list states with their existing copy (empty is a count, not a null container)
5. keeps exactly one selection marker, moved by clicks and restored on a fresh mount (FC-0004 selection)
6. draft UI: New session opens the picker with zero backend calls, picking clears the block, Discard closes it (FC-0021)
7. registers view, command and navigation exactly once in the sessions entry and never in the conversation entry (FC-0004 unique registration)

### plugins/connectors/acp/tests/agent-acp-wiring.test.ts (10)
1. activates through bridge, transport and host: the native pair is offered once, and the reviewed loop runs over the real contract
2. a Server whose hello carries no native-execution identity activates as an honest not-offered and registers nothing
3. refuses bridge frames the transport does not know, and they never reach the wire
4. a refused open launches nothing: an unopened project answers NOT_FOUND and a foreign instance is refused locally
5. a relay death is never a release: it errors the stream, cancels nothing, and the stand-down stays explicit
6. a refused release reaches the host as a typed diagnostic and the explicit retry lands over the same still-open bridge
7. a release answered released:false over a successful RPC is never booked as success, and the retry confirms
8. the real workspace reconnect flow proves the host consumption: an evicted ACP client with a refused release stays visible and retryable through the workspace surface
9. privileged-input refusals register nothing: no origin, and a token file group-readable
10. closing the bridge instance tears every live relay down and nothing flows afterwards

### plugins/connectors/ordessa/tests/agent-ordessa-connector.test.ts (18)
1. proves the authenticated Server instance before one connector is registered
2. registers nothing and strips the IPC wrapper from the native refusal
3. refuses to reuse a frozen connection when the Server behind the URL changed
4. projects an approved first send only from a real session id
5. keeps an accepted session when the list read has not caught up yet
6. rejects a first send whose session the Server binds to another project
7. accepts a first send the Server binds to the same project by path
8. never reports a first send the Server did not confirm, and keeps the caller request id
9. keeps an unconfirmed first send out of the session list
10. answers a real approval through one approvals.decide call only
11. refuses an answer that is not an allow or deny without touching the wire
12. never presents an ordinary request as answerable, and keeps approvals answerable (FC-0041)
13. shows an approval it cannot record as unanswerable instead of a button
14. makes an open run and a pending approval unknown when the event channel drops
15. maps the wire run states without inventing a verdict the protocol never carries
16. keeps the project selection scoped to what the Server actually offers
17. clears the pick behind a first send the Server refused for a lost project, and only that one
18. opens a session from its log and refuses the operations this product has no route for

### plugins/connectors/ordessa/tests/agent-ordessa.test.ts (23)
1. resolves the two explicit host inputs into a same-origin target
2. refuses when either input is absent instead of guessing a default port
3. refuses anything that is not a bare loopback http origin with an explicit port
4. refuses an unusable token locator without echoing the secret or its path
5. scopes one instance identity per Server however its origin is spelled
6. accepts only the same data-root secrets token file, at 0600
7. refuses a locator that is not the Server secrets token file
8. refuses a symlink and any other non-regular file
9. refuses a token file that group, other or somebody else can see
10. refuses where ownership cannot be checked at all
11. refuses an unusable token body
12. never writes the token or its full locator into a token-file refusal
13. sends under the exact profileId the authenticated hello names
14. refuses a first send whose hello identity the Server does not confirm
15. stops a first send whose project is already gone, before any send frame exists
16. registers a picked local folder through the Server and requires it in the returned project list
17. keeps a typed send-period project loss deterministic instead of asking the Server what it accepted
18. leaves a settled send refusal exactly as the Server answered it
19. queries only a genuinely unsettled send, and settles it under the caller’s own request id
20. takes a real session from the outcome query when the accepted response was lost
21. never spends an outcome query on a first send the Server answered directly
22. does not call a lost conversation with the Server a lost project
23. keeps a server-authored reason out of both the code and the message

### products/desktop/ui-tests/agent-ui-probe.test.tsx (3)
1. renders external history, incremental snapshots and tool results through the real assistant-ui runtime
2. rejects stale generations, late terminal writes and writes after disposal
3. preserves complete, cancelled and error as distinct library statuses

**Mechanics (six single-package lanes, main-session verified)**: each lane received exactly one target
package and its own files, wrote nothing outside them, and ran no git. After the lanes reported, the main
session re-diffed every one of the 10 migrated files against its frozen `HEAD` renderer version:

- All 10 files: the changed lines are **only `import` / specifier lines** — 10, 8, 10, 8, 10, 16, 15, 7, 6,
  and 0 lines respectively (the `agent-ui-probe` suite moved byte-for-byte). Listed in full above; zero
  `expect(`/`it(`/`test(` lines removed or altered in any file. Rule 1 of the T019 plan holds per file,
  verified rather than asserted.
- The receiving plugin packages each got a minimal `vitest.config.ts` (jsdom where the suite needs a DOM)
  whose aliases come from the single shared helper — `contractAliases()` in `tooling/vitest-extensions.mjs`
  — so no sixth copy of the drifting alias list exists (plan rule 3), plus a `scripts.test` of the form
  `vitest run --maxWorkers=1`.
- **Deviation from the plan, deliberate**: the plan's target for `agent-ui-probe.test.tsx` was
  `products/desktop/tests/`. `products/desktop/tests/` is driven by `node --test`, and a `.tsx` suite
  there is both runner-mismatched and picked up by that glob, so the product-level UI suite lives in
  `products/desktop/ui-tests/` with its own vitest config (`include: ['ui-tests/**/*.test.tsx']`, comment
  in file states why). Still product-level integration, exactly the disposition the plan intended.
- **Type-only host reference retained (registered)**: `plugins/connectors/{acp,ordessa}/tests/…` import
  `type { AgentNativeBridge }` from `../../../../apps/desktop/renderer/agent-native`. That is the renderer
  IPC surface the connector transports are tested against; the move kept it rather than inventing a
  duplicate type. It is not an FR-009 breach (domain → host *type*, not the platform wall), but it does
  keep one app-shell file load-bearing for plugin tests. Follow-up candidate: relocate that interface into
  `packages/desktop-platform/native-bridge` with the rest of the bridge contract.

**Coverage was not lost with the paths**: `apps/desktop/tsconfig.json` `include` gained
`../../plugins/*/*/*/tests` and `../../products/desktop/ui-tests`, so the migrated suites typecheck
exactly as loudly as they did when they were renderer files. `npm run typecheck` (the aggregate's first
suite, `tsc --noEmit` over that tsconfig) exits 0 with those additions.

**FR-010 wall (`products/desktop/tests/host-shell-suites.test.mjs`)**: the app shell may hold only the
three host suites; the guard scans `apps/desktop/renderer` for `*.test.*` and `deepEqual`s the result
against the frozen `['foundation.test.tsx', 'host.test.tsx', 'loader.test.ts']`. Probe P4: dropping a
`probe-business.test.ts` into the renderer made it exit 1 with the FR-010 message naming the extra file;
removed again.

**Counts re-frozen from real runs, not from the plan**: `apps/desktop` is now 3 test files / **36 tests**
(runtime output, and the naive `it(`/`test(` count of `loader.test.ts` gives 14 vs the runtime 19 because
that suite generates cases in loops — the runtime number is the one recorded). The three staying files
plus 110 migrated IDs = 146, the T003 freeze conserved exactly. The runtime "Tests N passed" lines of the
six new suites sum to the migrated set without any bookkeeping: 12 (`agent/connections`: 11+1) + 18
(`conversation`) + 26 (`sessions`: 16+3+7) + 10 (`connectors/acp`) + 41 (`connectors/ordessa`: 18+23) +
3 (`ui-tests`) = **110**, each matching its per-ID table section above.

**Full green aggregate after T018+T019**: `npm test` → **21/21 suites exit 0** (`AGGREGATE_EXIT=0`):
typecheck 4.3s, `build:examples` 0.9s, `build:foundations` 2.7s, `build:app` 3.5s, `apps/desktop` 3.6s,
`packages/desktop-platform/connections` 2.2s, `native-bridge` 1.7s, `packages/workbench` 11.4s,
`plugins/agent/connections` 2.8s, `plugins/agent/conversation` 3.8s, `plugins/agent/sessions` 3.1s,
`plugins/connectors/acp` 1.7s, `plugins/connectors/ordessa` 1.8s, `products/desktop` (vitest UI suite) 2.9s,
`node --test products/desktop/tests` 15.5s (12 tests), the ACP rig 13.1s, and the five temporary-Electron
gates 1.9/6.7/2.7/2.7/9.9s.

**Known cosmetic residue**: the five new plugin vitest configs print Vite's "The CJS build of Vite's
config API is deprecated" warning because those packages, like the pre-existing
`packages/desktop-platform/connections`, have no `"type": "module"` in their `package.json`. Adding it was
deliberately not done here: it is a package-wide semantics change, out of T019's scope, and the existing
workspace already carries the same warning.

## T024(C) (this commit) — lane delivery report: gates run, ledger diffed, scope honestly bounded

Status for the C lane: **IMPLEMENTATION_REVIEW_READY**. This is the C share only — A/B lanes are not
assessed here, `T024` stays an unticked shared checkbox (see the consistency-check note at the top), and
`T025` (main-control review, fixed SHAs, integration tree) is the next owner. Nothing is pushed, nothing
merged, no user service touched, no real model called.

### Task coverage (every C task in `tasks.md`)

| task | state | commit(s) | receipt |
| --- | --- | --- | --- |
| T003 freeze | done | `d4943cb229` | §T003 + `reports/C-baseline/*.ids.txt` |
| T006 Workbench API ownership + Token counterexample | done | `a31e4387d7` | §T006 |
| T017 Workbench → platform package | done | `a08367ef59` | §T017 |
| T018 contract ownership (+ FR-009 wall guards) | done | `e6e3eb195f`, `434f3aa5aa` | §T018 |
| T019 business test migration out of the shell | done | `28eca02683` | §T019 (+ per-ID map there) |
| T020 Workbench/product verification | done | `eb52ece569` | §T020 |
| T021 real root aggregate | done | `74eab2411e` | §T021 |
| C6/T026–T029 Connections platform (tests-first → impl → facade move → real-build guards) | done | `61ef0d66b2`, `a967feb9db`, `ca549ddcb1`, `754adaab51` | §C6/T026–T029 |
| T024 shared report gate | C share done here | this commit | this section |

### The gates the objective names, each tied to a test that actually ran

| gate | evidence (test ID / command) | result |
| --- | --- | --- |
| real build | `npm run build` (exit 0) + `products/desktop/tests/product-bundles.test.mjs`: *every admitted product extension is really built with entry and manifest*, *each DI token owner bundle is an admitted contract carrier in the product build* | green |
| duplicate-Token counterexample | `packages/workbench/tests/token-single-instance.test.mjs`: the watchlist-vs-sources sync tests, the exactly-once scan over the **real** build, and *counterexample: a rogue direct-source import bundles a second construction and the guard goes red* for both tokens and kinds (parameterised per literal; the rogue bundle alone is first asserted to really carry a second construction, so the counterexample cannot pass vacuously) | green (and provably red when a copy is introduced) |
| empty Host | `apps/desktop/renderer/host.test.tsx`: *starts without business plugins or public raw registry* | green |
| empty Workbench | `packages/workbench/tests/empty-workbench.test.tsx` (3 IDs: empty state, no tab strips, all five region labels, disabled layout controls) + `composition.test.tsx`: *empty product mounts with an empty state, no module entries — and shows one as soon as a module registers* | green |
| contribution unload | `packages/workbench/tests/contributor-unload.test.tsx` + `composition.test.tsx`: *removing a module erases its navigation, sidebar and main view without breaking a peer*, *overlay owner unload closes the instance and restores focus*, *settings page … removed on contributor unload*; release-side: `packages/desktop-platform/connections/tests/{connections,lifecycle-details}.test.ts` (CN rows: late-write refusal, close failure keeps the handle, busy rejection) | green |
| temporary-Electron smoke | `test:electron`, `test:extensions`, `test:agent-ui`, `test:agent-shell`, `test:ui-preview` — all five in the aggregate, temp `userData`, no real Server connection | 5/5 green |

### Quickstart battery, run in order at the final tree state

Evidence: `/tmp/ordessa-C-evidence/T024-gates.log` (one log, `### EXIT=` line per command).

| command | exit |
| --- | --- |
| `npm ci` (root, isolated: wipes and rebuilds `node_modules` from the committed lock) | 0 — `T024-npm-ci.log`; afterwards every workspace link resolves (no dangling symlink), and `git status package-lock.json` is clean, i.e. the committed lock is install-idempotent |
| `npm ci` in `tests/acp-connector` (the rig's own install) | 0 — `T024-rig-npm-ci.log` |
| `npm run typecheck` | 0 |
| `npm test` (the 21-suite aggregate) | 0 — `21/21 suites green`, per-suite exit code + wall time recorded in the log |
| `npm run build` | 0 |
| `npm run test:electron` | 0 |
| `(cd tests/acp-connector && npx vitest run --maxWorkers=1)` | 0 (79 IDs) |

Aggregate suite list with timings (from the same log): typecheck 3.9s, `build:examples` 0.8s,
`build:foundations` 2.8s, `build:app` 3.3s, `apps/desktop` 4.4s, `desktop-platform/connections` 2.1s,
`native-bridge` 1.6s, `packages/workbench` 13.7s, `plugins/agent/connections` 2.7s, `conversation` 4.4s,
`sessions` 4.1s, `connectors/acp` 1.8s, `connectors/ordessa` 2.0s, `products/desktop` 3.1s,
`node --test products/desktop/tests` 14.7s, ACP rig 12.3s, and the five Electron gates
1.8/6.5/2.9/2.7/9.7s.

### Per-ID ledger gate (FR-012 "账本" row): `tooling/id-diff.mjs`

The T003 freeze was a snapshot of four vitest suites; the lane moved packages across three of them, so
"no test was lost" has to be *derived*, not remembered. `node tooling/id-diff.mjs` re-runs every ID-bearing
suite the root aggregate knows about (suite discovery comes from `test-all.mjs --list`, so the gate cannot
drift away from what `npm test` runs), flattens each ID to the same `P|file|fullName` form as the freeze,
and classifies every frozen ID as kept / moved / **missing**:

```
frozen IDs: 265   current IDs: 304
kept in place: 128   moved (same name, new file): 137   MISSING: 0
added since the freeze: 39
```

- **265/265 frozen IDs still run** — none lost. The 137 moves are exactly the two relocations this lane
  performed: 110 `apps/desktop/renderer/*` → owning package (T019) and 27
  `plugins/workbench/tests/*` → `packages/workbench/tests/*` (T017); every move is printed as
  `old file -> new file :: ID` in `/tmp/ordessa-C-evidence/T024-id-diff.log`.
- **39 added IDs, all attributed**: 20 from the Connections platform suites (T026/T027), 7 from the new
  Workbench verification suites (T020), 12 from the product guards (`connections-platform-isolation` ×4, `contract-ownership` ×5, `product-bundles` ×2, `host-shell-suites` ×1). Note this count treats the
  `node --test` product guards as "added" because the T003 freeze only covered vitest suites — a freeze
  gap, now closed by the post-lane ledger.
- The current full universe is written to `reports/C-baseline/post-lane/post-lane.ids.txt` (304 lines) so
  T025 pins against a regenerated artifact rather than any number quoted in prose.
- The gate itself is probed, not trusted: with a doctored freeze that claims one ID which no longer
  exists, it prints the `UNEXPLAINED LOSSES` section and exits 1
  (`/tmp/ordessa-C-evidence/T024-id-diff-probe.log`); every suite that yields zero IDs throws instead of
  passing thin.

### New features did not modify the core (FR-013 / constitution)

`git diff --name-only 42bf446370..HEAD` over the whole lane:

- `packages/desktop-platform/extension-api`, `extension-host`, `extension-loader`: **0 files touched** — the
  Lumino host, its loader and its public API were not rewritten, only consumed.
- `apps/server`, `packages/pacthold`, `plugins/harness`: **0 files touched** (frontend lane, backend frozen).
- Two host-adjacent files changed, both disclosed: `apps/desktop/electron/main.ts` +10/−0 — inside the
  *smoke probe's page-sampling snippet* only, so the single-view shell (T017) is observable by
  `test:electron`/`test:ui-preview`; no host behavior, IPC surface, or lifecycle code. And
  `packages/desktop-platform/native-bridge/vitest.config.ts` +4/−1 — test infra pointed at the aggregator.
- Everything else this lane added lives where the plan says: `packages/workbench`,
  `packages/desktop-platform/connections`, `plugins/*`, `products/desktop`, `tooling`, `specs`, `docs`.
- No new model/service/release permission, no other worktree's work merged in (single-author C commits on
  `codex/010-platform-frontend`, base `42bf446370`).

### Scope isolation is probed asymmetrically, not symmetrically

Every "this is per-scope / per-composition, not process state" claim in the lane rests on the asymmetric
case, because a symmetric pair of identical compositions passes on a process-global table too:
`packages/desktop-platform/connections/tests/connections.test.ts`:314 *two scopes open distinct instances
from one connector id; closing one leaves the other fully usable* (plus the coalesced-close and
late-write rows), and every Workbench test constructs its own `createWorkbench(lifetime)`. A structural
cross-check backs it: no module-level mutable `Map`/`Set`/array exists anywhere in
`packages/workbench/src`, `packages/desktop-platform/connections/src` or
`plugins/agent/connections/src` — the shared singletons in this design are only the contract-carrier
Tokens and kinds, which the CN-08 exactly-once build guards own.

### Re-run at the lane tip

The whole battery above was executed at `28eca02683` (last code commit) and the aggregate re-executed at
this report's commit with the same result: `21/21 suites green`, exit 0
(`/tmp/ordessa-C-evidence/T024-final-aggregate-tip.log`).

### Inherited reds and registered noise

- T003 recorded **0 baseline reds** for the C suites; the post-lane ledger shows **0 failing frozen IDs**,
  so no unexplained new failure appears (SC-005: unexplained new failure IDs = 0).
- `docs/ui-preview/*.png` are regenerated by `test:ui-preview` and churn pixel-wise between runs
  (observed 3 files this session). Registered in `docs/known-issues.md`; each time restored to `HEAD`
  rather than committed, so the visual debt is not silently re-baselined.
- `package-lock.json` carries `"extraneous": true` entries (`plugins/connections/service`,
  `packages/desktop-platform/contracts/agent-ui`) that `npm install --package-lock-only` and
  `npm prune --package-lock-only` both leave behind. Tool-generated lock: not hand-edited; the residue is
  cosmetic and `npm ci` from it succeeds (above).
- The five new plugin vitest configs print Vite's CJS-config deprecation warning (packages without
  `"type": "module"`, same class as the pre-existing `packages/desktop-platform/connections`). Cosmetic,
  deliberately not "fixed" by a package-wide semantics change.

### Not tested by this lane (scope boundary, not a pass claim)

- `tests/acp-connector/test-native-two-turn.mjs` and `test-native-paired-no-send.mjs`: require the **real
  private Server** and prior user authorisation (cost + credentials). Not run; the ACP seam is covered by
  the 79-ID rig against a controlled fake peer.
- End-to-end GUI acceptance beyond the five headless smokes: no human-in-the-loop visual acceptance, no
  keyboard-reader/axe pass, no real multi-window session. The two UI debts named in the spec's own
  known-issue list stay open.
- Windows/macOS paths, real Electron under a real display server, real provider credentials, real model
  calls, packaging/publishing, and the server-side wire compatibility matrix (A/B lanes).
- `products/desktop` is assembled and built, but this lane does not claim the product's *business* flows
  (agent chat UX) beyond the migrated suites and the probe extension.

### What T025 needs to know

- Lane SHAs are in the ledger below (base `42bf446370`, every commit C-only, unpushed).
- Re-run: `npm ci && npm test` at the pinned SHA (21 suites), then `node tooling/id-diff.mjs` and diff
  `post-lane/post-lane.ids.txt` against your integrated tree to catch integration-time losses.
- A/B integration will land Python-side changes; nothing in the C aggregate touches them, so an
  aggregate-only check is sufficient for the frontend, plus `npm run build` to confirm the product's
  extension set still resolves after the merge.

## C lane revision ledger (for T024(C) / T025 SHA pinning)

Lane base: `42bf446370` (docs: prepare Spec Kit platform convergence and parallel lanes). Every
commit below is C-lane only; nothing is merged to `main` and nothing is pushed from this tree.

| SHA | Task | Scope |
| --- | --- | --- |
| `d4943cb229` | T003 | baseline freeze: test IDs, build paths, inherited-red register |
| `a31e4387d7` | T006 | Workbench public API → `packages/workbench`, real-build Token guard |
| `649dfa5d66` | C6 amendment | plan/tasks amended for platform Connections (docs) |
| `e21d6e2390` | C6 receipt | revision receipt + connections owner-map correction |
| `a08367ef59` | T017 | Workbench extension → `packages/workbench`, shell one-view fix |
| `61ef0d66b2` | T026 | CN-01–CN-06 tests-first (honestly red) + frozen connection semantics |
| `eb52ece569` | T020 | Workbench/product verification suites, token watchlist generalisation |
| `a967feb9db` | T027 | Connections platform implementation + `ordessa.connections` built-in |
| `ca549ddcb1` | T028 | Agent connections facade → `plugins/agent/connections` |
| `ac1e8b7ac8` | T028 docs | receipt, lane SHA ledger, T018/T019 migration plans |
| `247cc5aed9` | pre-T018 | `@extensions` contract alias map single-sourced into `tooling/vitest-extensions.mjs` |
| `754adaab51` | T029 | CN-08 real-build token+kind guards, CN-01 coupling gate, variant-build seam on `build-extension.mjs` |
| `74eab2411e` | T021 | Root JS aggregate `tooling/test-all.mjs` (15 suites, real failure collection), real-build lock ENOENT fix, `docs/baseline.md` entry-point correction |
| `e6e3eb195f` | T018 move | Agent-domain contract carrier `packages/desktop-platform/contracts/{agent,connections,agent-ui}` → workspace package `plugins/agent/contracts` (`@ordessa/agent-contracts`, id unchanged) + every mapping site |
| `434f3aa5aa` | T018 guards | FR-009 ownership wall: `products/desktop/tests/contract-ownership.test.mjs` (5 tests: source purity vs a frozen 26-name list, no reverse re-export, persistent-identity/umbrella shape, real-build exactly-once-per-domain-literal with the platform carrier constructing none, implemented-but-not-enabled domain API), 3 mutation probes red-then-restored |
| `_(this commit)_` | T019 | FR-010 business-test migration: 110 IDs / 10 files out of `apps/desktop/renderer` into `plugins/agent/{connections,conversation,sessions}/tests`, `plugins/connectors/{acp,ordessa}/tests` and `products/desktop/ui-tests` (5 new vitest configs sharing `tooling/vitest-extensions.mjs` aliases, `apps/desktop/tsconfig.json` include widened), 36 host IDs stay behind the new `host-shell-suites.test.mjs` wall, aggregate re-frozen at 21/21 |
| `db3c5c2536` | T024(C) | Lane delivery report + gates: `tooling/id-diff.mjs` per-ID ledger gate (265 frozen IDs → 128 kept / 137 moved / 0 missing, 304 current, post-lane ledger committed under `reports/C-baseline/post-lane/`), isolated `npm ci` ×2, quickstart battery 5×exit 0 at the final tree, FR-013 core-untouched proof, untested scope; `Status: IMPLEMENTATION_REVIEW_READY` for C (shared T024 box deliberately left unticked) |
| `72c2f4e831` | T024 addendum | Scope-isolation probe basis (asymmetric two-scope case, zero module-level mutable registries) and the 21/21 aggregate re-run at the report commit |
| `_(this commit)_` | T024 ledger | This ledger's T024 rows resolved to real SHAs, plus `docs/acp-connector-test-review.md` annotating the pre-T018 contract path. Prose only — no source, config or test file moved after `db3c5c2536`, so every verification number above still describes this tree |
