# Main consolidation: structural checkpoint (2026-10-19)

Phase: integration in progress. Health: at risk. Main has not advanced.

The original defect was a source baseline that inherited retired physical owners
and reversed migrated workspace paths. This checkpoint adopts 4,652 verified
nightly files, retires 2,193 old paths in the isolated integration tree, recovers
nine ignored DI Token source files from the full verified archive, and corrects
61 source/config files plus the exact `.gitignore` exceptions mechanically from
`packages/interfaces/workbench/` to `packages/interfaces/channels/workbench/`.
The original worktrees, raw indexes, history and unique private data remain
protected. No original worktree has been removed.

`structure-source-manifest.json` gives every adopted path/hash and retirement.
Only the original nightly source is active in this checkpoint. The subsequent
SDK/WIP candidate is preserved separately; its conflicts are not silently chosen.
Engineering business development/tests/migrations remain frozen; the untested
review-selection producer is not activated. This commit is a recovery/integration
checkpoint, not acceptance of the old Unit runtime or full product.

Actual verification:

- Python stdlib manifest identity/version check: 51 distributions PASS.
- Repository `_validated_workspace`: 51 projects / 54 source roots PASS.
- Explicit npm workspace paths and package-lock links: no missing targets.
- `node --test tooling/tests/root-scope-resolver.test.mjs`: exit 0, one file PASS.
- `node --test tooling/tests/dependency-boundaries.test.mjs`: exit 0, one file PASS.
- `git diff --cached --check`: exit 2, 144 inherited whitespace diagnostics;
  see `diff-check-summary.json`. No blanket source/Engineering formatting applied.
- `node tooling/checks/dependency-boundaries.mjs`: exit 1. The same scan improves
  from 62 unresolved resources to 6, with 0 reported violations and 41 unresolved
  dynamic references. It remains FAIL. See before/after JSON; these are source
  scans, not isolated builds, installed tests or real model calls.

The six remaining resource failures refer to upstream profile build outputs:
Claude Code and Codex `index.js`, and Pi `agent.js`, `deps.js`, `steering.js`,
`loaded-turn.js`. They require formal artifact/build-context verification; no
fake stub or scanner exclusion was added.

Subsequent differences: 224 conflict events / 223 target paths remain. Automatic
selection was withheld for four reverse-manifest events and one retired-owner
path; 367 Engineering events stay frozen and 134 historical documentation events
stay in the protected history. These 506 dispositions are not 506 code defects.
The candidate has not replaced this checkpoint's source.

Remaining before main can advance: resolve the SDK/WIP ownership/content conflicts,
verify original assertions and consumers, Unit runtime retirement and sole state
authority, formal brand artifact/installation closure, documentation links, and
required offline regressions. Earlier pip and local DSH model-management denials
remain in force; neither endpoint nor real models were called in this batch.

## Lower SDK integration checkpoint

185 / 223 source conflict targets are resolved; 38 remain in CLI/product assembly,
Workspace and original assertion migration. Source adoption and exact bytes are
in `lower-source-manifest.json`; the old structural manifest is historical at
commit 0ed8f7a396563f29ddecf813d5d9e41f9d686930, not a claim about current bytes.

Actual validation: 434 passed / 1 external OpenShell gateway skip for current lower
APIs, 319 passed for all 15 current brand SDK/compiler selections, and 53 passed
for generic host/real MCP stdio and controlled loopback HTTP. The one CLI package
relative-import regression was reproduced against the preserved previous wheel
(1 failed) and repaired in real rebuilt wheels (53 passed).

The broader brand selection still has five collection errors from original tests
using retired RuntimeProvider/Claude SDK APIs. Sixteen original tests scheduled
for deletion by the incoming delta remain preserved until equivalent assertion
migration is shown. These incomplete assertions are not reported as passed.
No new skip or stub was introduced. Current tests loaded first-party modules only
from this tree or the explicitly built interface wheels.

The six apparent native profile source misses are verified emitted-artifact edges:
three original package identities and pinned member hashes passed actual template
emission. The actual boundary scan is PARTIAL: zero errors, zero violations,
41 unresolved dynamic edges. This is not full installed/default-product acceptance.

