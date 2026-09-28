# Regression ledger — per-ID, same-cause comparison (T01 freeze + per-round diff)

Rules applied: exit codes are measured from the pytest run itself, never from a
pipe's tail; each suite is re-collected in the same turn it is recorded; an
inherited red is admitted only by matching the **exact ID and cause** against
`docs/baseline.md` / `docs/known-issues.md`. Collection errors are always FAIL.
Evidence: full logs + JUnit XML under the仓外 evidence root
`/home/maoqh/ordessa-evidence/q3/` (never committed, per `verification.md`).

## Environment for every row below

`/home/maoqh/ordessa-evidence` runs use the line-local venv
`.venv/bin/python` = Python 3.12.14, pytest 9.1.1, created this round:

```sh
python3.12 -m venv .venv
.venv/bin/pip install -r apps/server/lockfiles/server-linux-py312.txt
.venv/bin/pip install -e packages/pacthold -e apps/server -e packages/server-plugin-api -e 'plugins/harness[dev]'
.venv/bin/pip install -e plugins/server-compat -e plugins/workspace
```

All four installs exited 0; `import pacthold, ordessa_server, ordessa_harness,
server_plugin_api` → `imports ok`.

## Baseline "before" (HEAD `96fef2db47f485091ccaadda96f5321400b249f2`)

| Suite | Command | Exit | Collected result | Verdict |
| --- | --- | --- | --- | --- |
| `packages/pacthold` | `.venv/bin/python -m pytest packages/pacthold -q` | **0** | `238 passed in 2.02s`, `SKIPPED_TOTAL=0`, `VERDICT=GREEN_NO_SKIPS` | green, matches `docs/baseline.md` |
| `plugins/harness` | `.venv/bin/python -m pytest plugins/harness -q` | **1** | `2 failed, 308 passed, 3 skipped in 5.66s` | matches `docs/baseline.md:38` exactly ("308 passed / 3 skipped / 2 failed (inherited)") |
| boundary subset | `.venv/bin/python -m pytest apps/server/tests/test_dependency_direction.py apps/server/tests/test_server_compat_boundary.py -q` | **0** after env fix | `13 passed in 0.50s`, `VERDICT=GREEN_NO_SKIPS` | green |
| `apps/server` (full) | `.venv/bin/python -m pytest apps/server -q -p no:cacheprovider` | recorded below | see §"apps/server full" | — |

### The two harness reds — same ID, same cause ⇒ inherited

```
FAILED plugins/harness/tests/install/test_acp_schema_drift_target.py::test_the_acp_schema_a_closure_carries_satisfies_the_adapter_that_needs_it
FAILED plugins/harness/tests/install/test_acp_schema_drift_target.py::test_a_root_override_of_the_schema_does_not_violate_a_declaration_in_the_closure
```

Both are the npm-closure drift registered in `docs/known-issues.md:13`
(Pi's root override rewrites `pi-acp`'s exact
`"@agentclientprotocol/sdk": "1.4.0"` down to `1.3.0`). Same IDs, same
documented cause ⇒ admitted as inherited, not counted as Q3 regressions. Q3 does
not touch `plugins/harness`.

### One mid-round correction, recorded honestly

The *first* boundary-subset run reported
`1 failed, 12 passed` with
`test_the_compat_declaration_is_within_the_frozen_surface` failing as
`ModuleNotFoundError: No module named 'ordessa_server_compat'`.

That was **this line's own incomplete venv** (I had installed pacthold, server,
server-plugin-api and harness but not `plugins/server-compat` /
`plugins/workspace`), not a repo red and not an inherited red. Cause confirmed
by reading the test source: `apps/server/tests/test_server_compat_boundary.py:86`
performs `from ordessa_server_compat.core_wire import _COMPAT_METHODS,
_PARAM_SHAPES`. After the two missing editable installs the same command
collected 13/13 green. Recorded so nobody later mistakes the first row for a
Q3-introduced regression or, worse, for a pre-existing repo failure.

## `apps/server` full

Measured "before" in this line's venv at this baseline:

```
.venv/bin/python -m pytest apps/server -q -p no:cacheprovider
server_exit=1
90 failed, 670 passed, 10 skipped, 1 warning, 158 errors in 38.24s
```

Per-ID non-pass list (258 entries: 158 error + 90 failure + 10 skipped) captured
to the仓外 evidence root as `before-server.ids`, generated from
`baseline-server.xml` by a junit walk over `testcase` elements — not by reading a
log tail. Full log `baseline-server.log`, XML `baseline-server.xml`.

**This is deliberately NOT the same shape as `docs/baseline.md`'s migrated ledger**
(`783 passed / 43 failed / 10 skipped / 25 errors`). Rather than assume the
documented numbers apply, the difference is explained and bounded:

- The log's own diagnostics show this environment lacks artifacts the suite
  probes for: `ARTIFACT_worker-debug=ABSENT`, `ARTIFACT_worker-release=ABSENT`,
  `ARTIFACT_sidecar-entry=ABSENT`, `ARTIFACT_acp-npm-closure=ABSENT`,
  `TOOL_claude=ABSENT`, `TOOL_wsl.exe=ABSENT`. `docs/baseline.md` expects the ACP
  npm closure and the built Go bridge to exist; this tree has neither (no
  `npm ci`, no bridge build — both are build-artifact steps, and `AGENTS.md` rule
  4 forbids binaries in git).
- The 158 errors are therefore collected as *this environment's* pre-existing
  state at a commit that contains no Q3 code at all, which is exactly what a
  "before" must be.

