# Q3 → C0 integration request (shared-surface handoffs)

Q3's write surface is only `plugins/assets/subagents/**` plus this feature
directory (`specs/011-plugin-rollout/plan.md` §"每线所有者"). Everything below is
a **handoff**, deliberately not done by this line.

## I-1 Product composition (C0 owns `products/**`)

Q3 ships a server-plugin descriptor inside its own package but does **not** edit
the product assembly. C0 inserts it into
`products/server/src/ordessa_server_product/composition.py:40-55
default_plugins()` (currently `(WorkspaceServerPlugin(), ServerCompatPlugin(...),
AcpChannelServerPlugin())`), following the reference shape of
`plugins/workspace/src/ordessa_workspace/plugin.py:48-206`.

- Package: `ordessa-assets-subagents` (path `plugins/assets/subagents`).
- Editable install line for the backend recipe in `docs/baseline.md`:
  `-e plugins/assets/subagents`.
- Requires-python `>=3.11` (uses stdlib `tomllib` in the Codex adapter
  self-validation). The rest of the backend floor is `>=3.9`; this line does not
  change a shared floor and asks C0 to record the per-package floor instead.
- Runtime dependencies: **stdlib only** (verified in the package `pyproject.toml`
  at review time). No new third-party requirement is added, so no root
  `package-lock.json` or `apps/server/lockfiles/*` change is needed from Q3.

## I-2 Root workspace glob check

Root `package.json` workspaces already include `plugins/**` with the
`!plugins/harness/**` exclusion. Q3 adds no JS package, so no glob or lock edit
is required; C0 should confirm during the lock regeneration that
`plugins/assets/**` presence does not alter the generated root lock.

**Correction + two concrete items, measured by the T11 writer and verified here:**
Q3 *did* add TypeScript faces (`plugins/assets/subagents/ui`,
`.../settings`), so this row is no longer "no JS package":

1. **A future root lock entry is expected.** Both dirs match the `plugins/**`
   workspace glob, so the next `npm install` legitimately records two workspace
   entries. Q3 ran `npm ci` and never modified the lock
   (`git status --porcelain -- package-lock.json package.json` → 0 lines). C0
   generates the final lock.
2. **`apps/desktop/tsconfig.json` needs a path mapping**
   `"@extensions/ordessa.chat-api/contract.js": ["../../plugins/chat/api/src/contract.ts"]`
   before the desktop-wide typecheck can resolve Q3's imports. Today both packages
   self-resolve through their own `tsconfig.json` + vitest `alias` (exactly how
   `plugins/chat/api` does it — `node_modules/@extensions` does not exist), so
   `npx tsc --noEmit` in each package is green. The root run currently reports
   *only* grammar errors from an in-flight file, which suppresses semantic
   diagnostics; once that clears, a TS2307 could surface for Q3's `ui` face. This
   is C0's/Z2's file, not Q3's, so it is requested rather than made.
   Same need will apply to `@ordessa/*` contracts if the settings face imports them.
3. Q3 deliberately ships **no `manifest.json`** for the `ui` face:
   `tooling/build-all.mjs` treats any `plugins/**` dir containing a
   `manifest.json` as a loadable extension, and there is no live server-side
   reader yet (no `foundation`). Publishing one would advertise an assembly that
   does not exist. Product registration is T13/I-1 work for C0.

## I-3 `docs/known-issues.md` registrations this line needs recorded

Q3 must not edit the shared known-issues page (public docs are read-only for
business lines), so C0 registers:

1. **Environment-incomplete `apps/server` collection in this tree.** Measured
   before-state `90 failed, 670 passed, 10 skipped, 158 errors` (exit 1) with
   `ARTIFACT_worker-*`, `ARTIFACT_sidecar-entry`,
   `ARTIFACT_acp-npm-closure`, `TOOL_claude` all `ABSENT`. This differs in shape
   from `docs/baseline.md`'s migrated ledger (`783P/43F/10S/25E`) purely because
   the npm closure and the built Go bridge are absent. Per-ID list:
   `/home/maoqh/ordessa-evidence/q3/before-server.ids` (仓外, 258 entries).
2. **Pi `attach` capability** is declared but unobserved
   (`plugins/harness/src/ordessa_harness/harnesses.toml:376-388`) — Q3 treats Pi as
   `unsupported` for subagents and relies on this existing registration.
3. **`claude` CLI absent on this host**, so no Claude L2-exec/L3 evidence is
   obtainable here; the Claude row of G22–G24 stays open.
4. The two inherited `plugins/harness` npm-closure reds are unchanged by Q3
   (same IDs, same cause) — already registered at `docs/known-issues.md:13`.

## I-4 Public/compat deletions Q3 deliberately did NOT make

Per the rollout plan, shared `server-compat` deletions belong to C0. Q3 leaves
these intact and asserts they must **stay** as-is (they are the old authorization
edge, FR12 / T13 "保持旧授权边归属"):

