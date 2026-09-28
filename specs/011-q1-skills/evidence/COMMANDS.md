# Q1 / T16 package-isolation (G21) — command transcript with TRUE exit codes

Every `EXIT=` below was echoed immediately after the command itself
(never after a pipe/tail). Interpreter: /home/maoqh/.local/bin/python3.12
(CPython 3.12.14, same as docs/baseline.md pin). Repo:
/home/maoqh/projects/ordessa/worktrees/011-q1-skills @ codex/011-q1-skills
(HEAD 54763b34e6 before the test-side conftest edits recorded here).

1. pip download of pinned third-party closure (network/cache path — the
   only step that touched a package index; everything local was built
   from repo dirs and every INSTALL used --no-index --find-links):
   python3.12 -m pip download --no-deps \
       -r apps/server/lockfiles/server-linux-py312.txt -d /tmp/q1-wheelhouse
   -> EXIT=0  (log 01-lockfile-download.log)

2. Wheel build, same shape as foundation.json `commandsAndEvidence`
   ("python3.12 -m pip wheel --no-deps --no-cache-dir …"), from THIS tree:
   python3.12 -m pip wheel --no-deps --no-cache-dir -w /tmp/q1-wheelhouse \
       packages/pacthold plugins/runtime-compat packages/server-plugin-api \
       plugins/assets/skills apps/server plugins/workspace plugins/profile
   -> EXIT=0  "Successfully built pacthold pacthold-runtime-compat
      ordessa-server-plugin-api ordessa-skills ordessa-server
      ordessa-workspace ordessa-profile"  (log 02-local-wheel-build.log)

3. Fresh venv:
   python3.12 -m venv /tmp/q1-isolated-venv
   -> EXIT=0  (log 03-venv-create.log)

4. Pinned closure install, offline:
   /tmp/q1-isolated-venv/bin/python -m pip install --no-index \
       --find-links /tmp/q1-wheelhouse \
       -r apps/server/lockfiles/server-linux-py312.txt
   -> EXIT=0, 29 packages (log 04-lockfile-install.log)

5. Local wheels install, offline (skills pulled pacthold,
   pacthold-runtime-compat, PyYAML, server-plugin-api; [profile] extra
   installed ordessa-profile because the facet tests consume it):
   /tmp/q1-isolated-venv/bin/python -m pip install --no-index \
       --find-links /tmp/q1-wheelhouse \
       'ordessa-skills[profile]==2.0.0a1' ordessa-server==2.0.0a1 \
       ordessa-workspace==2.0.0a1
   -> EXIT=0  "Successfully installed ordessa-profile-2.0.0a1
      ordessa-server-2.0.0a1 ordessa-server-plugin-api-0.1.0
      ordessa-skills-2.0.0a1 ordessa-workspace-2.0.0a1 pacthold-2.0.0a1
      pacthold-runtime-compat-0.1.0"  (log 05-local-wheel-install.log)

6. pip check:
   /tmp/q1-isolated-venv/bin/python -m pip check
   -> EXIT=0  "No broken requirements found."  (log 06-pip-check.log)

7. Import-origin proof (cwd OUTSIDE the repo = /tmp/q1-run):
   /tmp/q1-isolated-venv/bin/python -c "import ordessa_skills,
     pacthold_runtime_compat, server_plugin_api, ordessa_workspace,
     ordessa_server; print(ordessa_skills.__file__)"
   -> EXIT=0  prints
   /tmp/q1-isolated-venv/lib/python3.12/site-packages/ordessa_skills/__init__.py
   (log 07-import-origin.log)

8. In-tree baseline (lead venv, unmodified use, AFTER the conftest
   fallback-guard edits; run from repo root):
   .venv/bin/python -m pytest -q plugins/assets/skills/tests
   -> EXIT=1  "329 passed, 6 errors in 2.83s" — the 6 errors are the
      known-red profile pins (upstream AgentBoxProfileV1 gap)
      (log 08-in-tree-baseline.log)

9. ISOLATED test run — tests from the repo tests dir, every package
   resolved from site-packages, cwd /tmp/q1-run:
   /tmp/q1-isolated-venv/bin/python -m pytest -q \
       /home/maoqh/projects/ordessa/worktrees/011-q1-skills/plugins/assets/skills/tests \
       --junitxml=/tmp/q1-evidence/09-isolated-run-junit.xml
   -> EXIT=1  "329 passed, 6 errors in 2.67s"
      (log 09-isolated-run.log, junit 09-isolated-run-junit.xml)

10. Per-ID parity: the 6 error test IDs extracted from logs 08 and 09
    (basename-normalised) diff clean (a.txt == b.txt, 6 lines each).
    Isolated traceback shows the failing import resolving at
    /tmp/q1-isolated-venv/lib/python3.12/site-packages/ordessa_profile/__init__.py:15
    — same upstream cause (AgentBoxProfileV1 emptied from
    pacthold.resource_contracts by the foundation checkpoint), not an
    isolation artifact. (evidence 10-pip-list.log also proves zero
    editable installs: no direct_url.json references a file:// source.)

## Test-side changes enabling isolation (all inside plugins/assets/skills/**)
- tests/conftest.py: the unconditional repo-src sys.path appends
  (skills/runtime-compat/profile) are now guarded by
  importlib.util.find_spec(<module>) — a repo path is appended ONLY when
  the distribution is not importable, so an installed wheel always wins
  and the in-tree venv keeps its fallback. Behaviour identical in-tree
  (baseline re-run after the edit: same 329+6).
- tests/skills_wire_support.py: same guard for the
  plugins/workspace/src fallback path.
- tests/test_profile_facet_contribution.py: same guard for the
  plugins/profile/src + plugins/runtime-compat/src fallback paths.
No pyproject change was needed (wheel ships src layout via
[tool.setuptools.packages.find]; no package-data gap surfaced).

## Residual repo coupling (registered, not sys.path):
skills_wire_support.frozen_compat_methods() loads
apps/server/tests/test_server_compat_boundary.py by absolute repo path
(deliberate pin-duplication-avoidance, file-load only); test_dependency_direction.py
AST-scans repo source dirs by design. Both work in-tree and would need
those files vendored for a copy-the-tests-elsewhere run; the isolation
claim here is about IMPORTS (site-packages), which is proven.
