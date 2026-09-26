# Server core cleanup batch — IMPLEMENTATION_REVIEW_READY

Status: implemented, tested, committed on `feature/server-core-cleanup`
(worktree `worktrees/server-plugin-host`). Base: local `main` at `cb3132da65`
(the batch-1 plugin-host merge). The multi-Harness work and the frontend
worktrees are byte-for-byte untouched.

## Commit list

| SHA | Stage | Change surface |
| --- | --- | --- |
| `e9823a983b` | Review round 4 | Mounted route SHAPE frozen (auth flag + endpoint signature join path/methods/owner): a re-activation changing either refuses typed (`PLUGIN_HTTP_ROUTE_SHAPE_CHANGED` + `HttpRouteShapeChangedError`); start-failure cleanup attaches to the explicitly passed start error (sys.exc_info() in the inner except named the cleanup exception). 3 new same-App counterexamples |
| `0e09112187` | Review round 3 | The five runtime-lifecycle holes the reviewer reproduced, each pinned red first (8 counterexamples reusing the same App / same runtime): mounted plugin routes follow their owner live (request-time ownership + endpoint resolution; restart mounting at lifespan startup); runtime port facades re-bind per activation round and clear on shutdown; a failed start hook disposes the round before the lock releases; staging-rollback disposal failures accumulate onto the primary conflict's `cleanup_errors`; unmounted-route activation refuses typed (`PLUGIN_HTTP_ROUTE_UNMOUNTED`). Install boundary: no ordessa-harness in the core's requirements, acp_channel alias deleted, packaging + AST import gates |
| `ec79af9fb2` | 0 · Freeze | `docs/server-core-cleanup-baseline.md` (67 wire methods, REST/WS/CLI, service construction, storage identifiers — each with source → owner → cleanup target), fresh per-ID red ledger re-run on the branch base (`.cleanup-evidence/`) |
| `c4cae7d36d` | 1 · Disposal hardening | A throwing disposal never breaks the cleanup: activation rollback stays transactional with the round's own failure primary and disposal failures on its `cleanup_errors`; shutdown disposes every plugin exactly once and raises one typed `CleanupError`; `runtime.stop()` releases the data root even when shutdown raises. 4 new gates (33 total) |
| `3dc57ceac6` | 2 · HTTP route seam | `server_plugin_api.HttpRouteDescriptor` (no transport types), typed `DuplicateHttpRouteError`, host `HttpRouteRegistry` (activation-stage duplicate refusal, owner-scoped unload), transport admission behind the host's bearer auth / loopback policy / error sanitisation, host-route shadowing refused at startup. 5 new gates (38 total) |
| `3e10c9dab3` | 3 · Physical migration | 130 files. Workspace → `plugins/workspace`; ACP channels → `plugins/harness/server_acp`; every remaining domain → `plugins/server-compat`; default selection → `products/server` via the `ordessa.server_product` entry-point seam; transitional adapter deleted; host bootstrap/transport/wire slimmed to the generic core |
| `d13da029a4` | 4 · Audit | 6 gates: bare-host capability surface, `SERVER_PRODUCT_MISSING`/`SERVER_PRODUCT_AMBIGUOUS` fail-closed, missing-dependency refusal, controlled Harness seat with zero host change, host source free of family/brand knowledge |

## What apps/server retains (the post-cleanup core)

- **Process / data root**: `DataRootOwner`, token, `Database`, `ObjectStore`,
  `EventNotifier`, `IdempotentRecords`, `CredentialRecords`, secret-store
  default, machine connectors (`ordessa_server.connectors` for the SSH one;
  the WSL one resolves externally, unchanged) — vended to plugins as ports.
- **Auth transport**: loopback policy, bearer authorization, error walls
  (orders 115/123 semantics), `/live`, `/wire/v1/{method}`, the OpenAPI view,
  the two websocket channels, and the plugin route admission seam
  (`transport/http/admission.py` carries the shared idempotency dependency).
- **Registry dispatch**: the one method registry + stream/HTTP route
  registries in `plugin_host`; `WireService` keeps only `server.hello` and
  the dispatch wall (handlers.py: 2474 → 331 lines).
- **Plugin lifecycle**: activation/unload/shutdown, port vending, dependency
  graph, fail-closed refusals, disposal-exception containment (stage 1).
- **Health**: `/live`.

Host-purity gates: `test_server_compat_boundary.py` (host imports no plugin,
no product, no business alias; plugins import only their declared surface)
and `test_stage4_audit.py::test_the_host_source_carries_no_harness_business_knowledge`.

## Residual business (plugins/server-compat — frozen, only-shrink)

59 wire methods (executions, profiles, providerModels, assets, hooks,
accounts, providerArtifacts, usage, config, sessions, sendOutcome, queue,
runs.stop, approvals.decide, history.snapshot), the business REST routes
(readiness, credentials, profiles, sessions, turns, SSE events, delegation
bridge, turns/cancel), the deployment compositions (native adapter +
sidecar), and startup recovery (credential import, native profile,
interrupted-turn sealing). Pinned by
`test_server_compat_boundary.py::test_the_compat_declaration_is_within_the_frozen_surface`
(only-shrink) — every row names its baseline source in
`docs/server-core-cleanup-baseline.md`.

## Import boundaries (before → after)

Before: bootstrap constructed every business service; `WireService` owned all
59 business handlers; the adapter wrapped the wire; the host imported the
business domains directly.

After:

- host → plugin: **zero** (gate-pinned). The host never imports
  `ordessa_server_compat` / `ordessa_workspace` / `ordessa_harness.server_acp`
  / the product package.
