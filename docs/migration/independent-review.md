# Independent review — Ordessa monorepo candidate (lead-executed)

The dedicated review subagent was terminated by the usage cap (22:40); the
lead completed its checklist directly. Evidence for every item was produced
in this session's shell history; key results are summarized here. Review
scope: candidate main at `c0ff0479e07b` (+ doc commit `fa461219ceda`, no tree
effect), archive refs at the same moment.

## 1. File integrity — PASS (2 defects found and fixed)

Scripted comparison of all files in the three frozen source trees against
candidate main + the two migration tables (script: `check1_files.py`,
data: `data/*.txt`).

- agent-box @a0b343e0: every source file mapped (migrated / registered drop).
- desktop @450944bd: every source file mapped.
- acp-adapter @41d9d94: every source file mapped.

Defects found → fixed in `df6327574d03`:
- `apps/server/lockfiles/server-windows-py312.txt` promised by the backend
  migration table but not copied.
- `apps/server/tests/fake_native_acp_peer_hd002.mjs` fixture of the migrated
  `test_native_cli_hd002.py` dropped (test remains an inherited red on both
  sides; restoration is for tree completeness).

False positives clarified: 10 `EXCLUDED-round1-qa__*_EXCLUDED-ROUND1-QA.py`
renames are registered in the backend table §4; `conftest.py` exists ×5 in
main (multi-package conftest split).

Defect found → fixed in `c0ff0479e07b`: the vendored bridge binary
`acp-adapter-round-h` (7.4 MB, tracked in the upstream acp-adapter repo as
build evidence) entered the tree with the vendored source. Removed from the
tree; preserved in `archive/acp-adapter` and byte-reproducible via the
packaging script.

## 2. History reachability — PASS (1 gap found and fixed)

- 594 archive refs + 3 reference refs. Counts by repo-key: agent-box 203,
  desktop-next 145, studio 219, control 3 (after fix), acp-adapter 18,
  profile/provider/workboard 2/3/2.
- Key SHAs reachable: a0b343e0 / 450944bd / 41d9d94 / e2ab7409 ✓;
  `main` descends from remote main `6c14ea8d` ✓; reference/* = e08fa034 /
  92a2d2ba / 8dce2c02 ✓.
- Gap found & fixed: control checkpoint `4fc80571` lived only in the
  checkpoint bundle; imported to `refs/archive/control/checkpoint-bundle/heads/checkpoint/2026-09-25`.

## 3. Old-path dependencies — PASS

Full-tree scan for `/home/maoqh/projects/agent-box`, `ordessa/worktrees`,
`ordessa-builds`: exactly 2 hits, both overridable GOROOT/GO defaults in the
two bridge build scripts (`${GOROOT:-/home/maoqh/ordessa-builds/go1.24.13}`),
matching the documented toolchain pin. Exact `import agent_box` = 0;
`products/agent-desktop` = 0; old desktop path refs = 0 outside the two
dated history docs registered by the desktop table §4.

## 4. Claim verification — PASS (1 composition correction)

Evidence-scope note (2026-09-26): `verify-clean.sh` is a **count** gate; run6's 17/0
proves clean-env executability + ledger-count equality. The "zero unexplained new red
**IDs**" claim below rests on the separate per-ID normalized diffs (migration-time
`new-only.txt` analysis + `run6-server-red-ids.txt` dumped in the run6 environment),
not on run6. The two evidences are cited separately throughout the docs.

- Red-ledger independence check from raw logs (not the agent's summary):
  baseline 117 normalized red ids; new-tree server suite 66 red ids; 59 in
  the baseline set + 7 scope-missing (placement ×4, asset_hubs probe ×1,
  wire_v1 ×1, sidecar_native_driver ×1). **Zero unexplained new reds.**
  (Correction: the backend agent's summary said "placement ×5"; the true
  composition includes the asset_hubs probe test. Registered in
  docs/known-issues.md.)
- pacthold 238P/0F, harness 308P/2F(inherited, first two entries of the
  baseline red ledger), acp_orchestration 40P/18F(=worker-entry ruling) —
  all match the raw logs.
- Desktop 146+13+79 and smoke results re-verified by the lead twice
  (candidate repo and clean clone).
- Bridge byte-identity reproduced by the lead from the candidate tree
  (`5fd6a37b…bbc61ea`) — clean-clone script re-run in flight.
- Every command path cited in README/docs/baseline.md exists in the tree
  (spot-checked: packaging/acp-adapter/build-acp-adapter-round-h.sh,
  tooling/dev/start-server.sh, tooling/checks/artifact_presence.py).
- Console scripts: `pacthold` entry kept; `agent-box*` aliases absent from
  packages/pacthold/pyproject.toml, as the table claims.

## 5. Secrets — PASS

- Value-shaped credential scan over the HEAD tree and recent commits: 0 hits.
- `.c1-001-*` mentions: 4, all documentation path-registry entries (never
  contents). Commit messages checked: no credential content.

## 6. Repo hygiene — PASS (after binary fix)

- No nested `.git`, no `node_modules/`, `dist/`, `__pycache__`, `.egg-info`,
  `.venv` in the HEAD tree.
- Files >1 MB: `docs/assets/acp-adapter.png` (1.4 MB, upstream-committed
  documentation asset, kept) — binary removed per §1.

## Verdict

**Superseded verdict — external review corrections (2026-09-25 late).** The
user-side reviewer accepted the fsck/repack/ignore/clean-status items but
correctly rejected the "no open items" claim: (1) run3's backend suites
other than pacthold never executed (collection interruptions) yet the script
counted 9/0 — fake green; (2) plain clones do not carry archive/reference
refs; (3) the switch plan still had either/or wording; (4) /live is not a
controlled ACP main-chain; the 7 scope reds needed per-item rulings; (5)
docs/ignores gaps. Dispositions: verify script rewritten strict (v2) and
rerun (`verify-clean-run4.log` — authoritative); restore loop demonstrated
and documented in `docs/reference-index.md`; switch plan §3/§4 rewritten as a
single deterministic procedure with USER GATEs; per-item rulings in
`docs/known-issues.md`; lockfile + dev extras + env-exception ignores + bash
invocations fixed; no-model handshake evidence added. Switch and publish
remain gated on user confirmation.