| Old surface | Owner today | Q3 stance |
| --- | --- | --- |
| `server_subagent_grants` table + `_migrate_16_to_17` | pacthold storage / server-compat | keep; never repurposed as a definition store |
| `profiles.subagentGrants / grantSubagent / revokeSubagent` wire methods (`core_wire.py:336-338`, handlers `:1104-1140`) | server-compat | keep |
| `profiles/repository.py:140 grant_subagent`, `:168 revoke_subagent`, `:178 subagent_grants` | server-compat | keep |
| `execution/delegation.py` `DelegationService.run/list_for`, `_merged_posture`, child-turn insert | server-compat | keep |
| synthesised MCP entry `agentbox-subagents` (`composition.py:1079-1140`) + `plugins/harness/runtime/subagent-bridge.mjs` | server-compat / harness | keep; Q3 adds no second dispatch path |
| `subagents.py` `grant_edges/resolve_roster/check_cycle/tool_definitions/validate_run_arguments` | server-compat | keep; **not** copied into Q3 |

There is no Q3-introduced duplicate of that logic to delete (see the duplication
audit in `report.md`), and no legacy file is retired by this line.

## I-5 Data compatibility

- No on-disk format, DB migration, or extension id is renamed by Q3
  (`AGENTS.md` rule 5). Q3's own store is a new private directory under its data
  root; its layout is versioned inside the package and documented at review time.
- The T05 importer is **dry-run + explicit approval only**; it writes nothing to
  legacy tables and never reads a real user data root as a fixture. Real
  user-data migration is out of scope this round.

## I-6 Cross-line seams (already published as requests)

`api-requests.md` SR-1…SR-8, readable by other main sessions via
`git show codex/011-q3-subagents:specs/011-q3-subagents/api-requests.md`.
The load-bearing ones:

- **SR-3b to C0** — the pinned Claude adapter already supports session capability
  `subagents`, `nativeSubagentSessions`, a native subagent control tool, and a
  `_meta.claudeCode.options` channel whose relevant keys (`agents`,
  `settingSources`) are rebuild-class; Ordessa today passes **none** of them
  (verified absent in `plugins/harness/src/ordessa_harness/claude/*.py` and
  `plugins/harness/adapters/acp-adapter/internal/`). Until that channel exists,
  Claude `loaded/invokable/used` stay unknown and gates G11/G18–G20 cannot close.
- **SR-2 to C0** — instance-private generation, full reset, proved reload.
- **SR-4/SR-5 to Z1/Z2** — Profile facet + Chat invoke contribution; Q3 supplies
  the single resolver so neither re-implements the override algorithm.
- **SR-6 to Q5** — ceiling authority; absent → typed refusal, never permissive.

## I-7 Cleanup guarantees (readiness checklist item)

- All probe artifacts (extracted pinned tarballs, the `npm install`ed Claude
  artifact, logs, JUnit XML, per-ID lists) live **outside** the repository under
  `/home/maoqh/ordessa-evidence/q3/` and are never committed.
- The line-local `.venv` stays untracked; no other tree's environment is touched.
- `~/.claude/agents`, `~/.codex`, `~/.pi` were **not** read, written, or used as
  fixtures (only path existence and `pi list` were observed); G24's
  zero-side-effect claim on user HOME is backed by that, and by tests that write
  only under `tmp_path`.
- No service is started, stopped or restarted by this line (`AGENTS.md` rule 8).

## I-2b — hard evidence that the root lock is stale, including this line's own entry

`npm ci` in this tree, after consuming harness-api and permissions-api, exits **1**:

```
npm ERR! code EUSAGE
npm ERR! `npm ci` can only install packages when your package.json and package-lock.json …
npm ERR! are in sync. Please update your lock file with `npm install` before continuing.
npm ERR! Missing: @ordessa/plugin-assets-subagents-ui@0.1.0 from lock file
```

Cross-checked against `package-lock.json` (`link`-type workspace entries: 25), all of
these exist on disk but are **absent from the lock**:

| Workspace directory | In committed lock? | Owner |
| --- | --- | --- |
| `plugins/assets/subagents/ui` (`@ordessa/plugin-assets-subagents-ui`) | **NO** | **Q3 — this line is one of the causes** |
| `plugins/chat/frontend` | NO | Z2 |
| `plugins/assets/sandbox/frontend` | NO | Q5 |
| `packages/desktop-platform/ui` | NO | platform/C0 |
| `examples/ui-consumer` | NO | platform/C0 |

Consequences, stated plainly:

1. Q3's own TS face is part of the desync. It is listed here so C0's single lock
   regeneration covers it; this line does **not** run `npm install` or edit the lock,
   because the final root lock is C0's exclusive surface (plan §构建与 git).
2. Root `npm run typecheck` cannot be green in any lane until that regeneration
   happens, so it is not a valid per-lane gate in the meantime. Evidence from the
   current run: 12 `error TS` lines, of which the non-Q3 ones are
   `examples/ui-consumer`, `examples/ui-foundations-probe`,
   `plugins/assets/sandbox/frontend`, and three files under `plugins/chat/frontend`
   — i.e. `@ordessa/ui` / `@ordessa/ui-components/react` unresolved, consistent with
   the missing lock entries.
