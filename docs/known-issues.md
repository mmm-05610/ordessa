# Known issues and untested scope

Baseline carries registered issues — establishing the baseline did not wait for
them. Nothing here is hidden; nothing here was "fixed" by deleting assertions
or skipping tests. Inherited = already red/absent in the frozen source
candidates; New = introduced by the migration (each has a disposition).

## Backend

| Issue | Class | Evidence / disposition |
| --- | --- | --- |
| `tests/acp_orchestration` suite reds (worker-entry retirement; 18 failed / 40 passed at closeout) | Inherited | hd004 ruling: do **not** revive compat chains to green them; kept visible |
| `plugins/harness/tests/install/test_acp_schema_drift_target.py` — 2 failures (npm closure: `@agentclientprotocol/sdk` override vs `@automatalabs/pi-acp` declaration) | Inherited (first 2 entries of the baseline red ledger) | dependency drift in the original tree; not touched by migration |
| server-suite red ledger (see `docs/migration/backend-build-test.md`): 782 passed / 44 failed / 25 errors — 59 inherited (same test id red in the frozen baseline, mostly worker-entry retirement / sidecar chain) + **7 scope-missing flagged at migration time, ruled per item below (item 5 subsequently green under the verified closure; 6 remain)** | Inherited + documented | the frozen bc-native baseline itself was 97 failed + 25 errors / 1755 passed; zero unexplained new reds (lead-verified from raw logs) |
| `apps/server/src/ordessa_server/bootstrap/runtime.py` `start()`/`stop()` still reach Core internals (`from pacthold.work_core import db as core_db` at :258/:262/:291, `configure_database(path)` + `get_conn()`) instead of an instance-level Store | **Unblocked 2026-09-27, still open in this tree (specs/010 B lane, T014-S1c)** | Measured, not argued: the current tree's `pacthold/work_core/repository.py::CoreRepository` takes no store and calls `db.get_conn()` on every method, and a live product path uses it (`plugins/server-compat/.../execution/sidecar_backend.py:201` wires `CoreRepository()` into `WorkService`/`ExecutionService`). Removing the host's configure pin turns exactly one previously-green ID red — `test_stage_a_server.py::test_core_uses_the_server_owned_database_file`, whose `PRAGMA database_list` resolves to a foreign `AGENT_BOX_HOME` db file, i.e. the test is reporting a real mis-binding; that ID is to be re-pointed at the instance store as part of the fix, **not** left red and not counted as inherited. Status change: the blocker is lifted — A published `Implementation checkpoint SHA b47b6d78038a7ecabda551b43c18735d32bed012` at `specs/010-platform-core/reports/A.md:8` (lane `codex/010-platform-pacthold` self-declared IMPLEMENTATION_REVIEW_READY), whose `pacthold.public.CoreStore` is a *self-owned, path-based* store (`core/store.py:32`, `sqlite3.connect(path, timeout=10.0, check_same_thread=False)`) with **no connection-injection seam**. So S1c is no longer "wait for A to make it injectable": it is a composition decision about which file Core owns (its own data-root file vs the legacy store's file, where the host's in-process write lock would no longer serialise Core's second connection), and it must be landed together with T015 and the `核心实例` two-instance counterexample. No shim, no fallback added; the reach stays visible until the merge and S1c land |
| Ordessa Server (`apps/server`) originally imported `pacthold_runtime_compat` at module scope | **Fixed in C0 branch, pending final foundation publication** | B's T016 isolated venv showed `ModuleNotFoundError` without compat. C0 `be53b8d77e` removed the module-scope imports; `526d1f9521` injects storage through the selected product's public composition. A fresh host-only venv containing Pacthold/Server API/Server wheels imports 25/25 modules and starts/hellos/stops an explicit neutral bare host (`apps/server/tests/install/check_bare_host_wheel.py`, `BARE_HOST_WHEEL_OK`, exit 0). No shim or fake module was used. The former B evidence remains the regression baseline. |
| Historical data root without a registered legacy migration provider was served silently | **Fixed in C0 branch, pending final foundation publication** | B's T023 scratch-root reproduction found a stale `[1..5]` schema with an upgraded product marker. C0 `80603a81dc` refuses before marker/lock/token/schema writes, preserves the synthetic DB bytes and rejects symlink paths before read. `526d1f9521` keeps the historical preflight before borrowing the installed product's database type for an explicit bare host. The default product registers the complete source and the positive synthetic root converges. No real user data was opened. |

**Scope-missing reds — per-item ruling (lead, 2026-09-25).** These were green
in the frozen baseline only because the baseline environment could import the
9 retired plugins; on the migrated tree the missing module surfaces as a typed
refusal or error. None is masked by a skip; none may be greened by fakes.

| # | Test (tests/server/… at baseline; apps/server/tests/… here) | Green at baseline because | Red here because | Ruling |
| --- | --- | --- | --- | --- |
| 1 | `test_placement.py::test_a_local_workspace_runs_through_the_local_channel` | local channel executes through `agent-box-sandbox-bwrap` (retired) | sandbox module unimportable → typed refusal | accept as scope-red; re-wire when sandbox returns under `plugins/<name>` |
| 2 | `test_placement.py::test_a_wsl_turn_still_routes_to_the_worker_from_a_windows_host` | WSL channel via `agent-box-runtime-wsl` (retired) | connector lazily refused (dist absent) | accept; re-wire with the WSL leg |
| 3 | `test_placement.py::test_the_placement_picks_the_channel_through_the_product_path` | product-path placement resolves the full channel set (bwrap/WSL importable) | resolution errors on missing dists | accept; re-wire with owning plugins |
| 4 | `test_placement.py::test_the_ssh_placement_runs_on_its_own_connector` | SSH worker client importable from the retired worker chain | `ssh_connector` converted to lazy typed refusal naming the missing dist | accept; re-wire when the SSH/worker lane returns |
| 5 | `test_asset_hubs.py::test_the_mcp_probe_answers_bounded_and_types_every_failure` | assets skill hub resolves through `agent-box-skills` (retired) | hub path hits missing dist | **updated 2026-09-25 late**: green (standalone and in-suite) under the verified closure lockfile in the clean-checkout rerun — the red in the migration agent's 22:03 run was environment/order-sensitive (cause not fully isolated; both observations recorded). No longer counted red; kept on watch as state-sensitive |
| 6 | `test_sidecar_native_driver.py::test_deployment_carries_a_declared_driver_module_into_the_reviewed_bundle` | sidecar deployment bundles exist (retired worker chain) | bundle fixture absent from main | accept; re-wire with the worker/sidecar lane |
| 7 | `test_wire_v1.py::test_unavailable_capabilities_carry_a_reason` | capability view resolves against importable retired plugins | resolution path errors instead of returning typed-unavailable | accept; revisit when any owning plugin returns — the typed-unavailable contract is worth keeping exercised |

| 10 `EXCLUDED-round1-qa__*.py` files in `apps/server/tests/` | Retained, not collected | their subjects (server-round1 QA gate scripts, docs evidence) did not enter main; kept as discoverable markers of the retired QA line — archive refs hold their subjects (lead ruling) |
| lazy dependency points on retired plugins: `ssh_connector` (typed refusal naming the missing dist), `bootstrap.runtime` → `agent_box_runtime_wsl.WslConnector`, `local_channel` → `agent_box_sandbox_windows.job.Job`, `pacthold.cli` → `agent_box_web` | Documented TODO | behaviour preserved (typed refusal / graceful degradation); pyprojects do not declare the missing dists; re-wiring needed if SSH/WSL legs, terminal sessions or the web workbench return |
| stop does not interrupt an in-flight tool turn (end_turn ≠ cancelled) | Inherited, accepted at Round H closeout | design gap registered at CP-SESSION-001 |
| Round H bridge flaky test `TestE2EACPPlanUpdateMappedFromTurnPlanUpdated` (plan-update 2-of-3 failures observed 2026-09-25) | Inherited, flaky | Go-side; not fixed in this migration |

## Desktop

| Issue | Class | Evidence / disposition |
| --- | --- | --- |
| Approval card has no timeout display | Inherited, accepted at Round H closeout | UI debt |
| Input box scrolls out of view (pending confirmation) | Inherited, pending | UI debt |
| `apps/desktop` package name still `@modular/desktop-app` | New (kept deliberately) | internal npm name; rename is cosmetic, deferred (registered in `docs/naming.md`) |
| `act()` stderr warnings in acp-connector rig | Inherited | tests green; warnings only |
| `test:ui-preview` screenshots are not byte-stable | New (C-T029 finding), accepted | Two consecutive runs of identical code changed `02-history.png`, `03-tool-expanded.png`, `06-narrow.png` (and once captured `02-history.png` mid-connector-switch: empty session list + open popover). The gate's DOM assertions (`history.toolCards === 3`, `thinkingCards === 1`, …) passed in both runs, so this is preview-driver capture timing, not a product regression; the committed PNGs are illustrative evidence, the assertions are the authority. Fix = settle-wait before each `shot()` in `apps/desktop/electron/preview-main.ts` |

## Cross-component / environment

| Issue | Class | Notes |
| --- | --- | --- |
| **Real-model end-to-end chain NOT exercised in this baseline** | Untested scope | no model API calls authorised for the migration; controlled Round H acceptance (2026-09-25) is the version-matched evidence: 11/11 gates incl. first-send=1, two turns, approval resolve, dual-restart history recovery (10 msgs ×2), release closed |
| Full GUI acceptance (the two UI debts above) | Untested scope | controlled smoke (electron boot, agent-shell, extension discovery) is green |
| `tests/acp-connector` is a standalone rig with its own lockfile (not a root workspace) | By design | pins `@agentclientprotocol/sdk` 1.5.0 |
| Desktop-repo history tags `v2026.9.11/14/21` + upstream refs not locally recoverable (shallow clone) | History gap | see `docs/reference-index.md`; remote unshallow pending user decision |

## Services (environment registry — do not kill/restart)

| Service | Status (2026-09-25) | Touch? |
| --- | --- | --- |
| hd004b server leg, pid 381142 (bc-native tree, port 57411) + access-entry 394938 + bridge 394946 | running, uses frozen bc-native tree paths | **No** — live user evidence; its tree stays in place until the user retires it |
| qoder sessions pids 36036/66577 (bc-native), 66935 (fc-functional), 273506 (desktop-ui-codex) | idle-but-alive executor sessions | **No** — read-only on their trees |
| Old trial servers 18790 / 18810 | stopped (no listener, 2026-09-25) | n/a |
| `.c1-001-runtime/`, `.c1-001-secrets/`, `runtime/native-pi-user` in the workspace root | run data + credentials (one 64-byte token registered, never read) | **No** — environment exceptions, never enter git |
