# BUILD-TEST — backend migration candidate (`ordessa-migration/backend/tree/`)

Date: 2026-09-25. All commands run inside `ordessa-migration/backend/`.
No real model API was called anywhere in this verification (fake/controlled
tests only; the real-model chain is explicitly listed as untested in §7).

## 1. Environment

| Item | Version |
| --- | --- |
| Python (uv-managed CPython, all venvs) | 3.12.14 |
| venv baseline (frozen-tree measurement) | `backend/.venv-baseline` (pytest, fastapi, uvicorn, wsproto, pydantic, httpx, pyyaml, jsonschema) |
| venv candidate (new-tree verification) | `backend/.venv` (same deps via editable installs) |
| Go (bridge toolchain, pinned) | go1.24.13 linux/amd64 (`/home/maoqh/ordessa-builds/go1.24.13`) |
| Node (mjs harness tests) | v22.22.1 |
| OS | Linux x86-64 |

Note: system python is 3.14 without ensurepip; venvs were created with
`uv venv --python 3.12`. The starlette TestClient additionally needs `httpx`
(the bc-native Windows lockfile does not list it; the Windows closure was not
re-validated here — carried lockfile noted in MIGRATION-TABLE.md).

## 2. Install / import / entry points (gate: 干净检出)

```bash
uv venv --python 3.12 .venv
uv pip install -e tree/packages/pacthold -e tree/plugins/harness -e tree/apps/server \
                pytest httpx pyyaml jsonschema
.venv/bin/python -c "import pacthold, ordessa_server, pacthold.harness_kit"
#  → imports OK: 2.0.0a1 ordessa_server pacthold.harness_kit
.venv/bin/python -c "from importlib.metadata import version; print(version('pacthold'), version('ordessa-server'), version('ordessa-harness'))"
#  → 2.0.0a1 2.0.0a1 2.0.0a1
.venv/bin/pacthold --help   # console script works (display name updated)
```

`python -m ordessa_server --data-root <dir> --port <p>` verified by the smoke
test in §6. Renaming completeness: `grep -rn "from agent_box\|import agent_box"`
over active `src/` returns only the four documented retired-plugin dependency
points (see MIGRATION-TABLE.md §6), no `agent_box`/`agent_box_harness` module
imports remain in active code.

## 3. Baseline measurement (frozen tree, for red classification)

To separate inherited reds from migration damage, the frozen tree itself was
extracted to `src-tree/` (git archive of `a0b343e0`), given a local scratch
git commit (so `git status`-based tests behave), and run with all ten plugin
`src/` dirs on `PYTHONPATH` — i.e. the retired plugins WERE importable there.

```bash
cd src-tree && PYTHONPATH=src:plugins/*/src ../.venv-baseline/bin/python -m pytest \
  tests plugins/agent-box-harness/tests -q --continue-on-collection-errors
# → 97 failed, 1755 passed, 44 skipped, 25 errors   (baseline-pytest.log)
# → tests/acp_orchestration: exactly 18 failed / 40 passed (documented inherited red)
```

