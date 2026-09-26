# Server plugin-host batch 1 — frozen baseline

Status: frozen 2026-09-26, before any host-boundary change. Evidence lives in
`.baseline-evidence/` (raw logs + junit XML). This is the diff anchor for the
batch's red ledger and wire-compatibility claims.

## Source identity

| Fact | Value |
| --- | --- |
| Branch base | local `main` at `dda84eb49c` ("Record selective integration of composition phases 1-2 into main") |
| Work branch | `feature/server-plugin-host`, worktree `worktrees/server-plugin-host` (created clean from that main) |
| Reference tree (read-only) | `worktrees/backend-multi-harness-acp` @ `edc0f23a0d` + uncommitted multi-Harness changes — **not** part of this batch; only `docs/server-plugin-host-plan.md` was copied in |
| Plan document | `docs/server-plugin-host-plan.md` (copied verbatim into this branch) |

## Test commands and baseline results

Environment: fresh `worktrees/server-plugin-host/.venv` (Python 3.12.14), installed from
`apps/server/lockfiles/server-linux-py312.txt` + editable `pacthold`, `ordessa_server`,
`ordessa_harness` (+ dev extras). All runs from the worktree root.

| Suite | Command | Baseline result | Exit |
| --- | --- | --- | --- |
| pacthold | `python -m pytest packages/pacthold -q` | 238 passed, 0 failed | 0 |
| harness | `python -m pytest plugins/harness -q` | 308 passed / 2 failed / 3 skipped | 1 |
| ACP orchestration | `python -m pytest tests/acp_orchestration -q` | 40 passed / 18 failed | 1 |
| server | `python -m pytest apps/server -q` | 783 passed / 43 failed / 10 skipped / 25 errors (68 red IDs) | 1 |

