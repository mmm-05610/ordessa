# Server core cleanup batch — frozen baseline

Status: frozen 2026-09-26, before any core-cleanup change. Evidence lives in
`.cleanup-evidence/` (raw logs + junit XML). This is the diff anchor for the
batch's red ledger and compatibility claims. Batch 1
(`docs/server-host-baseline.md`, `docs/server-host-batch1-report.md`) is merged
into `main` and is the structure this batch starts from.

## Source identity

| Fact | Value |
| --- | --- |
| Branch base | local `main` at `cb3132da65` ("Merge branch 'feature/server-plugin-host'") |
| Work branch | `feature/server-core-cleanup`, worktree `worktrees/server-plugin-host` (created clean from that main) |
| Untouched reference trees | `/home/maoqh/projects/ordessa` root worktree (frontend session owns `plugins/chat` etc.) and `worktrees/backend-multi-harness-acp` @ `edc0f23a0d` + its uncommitted multi-Harness changes — **byte-for-byte untouched by this batch** |
| Environment | same `.venv` as batch 1 (Python 3.12.14), `ordessa-server-plugin-api` installed editable |

## Test commands and baseline results (re-run on the branch base)

| Suite | Command | Baseline result | Exit |
| --- | --- | --- | --- |
| pacthold | `python -m pytest packages/pacthold -q` | 238 passed, 0 failed | 0 |
| harness | `python -m pytest plugins/harness -q` | 308 passed / 2 failed / 3 skipped | 1 |
| ACP orchestration | `python -m pytest tests/acp_orchestration -q` | 40 passed / 18 failed | 1 |
| server | `python -m pytest apps/server -q` | 812 passed / 43 failed / 10 skipped / 25 errors (68 red IDs, 890 collected) | 1 |

The harness and ACP orchestration red IDs re-run identical to the batch-1
frozen ledger (registered known reds; see `docs/server-host-baseline.md`).
The full per-ID list lives in `.cleanup-evidence/junit-server.xml`; the
end-of-batch diff is computed against it. The inherited red classification
anchor (68 server red IDs = 59 inherited + 7 scope-missing) carries over
unchanged from batch 1.

## Gate rule for this batch

Every entry below names its exact source location today and its cleanup
target. The stage-4 audit must show, per entry: moved, retained (with
justification), or blocked (with the concrete reason). A wire method, route,
CLI behaviour, service construction or storage identifier that appears in none
of the three states blocks the batch — "missing from the table" is gate
failure, exactly as batch 1 froze it.

## wire/1 method inventory (67 methods — re-verified against `_PARAM_SHAPES`/`_ADAPTER_METHODS`, zero divergence)

Source of truth: `apps/server/src/ordessa_server/wire/handlers.py`
(`_PARAM_SHAPES`, `_ADAPTER_METHODS`), the Workspace plugin declarations
(`plugin_host/workspace_plugin.py`), the host (`server.hello` in
`WireService.__init__`). Owner column: who registers the descriptor today.
Target column: who must own it when this batch ends.