3. Q3 therefore verifies its TS faces with the per-package gates
   (`npx tsc --noEmit` and `npx vitest run` inside each package), and reports the
   root-level result without claiming it as its own gate. The two Q3-attributable
   diagnostics seen so far (`subagent-input-source.ts:160` TS2322, and the
   `.typecheck.ts` TS2304/TS2552 mid-edit) are being fixed on this lane.

## I-8 — build manifest drift in C0's surface, observed and parked (not committed)

`products/desktop/extensions.lock.json` was found modified in this worktree at
2026-09-27 07:46 local, with two digests changed:

```
extensions/ordessa.agent-acp/entry.js   47d5d1c8…  ->  a87d17b4…
extensions/ordessa.agent-acp/native.js  e47c7358…  ->  a20279b7…
```

This line never runs the desktop build (`tooling/build-all.mjs`) and `products/**` is
C0's exclusive surface, so the cause is a build step invoked somewhere in this tree
during the session (candidate: a single-package agent's verification command). It is
**not** an upstream-checkpoint difference — the same path is unchanged at HEAD.

Action taken: parked reversibly as tagged stash entry
`q3-foreign-changes-products-desktop-extensions-lock` (no commit, no discard), so the
working tree stays clean for our own gates while C0 can recover the digests with
`git stash apply`. Q3 does not commit or regenerate it.

## I-9 — consolidated handoff checklist for C0 (Q3 lane), ordered by dependency

Nothing here is done by Q3, because each item crosses this line's write surface
(`plugins/assets/subagents/**` + `specs/011-q3-subagents/**`).

| # | Action for C0 | Why it blocks Q3 from closing a gate | Evidence this line measured |
| --- | --- | --- | --- |
| 1 | Inject the three admission ports in the default composition: `acp.admission.native_evidence`, `acp.admission.principal`, `server.instance_id` | Until then `ACP_ADMISSION_PORT` derives `ready=False`, so G18/G19/G20 stay refused for Q3 and no apply/send-once claim is possible | `plugins/permissions/backend/.../plugin.py:206` provides it; `plugins/harness/src/ordessa_harness/server_acp/plugin.py:98` consumes it; readiness derivation documented at that module's lines 6-11 |
| 2 | Decide the intent contract: merge Q3's adapter output onto `ordessa_harness_api` types and delete the duplicate vocabulary (SR-1b/SR-12) | Two sealed `IntentSet` shapes cannot both survive integration; Q3's is now internal | C0's real shapes: `IntentSet(intents=…)` (`intents.py:200`), `MountContent(source,target,relative_name,immutable_content_ref,mode)` (`:123`), `ContentRef(reference,sha256,size)` (`:109`), `ResetField.baseline_rule` closed set |
| 3 | Make `evidence_ref` mandatory when `Assessment.status == "supported"` | `contracts.py:197-205` only requires `reason` for the negative statuses, so "supported" is constructible with zero proof — the G01/G03 failure mode left open by the contract itself | read from the published harness-api content in this tree |
| 4 | Confirm on the apply side that `restore-owned-baseline` restores **only** the requesting `facet_id`'s baseline | FR09/G13: removing a managed generation must never touch a user's own native files | type-level only today; the enum exists, its apply-side scope is C0's code |
| 5 | Regenerate the root `package-lock.json` (and thus make `npm ci`/root typecheck usable) covering: `@ordessa/plugin-assets-subagents-ui`, Q3's `settings` face if it becomes a workspace package, plus already-pending `plugins/chat/frontend`, `plugins/assets/sandbox/frontend`, `packages/desktop-platform/ui`, `examples/ui-consumer` | Root `npm ci` fails `EUSAGE` today, so no lane can use the root TS gates; Q3 verifies per package instead | `npm ci` exit 1 with `Missing: @ordessa/plugin-assets-subagents-ui@0.1.0 from lock file`; four more workspaces absent from the lock's 25 link entries |
| 6 | Add `"@ordessa/ui-components/api"` mapping awareness where lanes need it (Q3 already mirrors chat-api's own tsconfig pattern locally) | Keeps each plugin's package-local typecheck honest without editing shared configs | four packages already carry that mapping; Q3 added it to its own tsconfig |
| 7 | Restore or supersede C0's ownership of `products/desktop/extensions.lock.json` drift parked in a tagged stash | Q3 must not commit or regenerate another lane's generated manifest | before/after digests recorded in §I-8 |
| 8 | Merge Z1's lane once so the profile content Q3 restored by path becomes proper history | Removes the ambiguity that Z1's commits are not ancestors of this branch | see `regression-ledger.md` §Dependency audit |
| 9 | Register this package in product composition (I-1) and add its editable install line to `docs/baseline.md` | G21 (isolated install / version lock / build+smoke) is C0's integration-tree gate | Q3's own suites pass in isolation here: 1 package face green, per-package TS gates green |
| 10 | Q3 registers nothing itself in `docs/known-issues.md`; the environment-shaped server baseline differences (212/67-item per-ID set after consumption) need the shared ledger re-frozen by its owner | So no later lane compares against a pre-consumption figure and calls it a regression | `regression-ledger.md` §G23 after-run |