Root causes of the frozen-tree reds: the retired `worker-entry.mjs` (the
harness plugin removed it; every sidecar-bundle build fails on
`runtime/worker-entry.mjs` missing — this is the same "worker-entry 退役既定
红灯" family as the acp_orchestration 18F), plus the round-1 gate/doc artifacts
that reference each other.

## 4. Candidate tree results (all numbers from final runs)

| Suite | Command (from `tree/`, repo-root cwd) | Result |
| --- | --- | --- |
| `packages/pacthold/tests` | `python -m pytest packages/pacthold/tests -q` | **238 passed, 0 failed, 0 skipped** — `VERDICT=GREEN_NO_SKIPS` |
| `plugins/harness/tests` (.py) | `python -m pytest plugins/harness/tests -q` | **308 passed, 2 failed, 3 skipped** |
| `apps/server/tests` | `python -m pytest apps/server/tests -q --continue-on-collection-errors` | **782 passed, 44 failed, 10 skipped, 25 errors** |
| `tests/acp_orchestration` | `python -m pytest tests/acp_orchestration -q --continue-on-collection-errors` | **40 passed, 18 failed** — identical to the documented inherited red |
| harness mjs (node:test) | carried, not run this round (see §7) | — |

### 4.1 harness suite — 2 failed = inherited red (not migration damage)

`tests/install/test_acp_schema_drift_target.py::test_the_acp_schema_a_closure_carries_satisfies_the_adapter_that_needs_it`
and `::test_a_root_override_of_the_schema_does_not_violate_a_declaration_in_the_closure`.
The frozen tree fails these identically (pi packaging lock resolves
`@agentclientprotocol/sdk@1.3.0` while `@automatalabs/pi-acp@0.5.0` declares
`1.4.0`). Same tests, same assertion, red on both sides of the migration.

### 4.2 server suite ledger — every failure classified

Final: 69 red (44 failed + 25 errors) = **62 inherited + 7 scope-missing**. No
unexplained new failure remains.

**(a) Inherited — 62 items red at the frozen commit with the same test id**
(`comm -12` of per-test red sets; lists in `baseline-red.txt` vs
`pytest-server.log`). Root cause families, unchanged by the migration:
- worker-entry retirement: sidecar bundle builds fail on the removed
  `runtime/worker-entry.mjs` (`test_deployment_credentials` 11F,
  `test_import_asset_request_id_129` 10F/E subset, `test_sidecar_native_driver`,
  `test_sidecar_upstream_cause_150`, `test_subagent_harness_round_086` 2E, …);
- sandbox-bwrap scope (conftest pins `AGENT_BOX_SANDBOX_MODULE`): partial reds
  in `test_shared_session_store`-family files that were carried;
- round-1 chain reds already present in the frozen tree (`test_wire_error_family_101`,
  `test_native_cli_hd002`, `test_cancel_recall_flake_087`, `test_accounts`, …).

**(b) Scope-missing — 7 items green at the frozen commit, red in the candidate
because the retired plugins are not importable there** (the baseline env had
them on PYTHONPATH). These are *explained* new reds caused by the decided
scope ("其余 9 插件不进 main"), not by migration damage:
- `test_placement.py` (5): composition tests resolving the sandbox/WSL
  providers (`agent_box_sandbox_bwrap`, worker client) — including
  `test_a_wsl_turn_still_routes_to_the_worker_from_a_windows_host`.
- `test_wire_v1.py::test_unavailable_capabilities_carry_a_reason`: asserts
  `workspaces.open` support "whenever this host can run the sandbox room";
  capability follows composition, composition lacks bwrap → refused.
- `test_sidecar_native_driver.py::test_the_bundle_carries_the_driver_seam_module`:
  bundle build hits the removed `worker-entry.mjs` (worker-entry family, but
  this one passed in baseline because the bundle code path differs when the
  retired modules import cleanly).
Decision needed from the lead: either accept these as documented scope reds in
main, or move these files next to the retired plugins when those return as
`plugins/<name>`.

**(c) Fixed during this round — were new reds in intermediate runs; each fix is
a mechanical migration correction (before → after):**
- `test_usage_aggregate.py` — `from ..storage.database import …` (escaping
  relative import after the server/core split) → `from pacthold.storage.database import …`. ERROR → passed.
- `test_environment_providers.py` (22 tests) — `ssh_connector` imported
  `agent_box_runtime_wsl` at module level; module now lazy-guards it (same
  pattern as `local_channel.py`): manifest/path/identity validation and the
  typed refusals keep working without the distribution; `WorkerClient`
  construction refuses naming the missing package. ERROR → 22 passed.
- `test_asset_hubs.py` (fixtures path) — `tests/server/fixtures` →
  `apps/server/tests/fixtures`; the mcp-probe test now passes; the other 3 in
  the file are inherited (worker-entry, see (a)).
- `test_config_describe_slots_125.py` — read `tests/server/test_wire_v1.py` →
  `apps/server/tests/test_wire_v1.py`. FAILED → passed.
- `test_workspace_connection_reserved_145.py` — path remap collision pointed at
  `packages/pacthold/src/pacthold/server/...` → corrected to
  `apps/server/src/ordessa_server/execution/sidecar_backend.py`. FAILED → passed.
- harness: production-template tests and `test_hermes/opencode/pi_production_template`
  + `test_packaging_boundaries` (path remaps to `plugins/harness`,
  `packaging/builders/`), `model-validation-42d.mjs` repoint (5 FAILED → passed),
  `test_core_boundaries`/`test_single_distribution`/`test_core_identity`/
  `test_family_dialect_tables` rewritten to pin the new single-name invariants
  (their old assertions pinned the retired alias-shim machinery). 21F → 2F(inherited).
- `test_brand_rename.py` — superseded guard rewritten (see MIGRATION-TABLE.md
  §3 last row); its replacement tests pass.

**(d) Excluded from the carried set — 25 files, not collected, content
preserved as `apps/server/tests/EXCLUDED-round1-qa__*.py`** plus the 15 import-level
drops listed in MIGRATION-TABLE.md §4. Their subjects (round-1 gate scripts,
round-1 docs artifacts, retired plugins, `protocols/worker` goldens) are not in
main; running them in main would red on missing subjects, which is a scope
fact, not a regression. Restore paths are in the archive refs.

## 5. Bridge rebuild (gate: 版本证据)

```bash
GOROOT=/home/maoqh/ordessa-builds/go1.24.13 \
  bash tree/plugins/harness/packaging/acp-adapter/build-acp-adapter-round-h.sh /tmp/acp-adapter-rebuilt
# go version go1.24.13 linux/amd64
# 5fd6a37b127274eef5c2f27fe731a720e32e9bd64efd6df23e61fe739bbc61ea  /tmp/acp-adapter-rebuilt
```

| Artifact | sha256 |
| --- | --- |
| Reference (round-h bridge, `/home/maoqh/ordessa-builds/acp-adapter/acp-adapter-round-h`) | `5fd6a37b127274eef5c2f27fe731a720e32e9bd64efd6df23e61fe739bbc61ea` |
| Rebuilt from vendored `tree/plugins/harness/adapters/acp-adapter` | `5fd6a37b127274eef5c2f27fe731a720e32e9bd64efd6df23e61fe739bbc61ea` |

Byte-for-byte identical. Build command: `CGO_ENABLED=0 go build -trimpath
-buildvcs=false -ldflags "-buildid=" ./cmd/acp`, `GOPROXY=off` (no third-party
Go deps), toolchain Go 1.24.13 (pin sha of the toolchain tarball recorded in
`packaging/acp-adapter/README.md`). No new binary was committed anywhere; the
rebuilt artifact lived in `/tmp` only. The older bc-native
`runtime/tools/acp-adapter/` copies (`7a727bdb…` v0.3.8 / `00c48c3a…` r11) are
historical artifacts of other rounds and are intentionally not reproduced.

## 6. Server smoke (gate: 干净检出 / 启动)

```bash
PATH="$PWD/.venv/bin:$PATH" tree/scripts/start-server.sh 25917
# AGENT_BOX_HOME=/tmp/ordessa-server-smoke.8ZiNrh/data-root
# starting ordessa_server on 127.0.0.1:25917
curl http://127.0.0.1:25917/live     # → HTTP 200 {"status":"alive"}
kill -TERM <server pid>              # → port closed, process gone (clean exit)
```

Loopback bind only (`127.0.0.1`, hardcoded in `__main__`), throwaway data-root
under `/tmp` created/owned by the server, no real data root touched, no model
contact, no protected port used; the process was terminated and verified gone
before finishing. (`/live` is the app's built-in liveness route,
`ordessa_server/transport/http/app.py`.)

## 7. Untested / not run, with reasons

- **Real-model chain**: never invoked. Pi/codex/claude real-CLI launches, live
  two-turn gates, credential-bearing deployments — untested (forbidden this
  round; contract §5.5). The no-model `handshake-check.py` for the bridge is
  carried but was not re-run (needs the pinned Pi bundle; the bridge identity
  is pinned byte-for-byte instead).
- **Node mjs harness tests** (`plugins/harness/tests/**/*.test.mjs`,
  `packaging/builders/*.test.mjs`): carried unchanged (relative-path based);
  not executed in this round — they drive the access-entry/harness runtime and
  are the natural next verification step, offline but time-intensive.
- **npm closure builders** (`build-*-runtime-artifact.mjs` real builds): need
  network npm installs; only their unit tests and the pure-path changes were
  verified. Digest agreement goes through `pacthold.resource_contracts.runtime_artifacts`
  (import repointed from the retired bwrap re-export).
- **Windows / WSL legs**: out of environment (Linux only). The Windows server
  lockfile was carried but not re-validated.
- **Independent plugin repos** (Profile/Provider/Workboard) and the running
  hd004b leg (pid 381142): untouched, per contract.

## 8. Reproduce

```bash
cd /home/maoqh/projects/ordessa-migration/backend
.venv/bin/python -m pytest tree/packages/pacthold/tests -q            # 238P
cd tree && ../.venv/bin/python -m pytest plugins/harness/tests -q     # 308P/2F
../.venv/bin/python -m pytest apps/server/tests -q --continue-on-collection-errors
../.venv/bin/python -m pytest tests/acp_orchestration -q --continue-on-collection-errors  # 40P/18F inherited
```

Raw logs kept in `backend/`: `baseline-pytest.log`, `pytest-pacthold.log`,
`pytest-harness.log`, `pytest-server.log`, `pytest-acp.log`,
`baseline-red.txt` (frozen-tree red list).