Server red classification anchor: 68 red IDs = the migrated-tree inherited
ledger (59 inherited same-id) + the six remaining scope-missing reds
(`docs/known-issues.md` scope table items 1–4, 6, 7). This run matches the
clean-checkout rerun recorded against item 5 (`test_asset_hubs.py::
test_the_mcp_probe_answers_bounded_and_types_every_failure` **green** here,
783P/43F vs the 782P/44F of the migration agent's 22:03 run). The full per-ID
list is `.baseline-evidence/junit-server.xml`; the end-of-batch diff is
computed against it. Notable inherited IDs this batch touches structurally
(must stay red with the same cause, never silently green):

- `tests.test_wire_v1::test_unavailable_capabilities_carry_a_reason` (scope item 7)
- `tests.test_placement.py::*` (scope items 1–4)
- `tests.test_wire_error_family_101::test_no_wire_error_is_constructed_with_a_non_family_first_argument`

### Baseline red ledger (inherited, per test ID)

Harness (2) — the registered npm-closure schema-drift pair, matching
`docs/known-issues.md` row 2:

- `plugins/harness/tests/install/test_acp_schema_drift_target.py::test_the_acp_schema_a_closure_carries_satisfies_the_adapter_that_needs_it`
- `plugins/harness/tests/install/test_acp_schema_drift_target.py::test_a_root_override_of_the_schema_does_not_violate_a_declaration_in_the_closure`

ACP orchestration (18) — the registered worker-entry retirement red, matching
`docs/known-issues.md` row 1 (do **not** revive compat chains to green these):

- `tests/acp_orchestration/test_access_authorization.py::test_unauthorised_send_launches_nothing`
- `tests/acp_orchestration/test_channel_passthrough.py::test_request_result_and_upward_notification_flow`
- `tests/acp_orchestration/test_channel_passthrough.py::test_downward_cancel_reaches_the_agent_and_settles_the_turn`
- `tests/acp_orchestration/test_channel_passthrough.py::test_cancelled_stop_reason_flows_through`
- `tests/acp_orchestration/test_channel_passthrough.py::test_upward_error_carries_the_native_error_identity`
- `tests/acp_orchestration/test_channel_passthrough.py::test_advertised_session_capability_is_observed`
- `tests/acp_orchestration/test_channel_passthrough.py::test_unknown_update_kind_flows_through`
- `tests/acp_orchestration/test_channel_passthrough.py::test_message_meta_flows_through`
- `tests/acp_orchestration/test_channel_passthrough.py::test_advertised_extension_capability_flows_through`
- `tests/acp_orchestration/test_disconnect_and_release.py::test_channel_death_during_prompt_is_not_success_or_cancel`
- `tests/acp_orchestration/test_disconnect_and_release.py::test_release_only_touches_the_owned_channel`
- `tests/acp_orchestration/test_disconnect_and_release.py::test_no_reprompt_no_replacement_session_after_death`
- `tests/acp_orchestration/test_dual_connections.py::test_two_channels_same_jsonrpc_ids_and_same_native_id_do_not_cross`
- `tests/acp_orchestration/test_project_binding.py::test_project_cwd_reaches_both_launch_boundaries`
- `tests/acp_orchestration/test_project_binding.py::test_project_replaced_by_different_tree_refused`
- `tests/acp_orchestration/test_reverse_request.py::test_reverse_request_arrives_verbatim_and_answer_completes_round_trip`
- `tests/acp_orchestration/test_reverse_request.py::test_client_chosen_option_id_is_not_replaced_by_a_kind_guess`
- `tests/acp_orchestration/test_reverse_request.py::test_permission_request_without_a_decision_is_not_answered_by_the_server`

Server suite: per-ID ledger recorded from `.baseline-evidence/junit-server.xml`
when the baseline run finished; classified against the migrated-tree ledger in
`docs/migration/backend-build-test.md` (782P/44F/10S/25E with the seven
scope-missing rulings in `docs/known-issues.md`).

## wire/1 method inventory (67 methods)

Source of truth at baseline: `apps/server/src/ordessa_server/wire/handlers.py`
(`_PARAM_SHAPES`, `WireService._handlers`, `WireService._capability`). One
atomic descriptor per method is the target; this table is the ownership record
the migration must reproduce.

| Family (methods) | Handler | Data owner | Capability condition (`_capability`) | Call-time behaviour when composition absent | Plugin candidate |
| --- | --- | --- | --- | --- | --- |
| `server.hello` | `WireService.hello` | harness registry (deployment fact) | always supported | n/a | **Server host (retained)** |
| `workspaces.browse/open/list/archive/gitStatus` (5) | `workspaces_*` | `WorkspaceService` → `WorkspaceRecords` + connectors(`wsl`/`ssh`) + `LocalEnvironmentProvider` | no `readiness_blockers()` (else first blocker code, e.g. `LOCAL_SANDBOX_UNAVAILABLE`) | n/a (composed) | **Workspace domain plugin — first migration** |
| `executions.list/get` (2) | `executions_*` | session-record DB (`server_*` tables) + execution port via `list_executions` / `channel_run_view` | always supported | n/a (composed) | Agent-session / execution domain (later batch) |
| `acp.channel.open/release` (2) | `acp_channel_*` | `AcpChannelRegistry` (`runtime.acp_channels`) | always supported | `CAPABILITY_UNSUPPORTED` when no channel registry composed | Harness server facet (next batch — explicitly **not** this batch) |
| `profiles.*` (11) | `profiles_*` | `ProfileService`/`ProfileRecords` + harness registry + `model_configs` (sendability walk) | always supported | partial degradations (`sendability` unknown) | Profile domain (later) |
| `providerModels.*` (6) | `provider_models_*` | `ProviderModelService`/records + secret store | always supported | `UNAVAILABLE` (`_require_model_configs`) | Model-provider domain (later) |
| `assets.*` (11) | `assets_*` | `AssetRecords` + `Skill/Mcp/PluginAssetStore` + `CatalogStore` | always supported | `UNAVAILABLE` (`_require_assets` / `_require_catalogs`) | Asset domains (later) |
| `hooks.*` (6) | `hooks_*` | `HookRecords` + `HookTriggerRecords` | always supported | `UNAVAILABLE` (`_require_hooks`) | Hooks domain (later) |
| `accounts.*` (4) | `accounts_*` | `AccountRecords` + `AccountAssetStore` + subscription files | always supported | `UNAVAILABLE` (`_require_accounts`) | Account domain (later) |
| `providerArtifacts.*` (3) | `provider_artifacts_*` | `ArtifactStore` | always supported | `UNAVAILABLE` + `internalCode: ARTIFACT_STORE_UNAVAILABLE` | Model-provider artifacts (later) |
| `usage.aggregate/export` (2) | `usage_*` | `UsageAggregator` | always supported | `UNAVAILABLE` + `internalCode: USAGE_AGGREGATOR_UNAVAILABLE` | Usage domain (later) |
| `config.describe/resolve` (2) | `config_*` | harness registry + `model_configs` + profile records | always supported | `UNAVAILABLE` (`_require_model_configs`) | Model-provider/Profile (later) |
| `sessions.*` (6) | `sessions_*` | `SessionService`/records + execution port + **workspace records** + queue | `execution is not None` (else `EXECUTION_CAPABILITY_UNAVAILABLE`) | handler-level refusals | Agent-session domain (later) |
| `sendOutcome.query` (1) | `send_outcome_query` | session intent records | `execution is not None` | n/a | Agent-session domain (later) |
| `queue.get/withdraw` (2) | `queue_*` | `QueueRecords` | always supported | n/a | Agent-session domain (later) |
| `runs.stop` (1) | `runs_stop` | execution port | always supported | `{"outcome":"unconfirmed","reason":"EXECUTION_CAPABILITY_UNAVAILABLE"}` | Agent-session/execution (later) |
| `approvals.decide` (1) | `approvals_decide` | `ApprovalRecords` | always supported | n/a | Agent-session domain (later) |
| `history.snapshot` (1) | `history_snapshot` | session records + objects + `WorkspaceService.read_workspace_file` | always supported | n/a | Agent-session domain (later) |

Cross-domain reads of workspace facts that constrain the Workspace migration
(the reason the migration is plugin-surface-first, records-second):

- `sessions.createAndSend` / `sessions.send`: `workspaces.records.get(workspace_id)`
- `history.snapshot` → `_message`: `workspaces.read_workspace_file(...)`
- `acp.channel.open`: `workspaces.records.get` + `workspaces.local.validate`
- host REST routes (`/api/v1/workspaces*`, `ProductRepositoryView`) and
  bootstrap `mark_workspaces_unverified()`: `WorkspaceRecords` directly
- sidecar execution assembly: workspace record placement facts

## On-disk identifiers to preserve (data compatibility)

- data-root owner marker `.agentbox-server-root` with content
  `agentbox-server-r1\n`; `server.lock`; `secrets/http-token` (≥32 chars, 0600)
- database schema + migration numbering unchanged (`server_workspaces`,
  `server_bootstrap`, object store layout)
- deployment JSON `schemaVersion: 1` and all its field names
- wire method ids, `{id, supported, reason?}` capability shape, error families
  (`INVALID_REQUEST`, `CAPABILITY_UNSUPPORTED`, `UNAVAILABLE`, …), and the
  `X-Wire-Version: wire/1` header

## Composition facts the host boundary must reproduce

- Default composition (`build_runtime`): every domain composed eagerly; both
  `execution` and `acp_channels` may legitimately be `None` (typed refusals).
- `wire.acp_channels` and `wire.native_execution_provider` are composed
  **post-construction** by native/sidecar compositions.
- hello capability order == dispatch table insertion order (pinned by
  `test_hello_capability_sync_097.py` G1); composition must reproduce the
  baseline sequence.
- `runtime.wire.workspaces.local` is mutated by tests to pin sandbox blockers —
  the wire surface must keep exposing the live `WorkspaceService` instance the
  plugin owns.