Q3's after-run must be an **ID-by-ID and cause-by-cause diff against
`before-server.ids`**: zero new IDs, zero cause drift. Any change relative to the
documented ledger (e.g. after an `npm ci`) is reported as a separate environment
change with its own before/after pair, never silently absorbed.

Full-suite ledger source of truth for *classification* remains
`docs/known-issues.md` and `docs/migration/backend-build-test.md`. Q3 does not
re-litigate those rulings and does not touch shared compat files (rollout plan:
`server-compat` public removals are C0-only).

## Fourth suite (the one `tasks.md` T01 left unnamed — ruling recorded in `tasks.md` §B1)

Desktop / extension closure, measured in this tree after `npm ci` from the
committed lockfile:

| Step | Command | Exit | Result |
| --- | --- | --- | --- |
| Closure install | `npm ci` | **0** | installed from `package-lock.json`; afterwards `git status --short -- package-lock.json package.json` printed **0 lines**, i.e. the lock was not rewritten (plan: the final root lock belongs to C0) |
| Typecheck | `npm run typecheck` | **0** | `tsc --noEmit`, no diagnostics |
| Unit | `npm test` | **0** | `Test Files 13 passed (13)` / `Tests 146 passed (146)` in 13.78s |

This equals the expectation in `docs/baseline.md` ("`npm test` # 146 tests (13
files)"), so no inherited red exists in this suite at this baseline and no
per-ID list is needed. Not run here: `npm run build`,
`npm run test:electron`, `npm run test:agent-shell`,
`tests/acp-connector` vitest — they belong to G21/T13 in C0's integration tree
(see `integration-request.md` I-1/I-2) and are listed as **untested** in
`report.md` §未测 rather than assumed green.

So the four T01 suites are now all frozen: `packages/pacthold` (green),
`plugins/harness` (2 same-ID/same-cause inherited reds), `apps/server` (258
non-pass IDs captured per-ID), desktop closure (green, 146/146).

## Guard mutation audit (a green count is not evidence; a red on removal is)

Method: copy `plugins/assets/subagents` to `/tmp/mut2` (never mutating the tree),
apply **one** exact-string mutation, assert the needle existed and the text
changed, re-run `pytest tests -q` with `PYTHONPATH` pointed at the copy, and count
red IDs. A mutation whose needle is absent is reported as invalid rather than
counted as "guard proven".

Baseline for comparison: unmutated copy = **89 passed**.

| # | Mutation (guard disabled) | Result | Verdict |
| --- | --- | --- | --- |
| M1 | `scopes.LAYER_ORDER` inverted (SESSION first instead of last) | **3 red**: `test_resolution_t04.py::TestDeterministicLayering::test_higher_layer_overrides_lower`, `::TestHonestDisable::test_disable_of_managed_item_excludes_with_reason`, `::TestHonestDisable::test_disable_of_native_item_is_reported_not_faked` | **guard is live** — the 6-layer priority (ruling C1) is genuinely pinned by tests |
| M2 | `store.py` CAS: `if int(stored["row_version"]) != expected_row_version:` → `if False:` | **0 red** (89 passed) | **NOT yet covered** — no red because the T03 store tests are not on disk at audit time; G06 stays open and is re-audited after T03 lands |
| M3 | `store.py` revision immutability: `except FileExistsError: raise REVISION_STALE` → `pass` | **0 red** (89 passed) | same as M2 — **G04 not yet proven**, re-audit required |
| M4 | `ceiling.py`: drop the `toolRefs` over-ceiling refusal | **4 red**: `test_ceiling_t04.py::TestRefuseOverCeiling::test_declared_tool_ref_outside_grant_is_refused`, `::test_zero_grant_ceiling_refuses_any_tool_declaration`, `::TestAdmissionStaysWithinCeiling::test_admission_cannot_raise_the_ceiling`, `test_resolution_t04.py::TestPinsAndFailClosed::test_over_ceiling_definition_is_refused_with_field_name` | **guard is live** — G09's "definition cannot raise the ceiling" is real, not decorative |

Honest conclusion: **G07/G09 (scope layering, ceiling refusal) have live guards;
G04/G06 (immutable revision, CAS) currently have no failing-test backing** and
must not be reported as done until the T03 slice lands and M2/M3 turn red. The
audit is repeatable: the same script re-run after T03 completes is the acceptance
condition for those two gates.

### Correction: the first audit was contaminated, and the method was fixed

The run above was performed while the adapters slice was still landing, so its
`red_ids` included failures that had nothing to do with the mutation being
applied: all three of M1/M2/M4-ish probes reported the *same*
`test_adapter_intents_t06.py::test_no_intent_accepts_a_non_enum_slot[...]` IDs.
Reading one traceback showed the truth — that failure is
`assert 'DEFINITION_INVALID' == 'TARGET_CONFLICT'`, an intents-side mismatch from
the concurrently-editing slice, not a store issue at all. Counting reds without a
control therefore over-reported guard coverage.

The audit was repeated with a **control copy**: run the unmutated copy, capture
its red-ID set, then per mutation report only `reds − control`.

| Mutation | Red IDs | **New vs control** | Verdict |
| --- | --- | --- | --- |
| control (no mutation, same copy procedure) | 15 | — | 15 pre-existing failures from the in-flight adapters slice, subtracted everywhere below |
| M2 `store.py` CAS staleness → `if False:` | 15 | **0** | **still untested** |
| M3 `store.py` revision-overwrite refusal → `pass` | 15 | **0** | **still untested** |

