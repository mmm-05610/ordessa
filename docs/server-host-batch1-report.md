# Server plugin-host batch 1 — IMPLEMENTATION_REVIEW_READY report

Status: implemented, tested, committed on `feature/server-plugin-host`
(worktree `worktrees/server-plugin-host`). Multi-Harness work is **not**
included; that stays in its own tree for a later, separate batch.

## Review round 1 (2026-09-26): lifecycle hardening

The independent review reproduced three lifecycle holes the first batch's
gates missed. Each was pinned with failing counterexamples first (5 new
tests in `test_plugin_host_gate.py`), then fixed:

1. **Data-root lock leaked on activation failure.** `build_runtime` released
   the lock only around token creation, so a plugin failing to build kept
   the flock (a same-process retry got `DATA_ROOT_IN_USE`); `start()`'s
   re-activation also ran outside its cleanup try. Fixed: activation is
   wrapped with `owner.release()` in `build_runtime`, and re-activation
   moved inside `start()`'s try. Gates:
   `test_activation_failure_releases_the_data_root_lock`,
   `test_reactivation_failure_in_start_releases_the_lock`.
2. **Dependency-provided ports never reached the dependent's context.**
   `context.ports` carried only host ports, so a declared dependency could
   not actually compose its dependent. Fixed: `context.ports` = host
   facades + `provided_ports` of every plugin declared in `requires`
   (topological order guarantees they are active); undeclared plugins see
   nothing — `requires` is the access grant. Contract docstring updated.
   Gate: `test_a_declared_dependency_provides_ports_to_its_dependent`
   (plus the negative boundary assertion).
3. **Lifecycle disposal/isolation gaps.** A plugin whose registration
   failed mid-staging was rolled back but its already-built resources were
   never disposed (build succeeded → disposal owed); and `deactivate(A)`
   silently orphaned `B` when `B.requires` contained A. Fixed: staging
   failure now calls `registration.disposal()` exactly once after rollback;
   unload refuses with a typed `PLUGIN_DEPENDENT_ACTIVE`
   (`server_plugin_api.DependentActiveError`) naming the active dependents —
   reverse-order shutdown disposes dependents first and never trips the
   guard. Gates: `test_method_conflict_disposes_the_plugin_that_already_built`,
   `test_unload_refuses_while_a_declared_dependent_is_active`.

Red ledger after the fixes (same commands, same per-ID comparison):

| Suite | Round 2 | Red-ID diff vs frozen baseline |
| --- | --- | --- |
| pacthold | 238P | none (0→0) |
| harness | 308P/2F/3S | identical 2 IDs |
| ACP orchestration | 40P/18F | identical 18 IDs |
| server | 807P/43F/10S/25E (885 collected, +5 gates) | **identical 68 IDs, zero new, zero resolved** |

## Review round 2 (2026-09-26): the composition cleans up after itself

The independent review reproduced one follow-up gap and flagged one boundary
risk; each is pinned by failing counterexamples first (5 new tests), then
fixed:

1. **A failed round leaked the plugins it had already activated.** With A
   activated and B failing to build, `build_runtime` released the data-root
   lock but never disposed A — the round returns no runtime, so nobody else
   could clean up ("same-root retry succeeds, A's disposal count is 0").
   Fixed: an activation round is now transactional at plugin granularity —
   `activate_all` disposes exactly what *this round* activated, in reverse
   order, before the failure propagates (earlier-round plugins untouched);
   `build_runtime` then releases the lock, and `start()`'s failed
   re-activation round gets the same treatment through the same path.
   Gates: `test_a_failed_composition_disposes_activated_plugins_and_releases_the_root`,
   `test_a_failed_start_round_disposes_activated_plugins_and_releases_the_lock`,
   `test_a_failed_activation_round_is_transactional_for_this_round`.
