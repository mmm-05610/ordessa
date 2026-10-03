# wheel_check — specs/010-platform-core T011 bare-wheel core verification

Purpose (SC-001 / SC-004): prove the packaged `pacthold` wheel runs the core
standalone in a **second pristine venv** that contains nothing but the wheel +
pytest — no `pacthold-runtime-compat`, no `ordessa_*` — and that a brand-new
provider can be onboarded through `pacthold.public` with **zero source
modification**.

All evidence below was produced on worktree HEAD `6e7da6af10` (branch
`codex/010-platform-pacthold`), Python 3.12.14.

## Files

| file | role |
| --- | --- |
| `import_scan.py` | evidence-two runner: `pkgutil.walk_packages` import of every pacthold module + `pacthold_runtime_compat` absence counterexample |
| `example_new_provider.py` | SC-001 demo: new resource + execution provider, full stage/commit/submit/query/replay/request_stop/close lifecycle on a tmp store; AST self-check pins its import surface to `pacthold.public` + stdlib |
| `test_t011_bare_semantics.py` | SC-004 counterexamples rerun in the bare env (see overlap note below) |

Repo-side guard (one file, outside this dir): `../test_t011_wheel_check_guard.py`.

## How to reproduce (commands + exit codes actually observed)

1. Build wheel (repo `.venv`):
   `.venv/bin/python -m pip wheel --no-deps -w /tmp/a-t011-wheelhouse packages/pacthold`
   → `pacthold-2.0.0a1-py3-none-any.whl`, exit 0. No extra build deps had to be
   installed: `.venv` already satisfied the `setuptools>=61,<77` build backend
   (pip used its normal isolated build environment).
   `pytest` was fetched once for the wheelhouse with
   `.venv/bin/python -m pip download -d /tmp/a-t011-wheelhouse pytest`
   (network use registered here; wheels pinned in `/tmp/a-t011-wheelhouse`).
2. Bare venv #2 (real isolation, outside the repo):
   `python3.12 -m venv /tmp/a-t011-venv && /tmp/a-t011-venv/bin/python -m pip install --no-index --find-links /tmp/a-t011-wheelhouse pacthold pytest` → exit 0.
3. Evidence one (absence): `/tmp/a-t011-installed.txt` —
   `pip list --format=freeze` shows only pip + iniconfig/packaging/pluggy/pygments/pytest + `pacthold==2.0.0a1`.
   No `pacthold-runtime-compat`, no `ordessa_*`. `pacthold.__file__` resolves under
   `/tmp/a-t011-venv/lib/python3.12/site-packages/` (not the repo src).
4. Evidence two (full-module import):
   `/tmp/a-t011-venv/bin/python packages/pacthold/tests/platform/wheel_check/import_scan.py`
   → `/tmp/a-t011-imports.txt`: 41/41 modules OK, 0 failures,
   `pacthold_runtime_compat` import raises `ModuleNotFoundError` (absence guard),
   `VERDICT: GREEN`, exit 0.
5. Bare suite run: see exclusion list below → `/tmp/a-t011-junit.xml`, exit 0.
6. SC-001 demo:
   `/tmp/a-t011-venv/bin/python packages/pacthold/tests/platform/wheel_check/example_new_provider.py`
   → `/tmp/a-t011-sc001.txt`: stage/commit/submit/query/replay/request_stop/close
   all OK, `VERDICT: SC-001 DEMO GREEN`, exit 0. Counter-proof that no src was
   touched: the demo files are untracked additions and `git diff --stat`
   (HEAD vs worktree) is empty.

## Exclusion list for the bare run (step 5)

First bare run (no exclusions):
`/tmp/a-t011-venv/bin/python -m pytest packages/pacthold -q` (from repo root)
→ **1 failed, 202 passed**, exit 1. The only red file:

- `packages/pacthold/tests/platform/test_t009_bare_core_imports.py`
  (whole file excluded via `--ignore`; the red ID is
  `test_tripwire_planted_compat_dependency_turns_the_scan_red`)

Reason (environment-layout limitation, not a core defect — tests were NOT
silenced or weakened): the tripwire self-test plants a probe module into the
repo `src/pacthold/` tree and expects the scan's child interpreter to import
`pacthold` **from src** (editable-install layout). In the bare wheel install,
`sys.executable` resolves the site-packages copy, so the planted probe is
outside the walked package and the counterexample cannot be seen. Under the
repo `.venv` (editable install) the same file is green:
`.venv/bin/python -m pytest packages/pacthold/tests/platform/test_t009_bare_core_imports.py -q`
→ **3 passed**, exit 0 (G1/.venv evidence, re-run on this HEAD).
The bare-environment semantics that file guards (all modules import without
the assembly; compat absent) are independently proven here by step 4
(`/tmp/a-t011-imports.txt`) against the *installed wheel*.

Final bare run with the explicit exclusion:
`/tmp/a-t011-venv/bin/python -m pytest packages/pacthold -q --ignore=packages/pacthold/tests/platform/test_t009_bare_core_imports.py --junitxml=/tmp/a-t011-junit.xml`
→ **207 passed / 0 failed / 0 skipped, exit 0** (junit: `tests="207" failures="0" errors="0" skipped="0"`;
includes the 3 wheel_check SC-004 IDs and the 4 repo-guard IDs).
`test_t009_sql_seal.py`, `test_t009_direction_guard.py`,
`test_t009_migration_namespaces.py` also read repo files (plugins/, migrations)
but pass in the bare env because the repo worktree is on disk while pytest runs
from the repo root — no exclusion needed. The repo `.venv` gate stays green
with the new files: `.venv/bin/python -m pytest packages/pacthold -q` →
**210 passed**, exit 0 (bare_core_imports 3 IDs included there).

## SC-004 overlap note

`test_t011_bare_semantics.py` reruns three platform-suite semantics in the
bare wheel env — same-key replay without a second start, unknown receipt
never auto-retried nor released, restart spawn tripwire. The step-5 suite run
collects this directory, so these IDs also appear in `/tmp/a-t011-junit.xml`
(intentional targeted evidence inside the same green run; they mirror
`test_us1_operations_idempotency.py` / `test_us1_recovery_negatives.py`
IDs which are likewise green in the same run).