| Methods | Source (handler) | Owner today | Target |
| --- | --- | --- | --- |
| `server.hello` (1) | `WireService.hello` | `server.host` (host-registered) | **retained by host** (with its `nativeExecution` facts and `SERVER_NATIVE_IDENTITY_INVALID` refusal — pinned by the inherited 101 red) |
| `workspaces.browse/open/list/archive/gitStatus` (5) | workspace plugin closures | `ordessa.workspace` plugin | **plugins/workspace** (physical move) |
| `acp.channel.open/release` (2) | `WireService.acp_channel_*` | `ordessa.transition-core` | **plugins/harness** server facet |
| `executions.list/get` (2) | `WireService.executions_*` | `ordessa.transition-core` | **plugins/server-compat** |
| `profiles.*` (11) | `WireService.profiles_*` | `ordessa.transition-core` | **plugins/server-compat** |
| `providerModels.*` (6) | `WireService.provider_models_*` | `ordessa.transition-core` | **plugins/server-compat** |
| `assets.*` (11) | `WireService.assets_*` | `ordessa.transition-core` | **plugins/server-compat** |
| `hooks.*` (6) | `WireService.hooks_*` | `ordessa.transition-core` | **plugins/server-compat** |
| `accounts.*` (4) | `WireService.accounts_*` | `ordessa.transition-core` | **plugins/server-compat** |
| `providerArtifacts.*` (3) | `WireService.provider_artifacts_*` | `ordessa.transition-core` | **plugins/server-compat** |
| `usage.aggregate/export` (2) | `WireService.usage_*` | `ordessa.transition-core` | **plugins/server-compat** |
| `config.describe/resolve` (2) | `WireService.config_*` | `ordessa.transition-core` | **plugins/server-compat** |
| `sessions.*` (6) | `WireService.sessions_*` | `ordessa.transition-core` | **plugins/server-compat** |
| `sendOutcome.query` (1) | `WireService.send_outcome_query` | `ordessa.transition-core` | **plugins/server-compat** |
| `queue.get/withdraw` (2) | `WireService.queue_*` | `ordessa.transition-core` | **plugins/server-compat** |
| `runs.stop` (1) | `WireService.runs_stop` | `ordessa.transition-core` | **plugins/server-compat** |
| `approvals.decide` (1) | `WireService.approvals_decide` | `ordessa.transition-core` | **plugins/server-compat** |
| `history.snapshot` (1) | `WireService.history_snapshot` | `ordessa.transition-core` | **plugins/server-compat** |

Total: 1 host + 5 workspace + 2 acp + 59 server-compat = 67. The
`ordessa.transition-core` adapter (id `TRANSITIONAL_ADAPTER_ID`) is **deleted**
in stage 3; every one of its 61 rows must be re-registered by a real plugin —
the only dispatch table remains the plugin host's method registry.

## REST/HTTP route inventory (`transport/http/app.py`)

| Route | Source | Target |
| --- | --- | --- |
| `GET /live` | host transport | **retained** (health check) |
| `POST /wire/v1/{method}` | host transport | **retained** (registry dispatch, auth, envelope) |
| `GET /api/v1/openapi.json` | host transport | **retained** (transport schema surface) |
| `GET /api/v1/readiness` | host transport → `ProductService.readiness()` | **plugins/server-compat** (business readiness facts) |
| `GET /api/v1/wsl/distributions` | host transport → `ProductService.distributions()` | **plugins/workspace** |
| `GET/POST /api/v1/credentials` | host transport → `ProductService.list_credentials/import_credential` | **plugins/server-compat** (credential import flow) |
| `POST /api/v1/connections/probe` | host transport → `ProductService.probe` | **plugins/workspace** |
| `POST /api/v1/connections/browse` | host transport → `ProductService.browse` | **plugins/workspace** |
| `POST/GET /api/v1/workspaces` | host transport → `ProductService.create_workspace` / `ProductRepositoryView.list_workspaces` | **plugins/workspace** |
| `POST/GET /api/v1/profiles` | host transport → `ProductService`/`ProfileService` | **plugins/server-compat** |
| `POST /api/v1/sessions`, `GET /api/v1/sessions/{id}`, `POST .../turns`, `POST /api/v1/turns/{id}/cancel` | host transport → `ProductService` | **plugins/server-compat** |
| `GET /api/v1/sessions/{id}/events` (SSE) | host transport → `repository.list_events` + `notifier` | **plugins/server-compat** |
| `POST /internal/delegation/{token}` | host transport → `DelegationService` | **plugins/server-compat** (order 65C bridge surface) |

## WebSocket route inventory

| Route | Source | Target |
| --- | --- | --- |
| `/wire/v1/event-stream` | host transport, data from `WireService.event_stream_batch` (session events) | route admission + auth **retained by host**; the event source moves behind a port consumed from **plugins/server-compat** (absent plugin ⇒ fail closed) |
| `/wire/v1/acp-channel/{connection_id}` | host transport via `StreamRouteDescriptor` (owner `server.host` — batch-1 retirement fact 5) | route admission + auth **retained by host**; stream-route ownership moves to **plugins/harness** server facet |

## CLI inventory (`__main__.py`, `credential_cli.py`)