2. **Provided ports could silently shadow existing bindings.** The
   dependency-port merge used `dict.update`, so a provided port named like a
   host facade (or like another dependency's port) would quietly override
   it. Fixed: the merge refuses with a typed
   `PLUGIN_PORT_CONFLICT` (`server_plugin_api.PortConflictError`) naming the
   consumer, provider and port; the refusal is transactional like any other
   activation failure. Gates:
   `test_a_dependency_port_shadowing_an_existing_binding_refuses_the_composition`,
   `test_port_conflicts_are_refused_between_dependencies_too` (both the
   host-facade shadow and the dependency-to-dependency collision).

Red ledger after the fixes (same commands, same per-ID comparison):

| Suite | Round 3 | Red-ID diff vs frozen baseline |
| --- | --- | --- |
| pacthold | 238P | none (0→0) |
| harness | 308P/2F/3S | identical 2 IDs |
| ACP orchestration | 40P/18F | identical 18 IDs |
| server | 812P/43F/10S/25E (890 collected, +5 gates) | **identical 68 IDs, zero new, zero resolved** |

## Rollback point and source identity

- Branch base: local `main` at `dda84eb49c`; the branch is 9 commits ahead
  (3 batch stages + report, then two review rounds each adding fixes and
  report updates).
- Rollback: `main` is untouched — discard the branch (or revert the 4 commit
  range) to restore the pre-batch Server byte-for-byte.
- Reference tree `worktrees/backend-multi-harness-acp` @ `edc0f23a0d` with its
  uncommitted multi-Harness work: verified untouched (status identical before
  and after this batch); only its `docs/server-plugin-host-plan.md` was copied
  into this branch as a standalone file.

## Commit stages

| SHA | Stage | Change surface |
| --- | --- | --- |
| `5d8e59df8d` | Baseline freeze | `docs/server-host-baseline.md` (SHAs, commands, 67-method inventory, red ledger), plan copy, gitignore |
| `8a70f02054` | Contract | new `packages/server-plugin-api` (`ordessa-server-plugin-api`, module `server_plugin_api`, zero deps): descriptors, context/registration, typed refusals |
| `0d6b3330f0` | Host + Workspace | new `ordessa_server/plugin_host/` (registry, lifecycle, workspace plugin, transition adapter); `wire/handlers.py` registry-backed; bootstrap composition (`server_plugins` selection, ports, restart re-activation); stream route admission in `transport/http/app.py`; `apps/server` dep on the contract |
| `3b5dbcb125` | Gates | new `test_plugin_host_gate.py` (19 tests); order-097/101/129 access points adapted to the registry (semantics unchanged) |
| `ef333cff42` | Report | `docs/server-host-batch1-report.md` (first version) |
| `eee778500a` + `8433d1932e` | Review round 1 | data-root lock released on activation failure (composition + start paths), dependency-provided ports into `context.ports` (`requires` as access grant), disposal on staging failure, `DependentActiveError` on unload under active dependents; 5 gates |
| `1653cefdb8` + `b6908512a3` | Review round 2 | transactional activation rounds (a failed composition or failed start disposes what it activated before the lock is released), `PortConflictError` refusing port shadowing; 5 gates (29 total) |

## Measured results (all runs from the worktree, isolated `.venv`)

| Suite | Command | Baseline | Final | Red-ID diff |
| --- | --- | --- | --- | --- |
| pacthold | `python -m pytest packages/pacthold -q` | 238P | 238P | none (0→0) |
| harness | `python -m pytest plugins/harness -q` | 308P/2F/3S | 308P/2F/3S | identical 2 IDs |
| ACP orchestration | `python -m pytest tests/acp_orchestration -q` | 40P/18F | 40P/18F | identical 18 IDs |
| server | `python -m pytest apps/server -q` | 783P/43F/10S/25E | 802P/43F/10S/25E (+19 gate tests) | **identical 68 IDs, zero new, zero resolved** |

Loopback smoke (`scripts/start-server.sh`): data-root marker
`agentbox-server-r1` unchanged, `/live` answers, unauthenticated wire is
401, `server.hello` returns the 67-row table in baseline order, and
`workspaces.list` / `workspaces.open` answer through the plugin with
baseline shapes and typed shape refusals.

The two inherited server reds that read wire internals fail with their
baseline causes (verified, not assumed): `test_wire_v1::
test_unavailable_capabilities_carry_a_reason` (sandboxless-host capability
rows) and `test_wire_error_family_101::
test_no_wire_error_is_constructed_with_a_non_family_first_argument` (source
scan finding `SERVER_NATIVE_IDENTITY_INVALID`, present at baseline).

## Honest-absence semantics (the one new observable state)

An uncomposed plugin's methods are absent from `server.hello` and dispatch
answers the existing `INVALID_REQUEST "… is not a wire/1 method"` typed
refusal. Present-but-degraded behavior is unchanged: Workspace methods are
declared with `supported:false, reason:LOCAL_SANDBOX_UNAVAILABLE` when the
sandbox probe fails, exactly as the baseline reported them. No default
composition behavior changes (the product selection enables the Workspace
plugin and the adapter).

## Business still behind the transitional adapter

Everything except Workspace and host-owned `server.hello`:
executions.list/get, acp.channel.open/release (+ the acp-channel stream
route, host-owned until the Harness batch), all `profiles.*`,
`providerModels.*`, `assets.*`, `hooks.*`, `accounts.*`,
`providerArtifacts.*`, `usage.*`, `config.*`, `sessions.*`,
`sendOutcome.query`, `queue.*`, `runs.stop`, `approvals.decide`,
`history.snapshot` — declared once in `wire.handlers`
(`_ADAPTER_METHODS`/`_PARAM_SHAPES`), registered as atomic descriptors by
`TransitionCorePlugin`. This is a bridge, not ownership: the baseline doc's
inventory table names each domain's eventual owner.

## Transitional facts to retire in later batches (registered, not hidden)

1. The Workspace plugin's code lives inside `ordessa_server` (interface is
   fully plugin-shaped; physical extraction is a separate test-backed move).