All 367 frozen Engineering/method source events and five automatic selection
refusals have recoverable old/new Git object references in
`deferred-source-recovery.json`. The valid pure Codex compiler probe was rescued
to `tooling/checks/decision-runtime/evaluation/codex_flow_probe.py`; reverse
manifest owner paths were not adopted, while real Python distribution/version
additions were merged at the correct owners. Engineering business remains frozen.

Main has not advanced; no worktree has been removed, no remote push or real model
call occurred. These results do not close Unit retirement or old product consumers.

## Workspace and Profile UI checkpoint

190 / 223 conflict targets resolved; 33 remain. Workspace now owns its binding
identity DTO, preserves exact historical serialization and all three original
error class ASTs, and uses Infrastructure ports. Ten identity tests passed with
zero skips. Profile UI uses current operation contracts at their actual owner;
frontend typecheck and eight tests passed. This does not qualify Workspace sandbox
execution or installed/default-product acceptance. See `workspace-ui-checkpoint.json`.

`STATUS.json` records two material integration gates: unsatisfiable frozen
Engineering dependency constraints and the incoming Server CLI versus existing
desktop HTTP launch behavior. The 42 passing selected product tests do not close
these gates. Product integration remains uncommitted; main is unchanged.

## Blocker diagnosis and independent schema owner

191 / 223 targets resolved; 32 remain. The current SDK schema generator now
verifies the mirror at its actual transport-client owner, whose real wheel ships
that mirror. Direct isolated verification passed. Fresh app wheels also passed
two current CLI consumer cases without skips; the CLI/product changes remain
uncommitted. The bundle publisher and installed dependency closure are unqualified.

`BLOCKER-DIAGNOSIS.md` gives exact preserved origins, minimal alternatives, file
scope and validation conditions for the Engineering and Server integration gates.
Four Engineering adapters fail a pure import check against 0.2; runtime source
integrity also refuses the old ABI. Application/domain files remain byte-identical
to verified nightly. The old HTTP flags parse under preserved nightly but the
uncommitted new module returns exit 2 before startup. No functional disabling
or speculative compatibility runtime was added.

## HTTP launch compatibility and approved Engineering adapter

192 / 223 targets resolved; 31 remain. The HTTP module/ordessa-server entry is
restored alongside the separate one-shot ordessa CLI. Six original transport
helper ASTs are unchanged. Nine original launch assertions and nine rebuilt-wheel
HTTP/Product/root/foreground tests passed without skips. The three actual HTTP
process cases verify temporary roots, listening, /live, bearer checks, current
Profile queries and original owner/root cleanup. Unconfigured default composition
refuses before root writes; production input selection is still unresolved.
See `http-entrypoint-checkpoint.json`; this is not full default-product acceptance.

User approved narrow Engineering adapter changes at 08:09 UTC. Commit 80e0d59df5
adapts the finite local selector to genuine rules jobs; 98 tests pass with zero
model calls. New evidence has explicitly new schema versions; no old manifest is
fabricated. The original source reviewer and historical receipts remain preserved.
Native evidence/Profile/Unit/pin compatibility is still incomplete. Older notes
about a blanket Engineering freeze describe the earlier checkpoint only.

## Grouped remaining work and genuine Decision reads

201 / 223 source conflicts resolved; 22 remain. The former 31 are grouped with
every path and shared cause in `REMAINING-GROUPED.md`; nine verified owner/codec
dispositions close together in `grouped-owner-resolution.json`. Original Server
identity logic moved with unchanged AST onto its existing DatabasePort/table;
two real temporary-database tests pass. Context/HTTP/codec tests pass 32 cases;
all original canonical assertion ASTs, including the full Library JSON test, remain.
No current production static import refers to the retired Server facades.

Commit b84492fafa restores reader-only original decision-evidence/1 validation
and its exact archived fixtures, preserving every original historical test body.
It adds a read-only view of the existing scoped new-job claim/result records,
without creating claims or replaying calls. Thirty-five tests pass, including
real controlled multi-answer job production and unchanged UNKNOWN readback. No
summary is presented as an old manifest, and no graph/sink/online runtime returns.
The Engineering source reviewer still needs to bind these real readers/producers
to its existing MethodControl/BlobStore/approval/fence rules; main remains held.