So the earlier conclusion stands but on valid evidence, and it is now firmer:
disabling the store's CAS check and its "a stored revision is never rewritten"
guard changes **nothing** in the 228-test suite. G04 and G06 are **not** covered
by the T03 slice as it currently stands; this is routed back as an acceptance
condition and re-audited when that writer reports. The 15 control failures are
themselves an in-flight state, tracked to resolution before any stage commit.

### Third re-measurement, and the actual cause (not "missing tests" but "unreachable guard")

After `test_cas_archive_clone_t03.py` landed, the controlled audit was run again:
control 3 reds, `M2` 3 (0 new), `M3` 3 (0 new), while a control mutation of the
scope layering (`M6`) correctly produced 3 new reds — so the harness detects real
gaps, and M2/M3 silence is meaningful.

Reading the code explains *why*, and it is not that the tests are weak:

- `service.py:170-174` performs its own `row.row_version != expected_row_version`
  check and raises `REVISION_STALE`; `service.py:176-178` likewise rejects a
  revision that already exists. The tests drive `service.save_revision(...)`, so
  they exercise **the service's** check and never reach the store's.
- `store.py:81 replace_definition(..., expected_row_version)` and
  `store.py:141 write_revision(...)` repeat both guards (`if int(stored[...]) !=
  expected_row_version`, and `except FileExistsError → REVISION_STALE`).
- Because the service checks *then* writes, the store's guard is the only thing
  standing between two concurrent callers that both passed the service check —
  i.e. it is the last line of defence for US4's "并发不串", **not** dead code.
  Being unreachable through the happy path is exactly when an unverified guard is
  worth the most.

Ruling and action: this is a genuine coverage gap in the right place, so it is
sent back to the T03 owner as a named requirement — direct store-level tests for
`replace_definition` with a stale version and for `write_revision` over an
existing revision, asserting refusal *and* unchanged bytes, plus a statement of
which layer is authoritative (duplicated enforcement should be one guard, or the
inner one should be proven to be what actually catches the race). G04/G06 stay
open until the re-audit shows new red IDs under M2/M3.

Fake-green screen over the landed tests: no `pytest.skip`, no `xfail`, no
`assert True`, no bare `except: pass`, no `pytest.raises(Exception)`;
146 `assert` statements across 89 tests (per file: assignments 19, ceiling 15,
references 24, resolution 62, scopes 26).