2. `WorkspaceRecords` is still constructed by the bootstrap and vended as a
   scoped port; record ownership has not moved.
3. The `ProductService` facade still composes its own `WorkspaceService`
   instance for the REST routes — a second, equivalent instance over the
   same records.
4. Plugin selection is a bootstrap argument; no manifest file or entry-point
   discovery exists (installing a distribution enables nothing silently).
5. The acp-channel stream route is registered under the host owner.

## Test adaptations (each preserves the gate's semantics)

- 097 G1 reads the registry view and `plugin_host.declared_shapes()`
  (plugin declarations + host-registered rows); the drop-a-method
  counter-example retires `usage.export` on the live registry and the
  declaration divergence stays visible; the no-rule/unknown-id gate now
  pins both sides (`queue.get` → `(True, None)`, unregistered id →
  `(False, "UNKNOWN_METHOD")` + dispatch refusal).
- 101's shape counter-example restores its defect via `amend_shape()` on
  the live registry (originals re-declared in-finally; not monkeypatchable).
- 129's handler counter-example re-binds via `replace_handler()`; **this
  test cannot execute in this tree** (its fixture needs
  `tests/server/fixtures/home_probe_acp_peer.mjs`, an inherited baseline
  error for all 129 wire cases), so that adaptation is review-verified
  only, marked here honestly.
- Registry `unregister` is idempotent for already-removed rows but never
  removes another owner's row.

## Not verified in this batch

- Real Harness/real-model behavior: unchanged scope, no model calls.
- Windows/WSL/SSH legs: unchanged (registered scope-reds stay red).
- The Go bridge: untouched, not rebuilt.
- Restart re-activation is exercised in-process (gate test); a real
  dual-process restart against this branch has not been run.