| Behaviour | Source | Target |
| --- | --- | --- |
| `ordessa-server --data-root --port` (isolated mode) | `__main__.main` → `build_runtime` | CLI **retained**; the plugin selection it composes comes from the product selection seam (**products/server**) |
| `--execution-mode native --native-harness --native-adapter-command/--native-adapter-arg/--native-continuation --plugin-root` | `__main__.main` → `build_runtime_from_native_adapter` (bootstrap) | CLI args **retained byte-for-byte**; the native composition function moves to **plugins/server-compat** (execution domain) and is selected by **products/server** |
| `--sidecar-deployment --plugin-root --mount` | `__main__.main` → `build_runtime_from_sidecar_deployment` (bootstrap) | same: deployment loader moves to **plugins/server-compat**, selected by **products/server** |
| credential one-shot import CLI | `credential_cli.main` → `build_runtime` + repository writes | **plugins/server-compat** (moves with the credential flow; same arguments, same behaviour) |

## Service construction inventory (`bootstrap/runtime.py`)

| Constructed today in `build_runtime` | Target |
| --- | --- |
| `DataRootOwner`, `_ensure_token`, `Database`, `ObjectStore`, `EventNotifier`, `SecretStore` default, `IdempotentRecords`, `CredentialRecords` | **retained by host** (process/data-root/storage primitives, vended as ports) |
| `_builtin_connector` / `_builtin_ssh_connector` (env-resolved connectors) | **retained by host** (machine bindings → ports); `SshConnector` class moves to **plugins/server-compat** (execution domain), resolved by composition injection |
| `WorkspaceRecords`, `WorkspaceService` | **plugins/workspace** (the plugin constructs its own; retirement fact 2 closes) |
| `ProfileRecords/ProfileService`, `ProviderModelRecords/ProviderModelService`, `SessionRecords/SessionService`, `QueueRecords`, `ApprovalRecords`, `AccountRecords/AccountAssetStore`, `AssetRecords` + skill/mcp/plugin stores + `CatalogStore`, `HookRecords/HookTriggerRecords`, `ArtifactStore`/`UsageAggregator` compositions | **plugins/server-compat** (constructed inside the compat plugin's `build()` from host ports) |
| `ProductService` (pacthold facade), `ProductRepositoryView`, `DelegationService`, delegation tokens | **plugins/server-compat** |
| `WireService` (business ctor args shrink to generic: server-id, codec, registries; `hello`'s harness directory arrives as a composition-injected registry object) | **retained by host** (generic dispatch) |
| plugin host + host ports + `WorkspaceServerPlugin()` + `TransitionCorePlugin(wire)` selection | host keeps the host + ports; the **selection moves to products/server** (batch-1 retirement fact 4 closes); `TransitionCorePlugin` is **deleted** |
| `runtime.start()` business recovery: `mark_workspaces_unverified()`, `recover_interrupted_turns()`, `_import_declared_credentials`, native profile bootstrap | credential import + native profile stay composition-driven (**products/server** passes the facts); workspace/session recovery moves behind a plugin start hook (minimal lifecycle seam) |
| `build_runtime_from_native_adapter` / `build_runtime_from_sidecar_deployment` (incl. AcpChannelRegistry construction + `AccessEntryTransport` launch + stream route registration) | **plugins/server-compat** (deployments/native) and **plugins/harness** (ACP channel registry + launch + stream-route ownership) |

## Storage / on-disk identifiers (unchanged by this batch)

- data-root owner marker `.agentbox-server-root` content `agentbox-server-r1\n`; `server.lock`; `secrets/http-token` (≥32 chars, 0600)
- database schema + migration numbering unchanged (`server_workspaces`, `server_bootstrap`, `server_*` tables, object store layout)
- deployment JSON `schemaVersion: 1` and all field names
- wire method ids, `{id, supported, reason?}` shape, error families, `X-Wire-Version: wire/1`
- module distribution names (`ordessa_server`, `ordessa_harness`, `pacthold`, `ordessa-server-plugin-api`) keep their identifiers; new packages (`ordessa-workspace`, `ordessa-server-compat`, product) are additions, not renames
