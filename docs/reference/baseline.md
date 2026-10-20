# Development baseline · observed 2026-10-09

This nightly implementation uses the currently observed source commit `c5c0e50b08178cbfb52aa5e423d904aa9c5b5145`, from root `codex/nightly-development-20261007`. Its dedicated integration branch is `codex/nightly-restructure-20261009` at `worktree/nightly-restructure-20261009`. The detailed [baseline](../implementation/nightly/baseline.md), [package inventory](../implementation/nightly/evidence/preparation/package-inventory.json) and [source manifest](../implementation/nightly/evidence/preparation/source-manifest.json) bind observations to this source. The preparation commit f3b016bb98 contains documents/design assets only; later nightly changes are implementation checkpoints, described in the current status.

The previous baseline text, including 3ada/747 refs and historical counts, is preserved verbatim in [the archive](../archive/pre-restructure/source/docs/baseline.md). It does not describe the current HEAD.

Observed runtime: root test Python 3.12.14, Node 22.22.1, npm 9.2.0. Go 1.24.13 remains the documented bridge pin; it was not executed in this preparation. The root `.venv` and `node_modules` were preserved. W01 installed an independent `.venv-nightly` with 48 initially enumerated editable distributions (50 after Agent cutover; 49 after records joins that same distribution) from this worktree and a clean pip check; npm ci installed 551 packages without lifecycle scripts. The requirements pin resolved external versions; they are not artifact hash pins. Three local wheels (interfaces, infrastructure, engineering) were built and imported from an isolated target; this does not establish full product delivery.

Current command definitions (not all run): `npm ci`, `npm run typecheck`, `npm run build`, `npm test`, `npm run test:agent-shell`, `npm run test:electron`; the real aggregate is `tooling/checks/test-all.mjs`. The preparation `--list` probe enumerated 45 suites. The current upper-structure caller inventories 53 exact suites (49 case-report suites and four prerequisite gates); formal caller controls pass 11/11, while the full aggregate remains NOT_RUN. The current clean verifier snapshots working-tree source into an owned temporary tree, requires an absolute Python 3.12.14 executable, and records actual case ledgers and supervised process results; its controlled guards pass, while full historical equivalence and clean-tree acceptance remain incomplete. The seven access/relay tests were moved as a whole back to their actual plugin production owner, plugins/harness/tests/access; inherited path/descriptor issues and the earlier timeout are retained in evidence. Discovery success is not suite acceptance. Package-local Python tests derive from each `pyproject.toml`; the complete product editable/wheel/deb closure is unverified for this new tree. Do not use retired aggregate/profile/server-compat install paths.

Preparation verification: design assets 407 static assertions; interfaces 6 schemas, 4 positive and 6 negative cases; existing cross-package test-path guard 3 passed/0 skips. These do not establish new architecture boundaries, real Harness, quality, GUI, migration or product readiness. Root `.venv` lacks jsonschema/referencing; its failed static attempts were retained, then the already available system Python dependencies were used successfully.

No full application build, service launch/restart, user database migration, main merge or push occurred. Real-model authorization was limited here to two small, explicitly free synthetic connectivity calls; [provider evidence](../implementation/nightly/provider-opencode.md) separates connectivity from quality/SDK/Pi/engineering acceptance. [Known issues](./known-issues.md) retain prior failure history; [nightly blockers](../implementation/nightly/blockers.md) records new findings.

## Same-source nightly commands

Run from the dedicated nightly worktree. Use its Python interpreter so imports resolve to changed source:

```bash
.venv-nightly/bin/python -m pip install -r tooling/workspace/nightly-python-requirements.txt
.venv-nightly/bin/python tooling/workspace/python_workspace.py --install
.venv-nightly/bin/python -m pip check
node tooling/checks/test-all.mjs --list
.venv-nightly/bin/python -m pytest -q tests/architecture/test_dependency_boundaries.py
node --test tooling/tests/dependency-boundaries.test.mjs tooling/tests/test-all.test.mjs
.venv-nightly/bin/python tooling/checks/dependency_boundaries.py
node tooling/checks/dependency-boundaries.mjs
```

The two real boundary scans currently fail; do not reinterpret fixture passes as a clean architecture. Current source/evidence and the next actions are in [nightly status](../implementation/nightly/status.md). packages/engineering is the sole Engineering distribution source; the former packages/backend/engineering path is removed. interfaces and infrastructure are installed production-shaped packages, with partial responsibilities explicitly recorded.

Current Engineering material validation remains package-local: `.venv-nightly/bin/python -m pytest -q packages/engineering/tests`. [Source/wheel evidence](../implementation/nightly/evidence/W04/material-checkpoint.md) and [explicit schema6 upgrade](../migration/engineering-schema6-materials.md) supersede earlier partial counts. Default schema2 and all product/runtime acceptance gaps remain.

Current Proposal validation command remains `.venv-nightly/bin/python -m pytest -q packages/engineering/tests`:488 passed/0skip. Installed Engineering wheel repeats the same488 cases. [Proposal receipts](../implementation/nightly/evidence/W04/proposal-checkpoint.md) supersede the earlier material slice for current code; [schema7](../migration/engineering-schema7-proposals.md) is explicit. No product Server/CLI launch command is advertised before actual trusted composition exists.


W10 now selects one InstanceAccessAuthority in the default Server. The instance bearer is a machine identity with no default Engineering grants; original local owner ACLs remain. HTTP/wire/REST/WS share this identity mechanism; missing authority refuses, without the old token fallback. Real SQLite admission/COMMIT, revocation and copied-context negatives are verified. Full production Engineering catalog/receipt, project mapping, CLI and human confirmation remain incomplete. Server now requires Python >=3.12, matching its direct interfaces dependency. See [W10 actual evidence](../implementation/nightly/evidence/W10/README.md).