Ownership note and its limit: writer files are disjoint by construction (each
writer got an allow-list plus the other slices' deny-lists). Because the new
package is still **untracked**, git cannot prove nobody edited a foreign file —
`mtime` shows only that the T03 writer was concurrently editing its own files
(`decoder.py` 02:28, `service.py`/`conftest.py` 02:29) and that no third party
touched them after 02:23. The finished T04 writer self-reported importing
`dto/errors/limits/digest` only, with no edits. Stated as an evidentiary limit,
not as proof.

## Q3's own suite (fifth, additive)

Recorded per stage below — it does not substitute for any of the four.

### Stage R0/R1 — documentation only (this commit)

No production file changed, so no suite can regress. Re-verified anyway:
`packages/pacthold` 238 passed, harness 2 inherited, boundary 13 passed, and the
new Q3 package suite state is recorded in the stage report rather than claimed
here.

### Stage R2 — content domain (T03)

_Pending: filled by the main agent after reviewing the writer's diff and running
`plugins/assets/subagents` plus the boundary subset._

### Stage R2b — brand adapters (T06/T07/T08), reviewed and committed `04322472c2`

Writers' self-report vs main-agent re-measurement:

| Claim by the adapters writer | Re-measured here | Verdict |
| --- | --- | --- |
| "260 passed, exit 0" for its six test files | `PYTHONPATH=… .venv/bin/python -m pytest <6 files> -q` → **260 passed**, exit 0 | confirmed |
| "full-directory run is 21 failed … none attributable to this slice" | excluding the then-in-flight test files: **386 passed, 0 failed**; the red files belong to the T03/T03b faces | confirmed |

Guard liveness, by controlled mutation (control copy first, reds reported as
`reds − control`):

| Mutation | New reds | Verdict |
| --- | --- | --- |
| M8 — flip `ClaudeKey("permissionMode", "rejected", …)` classification to `"supported"` | **0** | **not a coverage hole — the mutation was behaviour-preserving**: `_REJECTED_BY_NAME` is keyed by membership in `CLAUDE_REJECTED_KEYS`, and the compile-time refusal looks the entry up by name, so relabelling the field changes nothing. Recorded because a naive reading would have called this an untested guard. |
| M8b — empty `_REJECTED_BY_NAME` so the refusal cannot fire | **3** (`test_compile_refuses_by_name_before_any_intent[permissionMode]`, `[mcpServers]`, `test_compile_refuses_the_offending_item_id`) | **guard is live** — the FR06 field refusal is genuinely pinned by tests |

Two writer-flagged judgement calls that I am accepting with a note: Codex
`compile` refuses the whole collection (nothing emitted) rather than emitting
unreachable mounts, and `TargetSlot` has no Pi member so Pi can never produce an
intent — both are the stricter reading of `harness-adapters.md`, and both must be
re-confirmed against C0's `ordessa_harness_api` when the `harness-api` checkpoint
publishes (SR-1b), since Q3's slot enum is being replaced by C0's
`TargetHandle`/`FieldPath`.

Still open on this face: `base.py`'s "file existence cannot yield `loaded`" rung was
**not** mutation-tested (needle not located), so G11/G12's structural claim is
reviewed by reading, not by a proven-failing test. Listed in `report.md` §未测.

### Closing the G04/G06 store-guard condition (post-checkpoint follow-up)

A third writer was dispatched with ownership of exactly one new file
(`tests/test_store_guards_direct.py`) and the instruction to report dead code
honestly rather than manufacture a passing test. Main-agent re-measurement in a
scratch copy, running only that file:

| Run | Result |
| --- | --- |
| control (unmutated copy) | `5 passed`, red set empty |
| mut1 — `store.replace_definition` CAS → `if False:` | `2 failed, 3 passed` → **2 new reds** (`test_a_stale_expected_row_version_is_refused_and_the_row_bytes_do_not_move`, `test_a_row_version_advances_and_a_repeat_of_the_stale_write_is_still_refused`) |
| mut2 — `store.write_revision` `except FileExistsError: raise` → `pass` | `1 failed, 4 passed` → **1 new red** (`test_a_stored_revision_number_is_refused_and_its_bytes_do_not_move`) |

Red sets are disjoint, so neither kill is contamination. Verdict: the guards were
**genuinely untested, not dead code** — reachable and behaviour-bearing at the
store boundary (mut1 lets a stale writer actually overwrite the row; mut2 silently
accepts a history-rewriting publish). Both are now killed, so **G04 and G06 are
closed at L1**.

One subtlety worth keeping: under mut2 the on-disk bytes still do not change (the
underlying `os.link` fails), so a bytes-only assertion would have stayed green —
the typed-refusal assertion is what makes that test capable. Recorded because a
future reviewer might otherwise "simplify" the test into a blind one.

## After-runs with the Q3 packages present (repo-wide gates)

| Command | Exit | Result |
| --- | --- | --- |
| `npm test` (root) | **0** | `Test Files 13 passed (13)`, `Tests 146 passed (146)` — identical to the frozen "before", so the Chat UI package introduces no desktop regression |
| `npm run typecheck` (root) | **1** | 28 `error TS` lines, **all** in `plugins/assets/subagents/settings/src/contract.ts:341-342` |
| `git status --porcelain -- package-lock.json package.json` | — | **0 lines**: the new workspace-facing packages did not rewrite the root lock (C0's exclusive surface) |
| `cd plugins/assets/subagents/ui && npx vitest run` | **0** | 26/26 |
| `cd plugins/assets/subagents/ui && npx tsc --noEmit` | **0** | clean |

The root typecheck failure is **not** a Q3 defect and not caused by the committed
`ui/` package: `contract.ts(341,17)` etc. are syntax errors on a line being
written *while* `tsc` ran — the Settings slice had only just created
`package.json`, `src/contract.ts`, `tsconfig.json`, `vitest.config.mjs` and had no
test file yet (`npx vitest run` there reported "No test files found"). It will be
re-measured once that writer is idle, and **the publication commit must not be
made while any TypeScript writer is mid-file**, because the root `apps/desktop`
tsconfig globs `plugins/**` and therefore type-checks an in-flight file.

Two useful facts that this failure established, both needed later:

1. The root typecheck **does** cover `plugins/assets/subagents/**` (paths appear
   as `../../plugins/assets/...` from `apps/desktop`), so no tsconfig edit is
   required to keep the new packages checked — the integration question raised in
   `integration-request.md` I-2 is answered: nothing has to change for coverage.
2. Because of (1), a broken file anywhere under this package turns the repo-wide
   gate red, which is exactly the guard that must be green before `codex/011-q3-ready`
   is created.

### Triage of the remaining prohibition-guard reds (main agent, measured per symbol)

Whole-package state at this measurement: **17 failed / 587 passed**, all source
files parse clean. The four guard/boundary reds were each checked against the code
they accuse, and three are the scanner flagging its own defence:

| Red | Accusation | Actual code | Verdict |
| --- | --- | --- | --- |
| `test_g24_no_module_reaches_for_the_user_home` | `service.py: .home()`, `'~'` literals in `decoder/migration/service` | `service.py:683-686` calls `Path.home()` **to refuse** an import root equal to or under HOME; `decoder.py:190,301`, `migration.py:459`, `service.py:704` are all `startswith("~")` path-shape **refusals** | **false positive** — but it exposes a real weakness: the guard cannot distinguish "read HOME to reject" from "write HOME", so as written it neither proves G24 nor tolerates the defence. Needs refusal-site allow-listing plus a behaviour test that a home-rooted import is refused |
| `test_fr12_the_old_grant_table_is_never_the_definition_store` | `SQL/table token 'UPDATE '` in `claude.py`, `assignments.py` | `grep -n "UPDATE "` returns **no match** in either file → case-insensitive prose match | **false positive** (scanner too broad) |
| `test_boundaries_t03b` artifact walk | `ui/node_modules: forbidden artifact directory` | created by my own `npx vitest run` for verification; gitignored, never committed | **environment artifact**, guard should skip ignored dirs; `node_modules` gets cleaned before the final publication regardless |
| `test_fr08_the_native_write_scan_is_capable` | its own capability probe: `_native_write_literal('Path("~/.claude/agents/x.md").write_text("y")')` returned `[]` | the scanner does **not** detect a literal native-path write in a sample it is fed | **genuine defect in the guard**: a probe that cannot see the exact case it exists to catch means FR08's native-write assurance is currently decorative. Must be fixed, not deleted — deleting the probe would convert a real finding into a passing test |

Rule applied while triaging: a red guard is investigated by reading the accused
line before being called either a defect or noise, and a failing *capability probe*
is treated as a defect in the guard rather than as a test to relax.

## Stage R3 — after-run of the inherited suites, live tree (G23)

Measured in the real worktree at HEAD `126f7429b8` (T05 importer landed, 88 tests):

| Suite | Command | Result | Diff vs frozen "before" |
| --- | --- | --- | --- |
| `plugins/harness` | `.venv/bin/python -m pytest plugins/harness -q` | `2 failed, 308 passed, 3 skipped`, exit 1 | **identical counts and the same two IDs** as the baseline (`test_acp_schema_drift_target.py` npm-closure pair) ⇒ 0 new reds, 0 cause drift |
| `packages/pacthold` | same form | `238 passed`, exit 0 | identical |
| boundary subset | `test_dependency_direction.py test_server_compat_boundary.py` | `13 passed`, exit 0 | identical |
| Q3 package (tracked content only) | `PYTHONPATH=… pytest plugins/assets/subagents/tests -q` in a detached worktree at HEAD | `479 passed`, exit 0 | new package, no baseline |

### A false alarm worth keeping in the record

A first attempt measured `packages/pacthold` + `plugins/harness` from a **throwaway
worktree** while reusing this line's venv, and reported `25 failed, 523 passed`,
including
`test_single_distribution.py::test_dsh_qwen_kilo_assets_use_the_single_plugin_root`.
That looked like a Q3-caused regression in an "assets" guard. It was not:

```
assert production.PLUGIN_ROOT == root
E  PosixPath('/home/.../011-q3-subagents/plugins/harness') == PosixPath('/tmp/q3c4/plugins/harness')
```

`ordessa_harness` is installed **editable against the original tree**, so from a
copy every `PLUGIN_ROOT`-identity test compares the copy's path against the real
tree's and fails (21 of the 25 were `test_core_identity.py`). Re-running in the
live tree reproduces the baseline exactly.

Rule recorded: a copy worktree is valid for checking *this line's own tracked
content* (it has no editable-install dependency) but **not** for measuring
`plugins/harness`, whose tests assert absolute-path identity. Per-ID regression
numbers must come from the live tree.

## Post-consumption measurement (foundation `8844c475bc` + profile-api `4943628f47`)

Both merged by fixed publication SHA after verifying `status: READY`,
`implementationSha` ancestry and descent from this line's base. Venv refreshed
(`-e plugins/harness/api`, `-e plugins/profile`, `-e plugins/runtime-compat` — all
new with foundation; `install_exit=0`).

| Gate | Before consumption | After consumption | Reading |
| --- | --- | --- | --- |
| Q3 package | 635 passed / 0 failed | **639 passed / 0 failed** | Q3's own surface unaffected by the merges |
| `packages/pacthold` | 238 passed | `212 passed` (exit 0, no failures) | 26 collected items disappeared from this suite — foundation restructured packages, so the **per-ID comparison is now invalid** and must be re-frozen against the post-merge baseline before any further regression claim |
| `plugins/harness` | 2 failed / 308 passed / 3 skipped | `3 failed / 346 passed / 3 skipped / 28 subtests` | baseline no longer comparable (346 vs 308 = foundation added tests); one additional failure whose cause is **not yet attributed** |

### Conflict found and routed (not absorbed, not worked around)

`import ordessa_profile` fails in the merged tree:

```
ImportError: cannot import name 'AgentBoxProfileV1' from 'pacthold.resource_contracts' (unknown location)
```

Z1's `profile-api` (published against its own base) expects a symbol that the
`foundation` C0 just published no longer provides. This is a genuine inter-checkpoint
incompatibility between two sibling lanes, **outside Q3's write surface**: this line
does not patch either package, does not pin around it, and does not silently drop
the profile-api merge. Reported to Z1 (producer of `profile-api`) and C0 (producer of
`foundation`) as a concrete symbol pair: `pacthold.resource_contracts.AgentBoxProfileV1`.

Consequence for this line's remaining scope: T10 (Profile facet/editor) was unblocked
by `register_v2_facet` appearing, but the facet wiring cannot be *executed* until the
above import works, so T10 stays open with this exact blocker named, and
`report.md`/`q3.json` must not claim T10 progress based on the checkpoint's existence
alone.

### Post-consumption baselines re-frozen and attributable (resolution)

The "not comparable" note above was resolved by fixing this line's own
environment rather than by reinterpreting numbers:

| Gate | Command | Result | Attribution |
| --- | --- | --- | --- |
| `packages/pacthold` | `.venv/bin/python -m pytest packages/pacthold -q` | exit 0, **212 passed**, junit shows **0** non-pass items | the 238→212 delta is upstream restructuring (items moved), **not** failures; per-ID list `after-pacthold.ids` is empty |
| `plugins/harness` | same, after `.venv/bin/pip install -e products/server` | exit 1, **2 failed / 347 passed / 3 skipped / 28 subtests** | the 2 failures are exactly the inherited npm-closure pair (`test_acp_schema_drift_target.py::test_the_acp_schema_a_closure_carries_satisfies_the_adapter_that_needs_it`, `::test_a_root_override_of_the_schema_does_not_violate_a_declaration_in_the_closure`) ⇒ **0 new reds** |

The third failure seen before the install,
`tests/test_external_adapter_product.py::test_external_adapter_default_product_registration_compile_and_retirement`,
raised `SERVER_PRODUCT_MISSING: no installed product provides …`. That test arrived
*with* foundation, and the cause was that my venv had no product package installed.
Installing `products/server` (exit 0) cleared it: 347 passed, one more than before,
i.e. the previously-erroring test now runs and passes. Recorded because the honest
reading is "my gap", and `AGENTS.md`/rollout R01 expect each tree to install its own
dependencies.

Baseline files: `post-foundation-{pacthold,harness}.{log,xml}`, per-ID lists
`after-pacthold.ids` (empty) and `after-harness.ids` (6 items: 2 failure +
… + 3 skipped), all under the仓外 evidence root.

## Second consumption round (harness-api + permissions-api), 2026-09-27 23:37–23:50 UTC

| Checkpoint | Publication SHA | Verified before merge | Merge commit |
| --- | --- | --- | --- |
| `harness-api` (`codex/011-harness-api-ready`) | `d3f026904ead6c7ce58df26f2536175ce6179de7` | `status=READY`, producer `c0`, `implementationSha=61966e3118` **is** an ancestor, `planAnchor=refs/heads/codex/011-plugin-plan` | `c788f1741f` |
| `permissions-api` (`codex/011-permissions-api-ready-r4`) | `ad8902d5c8e6ae6882057e1ddde400110c837bb0` | `status=READY`, producer `q5`, `implementationSha=a98048216c` **is** an ancestor, same anchor | `1bc22ccb1b` |

In-flight work from the stopped T09 writer (4 modified files) was parked first as a
**tagged** stash entry `q3-t09-inflight-from-stopped-writer` rather than discarded, so
it can be restored by that exact name; nothing of another lane's was touched.

### Environment gaps that were mine, and the true per-suite numbers after fixing them

Measured with exit codes redirected to a file (not from a pipe's tail):

| Gate | Raw result right after the merges | Cause | Result after fixing my own gap |
| --- | --- | --- | --- |
| `plugins/harness` | **4 collection errors**, `ModuleNotFoundError: No module named 'tomli_w'` | upstream C0 tests need `tomli_w`; absent from my venv ⇒ **my gap** | `.venv/bin/pip install tomli_w` → **2 failed / 433 passed / 3 skipped / 37 subtests**, and the two failures are exactly the registered npm-closure IDs (`install/test_acp_schema_drift_target.py::test_the_acp_schema_a_closure_carries_satisfies_the_adapter_that_needs_it`, `::test_a_root_override_of_the_schema_does_not_violate_a_declaration_in_the_closure`) ⇒ 0 new reds vs the *new* baseline |
| `packages/pacthold` | 212 passed, exit 0 | — | unchanged; still the post-foundation figure (238→212 is upstream restructuring, 0 non-pass items) |
| `apps/server` | **42 failed / 1116 passed / 10 skipped / 25 errors** | upstream added ~446 collected tests since the pre-consumption 670 | per-ID set captured to `merged-server.xml`; comparison is now against Q5's published ledger (`43F/850P/10S/25E`), not against my own stale numbers |
| `npm run typecheck`, `npm test` | both exit 1 | **two different causes, split honestly**: (a) root `node_modules` stale after the merges — `@ordessa/ui`, `@ordessa/ui-components/react` unresolved in `examples/**` and `plugins/assets/sandbox/**`; (b) **one genuine Q3 defect** | (a) is a refresh step owned by the integration lane and deliberately not fixed by editing root files; (b) is being fixed now by a single-package writer |

### The genuine Q3 defect found by the merge (contract drift, not my test being wrong)

`chat-api` moved to **r3** in this tree (`33abf4efbf`, `47459b0acb`). Its
`ChatInputEntryAction` `invoke` variant changed shape:

```
plugins/chat/api/src/contract.ts:222
  | { readonly kind: 'invoke'; readonly execute: (location: ChatLocation) => Promise<ChatActionResult> }
```

Our committed Chat face still supplies a `ChatScopedAction<void>` closing over the
*query* location, so the root typecheck reports

```
plugins/assets/subagents/ui/src/subagent-input-source.ts(160,31): error TS2322
```

This is not merely a type nuisance: the new signature hands us the **selection-time**
location, which is exactly what G17's stale-target rule needs, so the fix must make
`execute` treat its argument as authoritative and revalidate it — closing the type
error while *strengthening* the guard, never by casting.

### Baselines that are now void and must not be reused

Any statement of the form "harness 2 failed / 308 passed" or "server 90 failed /
670 passed / 158 errors" describes the **pre-harness-api tree** and is superseded by
the numbers in this section. Regression claims after this point compare against the
`merged-*.xml` JUnit files only.

### `npm ci` refresh attempt: failed, and why that is not this line's gate

`npm ci` exit **1**, `EUSAGE` … `Missing: @ordessa/plugin-assets-subagents-ui@0.1.0
from lock file`. Verified against the lock: 25 link entries, while
`plugins/chat/frontend`, `plugins/assets/sandbox/frontend`,
`packages/desktop-platform/ui` and `examples/ui-consumer` are also absent. So the
root lock is stale across several lanes **including Q3's own new package**, and
regenerating it belongs to C0 alone; this line leaves the lock untouched
(`git status --porcelain -- package-lock.json package.json` → 0 lines, re-checked
after the failed `npm ci`).

Root typecheck is therefore recorded as "blocked on lock regeneration", with its 12
diagnostics itemised by owner in `integration-request.md` §I-2b, and Q3's gates are
the per-package `tsc`/`vitest` runs.

## Lane-integrity defect caused by my own sequential merges, repaired

While merging `permissions-api` (`1bc22ccb1b`), git resolved against Q5's history and
**deleted 55 files of Z1's lane from this branch**, among them the whole
`plugins/profile/**` package, `plugins/profile/api/**`, Z1's `specs/011-z1-profile/**`
evidence, and `specs/011-plugin-rollout/checkpoints/profile-api.json`. The harness-api
merge deleted nothing; the damage was confined to this one merge.

Repaired by restoring each deleted path from the profile-api publication SHA
`4943628f47…` (read-only restore of Z1's own published content — no reimplementation,
no edits to their files).

### A wrong conclusion this repair overturned

Before restoring, `import ordessa_profile` "succeeded" while
`import ordessa_profile.contracts` failed. I read that as *the AgentBoxProfileV1
conflict is resolved*. That reading was wrong, and the cause is worth the rule:
`ordessa_profile` resolved as a **namespace package over a nearly empty directory** —
the merge had deleted its modules — so the import proved only that the name was
importable-by-accident, not that the seam existed.

Corrected state, re-measured after the restore:

```
plugins/profile/src/ordessa_profile/plugin.py:17
  from pacthold.resource_contracts import AgentBoxProfileV1
ImportError: cannot import name 'AgentBoxProfileV1' from 'pacthold.resource_contracts'
```

So **T10 remains genuinely blocked** on the Z1↔C0 symbol conflict, exactly as first
recorded, and the `AgentBoxProfileV1` request stays with C0/Z1. Rule taken away: an
import that succeeds must be confirmed by resolving to a real file path
(`__path__`/`__file__`) before it is used as evidence that a seam exists.

### Second repair pass: the restore had used Z1's stale publication, and that hid T10

Restoring from the profile-api publication SHA `4943628f47…` brought back
`plugin.py:17 from pacthold.resource_contracts import AgentBoxProfileV1`, which fails
because `foundation` removed that marker (it exists on `main`, not on
`codex/011-foundation-ready` — verified per-ref with `git grep -l`).

Z1 had already adapted upstream: commit `40cb6cc4ed "Z1: adapt to foundation 8844c475bc
- runtime-compat contract import …"` moves the import to
`pacthold_runtime_compat.resource_contracts`, i.e. the package this line had already
installed from `plugins/runtime-compat`.

Repaired by taking Z1's own lane tip `codex/011-z1-ready` for `plugins/profile/**` and
`specs/011-z1-profile/**` (28 files, +2532/-82 — their content, unmodified by Q3), then
measuring:

| Check | Result |
| --- | --- |
| `import ordessa_profile.contracts` | succeeds |
| `ProfilePluginServices.register_v2_facet` | **present** ⇒ T10's seam exists |
| `.venv/bin/python -m pytest plugins/profile -q` | exit **0**, `140 passed` |

So T10's blocker is **lifted by consuming Z1's newer committed work**, not by patching
either lane — and the earlier "conflict resolved" note in this ledger was right in
conclusion only by accident (it had been measured against a directory my own merge had
emptied). Both statements are kept here in order so the sequence is auditable.

## Producer proofs re-run in this tree (consumption protocol step), 2026-09-28 00:27

| Package | This tree | Producer's record | Same? |
| --- | --- | --- | --- |
| `plugins/harness/api` | exit 0 — `14 passed, 37 subtests` | harness-api record lists an aggregated command including C0 harness suites | not directly comparable (different command scope), no failure |
| `plugins/permissions/api` | exit 0 — **316 passed** | `223 passed` | **more tests here, 0 failures** — record was taken at an earlier revision; treated as an additive difference, not a contradiction |
| `plugins/permissions/backend` | exit 0 — **134 passed** | `69 passed` | same reading |
| `plugins/permissions/adapters` | exit 0 — **124 passed** | `100 passed` | same reading |
| `plugins/assets/sandbox` | exit 0 — **269 passed** | `sandbox 218` inside a combined 610 | first attempt errored with `ModuleNotFoundError: No module named 'ordessa_sandbox_api'` — **my missing editable install**; after `-e plugins/assets/sandbox/{api,backend,adapters}` it is green |
| `plugins/profile` (Z1 tip) | exit 0 — `140 passed` | Z1 lane record | reproduced |

Rule applied: a collection error in a suite I have not installed is **my** gap and is
fixed by installing, never reported as an upstream red — and a larger passed-count than
the producer's is recorded as an additive difference with the reason, not silently
claimed as "same as record".

## Dependency audit — exact ancestry of everything this branch stands on

`git merge-base --is-ancestor <sha> HEAD`, run at 2026-09-28 00:30:

| Upstream | Publication SHA | Ancestor of HEAD? | How it arrived |
| --- | --- | --- | --- |
| `chat-api` r1 | `54ad26c15d` | **YES** | merge `c0686a2407` |
| `chat-api` r3 | `3d8c3fa410` | **YES** | merged into the lane history before the harness/permissions merges; r2 = `31fb2db46d` also present |
| `foundation` | `8844c475bc` | **YES** | merge `2b307ab48c` |
| `profile-api` | `4943628f47` | **YES** | merge `7c5dfa0a56` |
| `harness-api` | `d3f026904e` | **YES** | merge `c788f1741f` |
| `permissions-api` r4 | `ad8902d5c8` | **YES** | merge `1bc22ccb1b` |

**One honest exception.** To repair the deletion damage I fixed Z1's content to their
lane tip `codex/011-z1-ready`, which was done with `git checkout <ref> -- <paths>`
(file restoration), **not** a merge. Consequences, stated plainly:

- the profile **files** here are Z1's newest committed content and their suite passes
  (140/140), but their **commits are not ancestors of this branch**, so `dependsOn`
  cannot honestly list `codex/011-z1-ready` as a consumed publication;
- what is recorded as consumed is the published `profile-api` SHA `4943628f47`
  (an ancestor), and the newer content is a documented, reversible working-tree
  restoration;
- for C0's integration the clean resolution is to merge Z1's lane once, which replaces
  the restored files with their history and removes this ambiguity.

## G23 after-run in the merged tree, per ID **and** per cause

`apps/server` re-run after all consumptions and after Q3's own slices landed:

```
42 failed, 1116 passed, 10 skipped, 1 warning, 25 errors   exit 1
baseline (post-consumption) non-pass IDs: 67        after-run non-pass IDs: 67
new IDs: 0        disappeared IDs: 0        cause drift after normalisation: 0
```

Comparison method, because the naive version lied: comparing raw JUnit `message`
text reported **59 "cause drifts"** that were entirely `tmp_path` noise — pytest's
per-run directory counter differs between runs
(`pytest-1841/test_x0` vs `pytest-1880/test_x0`). After normalising
`pytest-<n>`, the test-name suffix and `0x…` addresses on **both** sides, the same
67 IDs show **zero** cause drift, and the failure `type` is identical too.

So the honest claim is: identical ID set, identical normalised cause, no
unexplained increment against the post-consumption baseline — and the inherited-red
classification itself still comes from `docs/known-issues.md` /
`docs/migration/backend-test-red-ledger.md`, which this line does not re-litigate.

Artifacts: `merged-server.{log,xml}` (before), `after-server.{log,xml}`,
`after-server.ids.txt` (per-ID list), all under the仓外 evidence root; the
normalising comparator lives at `/tmp/cmp.py` (scratch, not committed — recreated
here so the diff is reproducible: `pytest -p no:cacheprovider --junitxml=…` on both
sides, then compare `(type, normalised message)` per ID).

## Whole-domain prohibition audit, re-run after every face landed (main agent)

Re-checked by text scan over `src/**`, not by trusting the green suite:

| Requirement | Scan | Result |
| --- | --- | --- |
| FR12 — no legacy dispatch mechanism | `run_subagent|resolve_roster|grant_edges|check_cycle|has_delegation|server_subagent_grants|agentbox-subagents` | three hits, all legitimate: `migration.py:426` is the **REJECT** rule's key list, `service.py:13` and `plugin.py:7` are docstrings naming what must stay with its old owner. No dispatch code exists here |
| FR08 — no native write, no spawn, no model call | `import subprocess|import socket|urllib|http.client|os.system|Popen` | **zero hits** |
| G24 — never touch the user HOME | `Path.home()|expanduser` | two hits, **both enforcement**: `service.py:683` refuses an import root equal to or under HOME; `wire.py:138-140` is a deliberate `_home()` indirection feeding the same refusal at `wire.py:315-317` |

This is also why the prohibition guard's original HOME scan was wrong rather than the
code: it flagged *any* `Path.home()` use, so it accused the defence and, being blind to
literal write shapes, would have missed an actual leak. The guard is being migrated to
distinguish "read HOME to refuse" from "write under HOME" (SR-13 context, `I-9` row 5).

## Sibling and inherited suites with all in-flight faces present (working tree, 00:51)

| Suite | Command | Result | Attribution |
| --- | --- | --- | --- |
| `packages/pacthold` | `.venv/bin/python -m pytest packages/pacthold -q` | exit 0 — `212 passed` | equals the post-consumption baseline |
| `plugins/harness` | same form | exit 1 — `2 failed, 433 passed, 3 skipped, 37 subtests` | the 2 are the registered npm-closure IDs (`install/test_acp_schema_drift_target.py::test_the_acp_schema_a_closure_carries_satisfies_the_adapter_that_needs_it`, `::test_a_root_override_of_the_schema_does_not_violate_a_declaration_in_the_closure`); 433 vs the earlier 308/347 = harness-api added tests upstream |
| boundary subset | `test_dependency_direction.py test_server_compat_boundary.py` | exit 0 — `15 passed` | grew from 13 upstream, still green |
| sibling lanes touched by this line's consumption | `pytest plugins/profile plugins/permissions/api` | exit 0 — **456 passed** | Z1 and Q5 packages unaffected by Q3's faces |
| Q3 package | `pytest plugins/assets/subagents/tests` | exit 1 — `18 failed, 824 passed` | all 18 are the two guard files awaiting migration; every other face (adapters remap, permissions seam, ceiling/references, plugin registration, apply) is green here |

## Permissions seam accepted on the main agent's own measurement (writer died at its turn cap)

The seam writer stopped at its 150-turn limit with a stale last line ("let me write the
seam adapter first"), so acceptance is based on the tree, not its message. Measured:

| Run | Result |
| --- | --- |
| `tests/test_permissions_seam_t04.py + test_ceiling_t04.py + test_references_t04.py` (scratch copy, control) | exit 0 — **91 passed**, empty red set |
| M1 — unmapped authority code resolves to permissive instead of `OPERATION_UNKNOWN` | `2 failed` → `test_every_answer_lands_on_a_declared_c5_code`, `test_the_refusal_code_table_covers_their_whole_closed_vocabulary` |
| M2 — a denial entry remapped to a different C5 code | `2 failed` → `test_every_answer_lands_on_a_declared_c5_code`, `test_a_tool_the_vocabulary_has_no_word_for_is_operation_unknown` |

So the earlier defect I flagged while it was mid-write — every refusal collapsing to
`OPERATION_UNKNOWN`, which would have destroyed §C5's item-level reasons — is gone: the
seam now carries an explicit decision table over the authority's closed vocabulary, with
`OPERATION_UNKNOWN` reserved for genuinely unrecognised answers (fail-closed but honest),
plus tests that the table covers that vocabulary in full. 94 assertions across 19+ tests,
no skips.

Accepted at L1. Note what this does **not** upgrade: with the composition still missing
`acp.admission.native_evidence` / `acp.admission.principal` / `server.instance_id`
(SR-3c), the authorizer's answer is adjudication only — no pre-effect enforcement, so
G09's L2/L3 half and G18–G20 stay open.