- plugin → host: only the generic vocabulary (`errors`, `records`, `ids`,
  `idempotency` as port objects, `credentials` as a port object, `wire.errors`,
  `wire.envelope`, `wire.projection`, the wire param helpers,
  `transport.http.admission`) plus the public composition seam
  (`bootstrap.build_runtime`) — the same vocabulary `pacthold.service.*`
  already consumed under the pinned transitional edges.
- plugin → plugin: declared dependencies and ports only, with two
  documented edges: compat consumes `workspace.service` / `workspace.records`
  ports (requires `ordessa.workspace`), and the execution domain's native leg
  reuses the workspace domain's `LocalEnvironmentProvider` (one declared,
  gate-listed import). The ACP facet consumes `sessions.records` /
  `profiles.records` ports (requires `ordessa.server-compat`).
- legacy `ordessa_server.{profiles,accounts,assets,hooks,model_configs,
  execution,approvals,workspaces,acp_channel,persistence,usage_aggregate,
  credential_cli}` remain as zero-implementation module-identity aliases
  (M1-P-A① discipline, pinned by `test_server_compat_boundary.py`) so the
  890-test suite keeps its IDs.

## Batch-1 retirement facts — all five closed

1. Workspace code physically in `ordessa_server` → **closed** (`plugins/workspace`).
2. `WorkspaceRecords` constructed by bootstrap → **closed** (plugin constructs its own from ports).
3. `ProductService` composing a second `WorkspaceService` → **closed** (facade composes the plugin's instance via the port).
4. Plugin selection a bootstrap argument with no manifest → **closed** (`products/server` + entry-point seam, fail-closed).
5. ACP stream route under the host owner → **closed** (owner `ordessa.harness.acp`).

## Measured results (all from the worktree, isolated `.venv`)

| Suite | Command | Baseline | Final | Red-ID diff |
| --- | --- | --- | --- | --- |
| pacthold | `pytest packages/pacthold -q` | 238P | 238P | none |
| harness | `pytest plugins/harness -q` | 308P/2F/3S | 308P/2F/3S | identical 2 IDs |
| ACP orchestration | `pytest tests/acp_orchestration -q` | 40P/18F | 40P/18F | identical 18 IDs |
| server | `pytest apps/server -q` | 812P/43F/10S/25E | **844P**/43F/10S/25E | **identical 68 IDs, zero new, zero resolved** |

(+32 gate tests: 4 stage-1, 5 stage-2, 6 compat-boundary, 6 stage-4, 8 review-round-3, 3 review-round-4.)

Environment note: the worktree `.venv` now also installs
`ordessa-workspace`, `ordessa-server-compat` and `ordessa-server-product`
editable (the product composition resolves through the entry point; a venv
without the product answers `SERVER_PRODUCT_MISSING` at startup — fail
closed).

## Model-free default-product smoke (loopback, throwaway data root)

`python -m ordessa_server --data-root <tmp> --port 8933`:

- `GET /live` → 200 `{"status": "alive"}`;
- unauthenticated `POST /wire/v1/server.hello` → **401**;
- authenticated `server.hello` → **67 capabilities** in baseline order
  (`acp.channel.*` now advertise after the compat families instead of between
  `executions.*` and `profiles.*` — the one observable ordering change; no
  contract consumer branches on position, and 097 G1's order-consistency gate
  passes), `harnesses: []` on a fresh root, bearer auth advertised;
- `workspaces.list` (wire) and `GET /api/v1/workspaces` (plugin REST route)
  answer with baseline shapes through the workspace plugin;
- both websocket routes refuse pre-accept (handshake denial) for
  unauthenticated and unauthorized-but-unknown session/connection — fail
  closed at the transport.

## Test adaptations (semantics preserved, each noted honestly)

- 097/098/101/125/129/147: patch targets and source-scan paths follow the
  moved handlers (`ordessa_server_compat.core_wire`); 101's family scan now
  covers both the host dispatch module and the compat handlers module, and
  its inherited red (`SERVER_NATIVE_IDENTITY_INVALID` in host `hello`) stays
  red with the same cause.
- MB-S2a/S2c1 boundary pins: the composition-root assertions follow the
  moved root (`ordessa_server_compat/plugin.py`); the facade's pinned edge
  set swaps `ordessa_server.sessions` for `pacthold.service.sessions` — one
  ordessa_server edge fewer.
- The unload-isolation gate now exercises the dependency guard: unloading
  the workspace plugin while the compat core is active refuses
  (`DependentActiveError`), the consumer unloads first, and the dependency's
  rows survive — the stage-1 round-1 hardening doing its job.
- Startup-recovery order: workspace `mark_all_unverified` now runs before
  the compat core's credential import / native profile (activation order)
  where the baseline ran it after; both steps are idempotent and
  data-independent — recorded as an honest reordering.
- The adapter-string selection idiom (`"ordessa.transition-core"`) died with
  the adapter; explicit selections now pass plugin instances.

## Not verified in this batch

- Real Harness / real-model behaviour: unchanged scope, no model calls.
- Windows/WSL/SSH legs: unchanged (registered scope-reds stay red).
- The Go bridge: untouched, not rebuilt.
- The 3 native fake-peer red IDs fail at the same assertion as the baseline
  (turn `failed` vs `completed` through the retired worker-entry chain);
  their failure text embeds nondeterministic execution ids, so the byte-level
  message differs while the cause family is identical.
- A dual-process restart against this branch has not been run (the
  in-process restart gates cover re-activation).
