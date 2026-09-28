# T01 Harness migration ledger

Snapshot: C0 working tree, 2026-09-28. Scope is the currently committed Harness
source and static callers. This ledger expands `docs/design/harness-v2/migration.md`;
it does not authorize deleting a module merely because a text search found no
caller. B's final source `888d69f853a38427e8131bec462ca4327821b835`
has been merged into C0 at `26be37359d`; the Server caller statements below
have been rechecked against that committed source. No user data was read.

## File-by-file migration decisions

| Existing file | Active caller found now | Persistent identity/path | Target owner and deletion condition |
| --- | --- | --- | --- |
| `src/ordessa_harness/native_materialization.py` | Direct production `src` imports: none in merged B's `apps/server/src`, `products/server/src`, or `plugins/server-compat/src`; `apps/server/tests/test_native_materialization_093_stage3.py` and Harness tests import its renderer/table. Its own code imports all eight brand `native.py` modules. | Canonical protocol IDs (`openai-chat`, `openai-responses`, `anthropic-messages`, `gemini-generate`), family key `claude-code`, native target paths below. | Provider/model renderer, protocol map and golden cases → Z3 `harness_adapters`; native target handle and allowed file path → Harness. Delete aggregate after all production/test imports move, target claims are registered, and negative unsupported-protocol behavior survives. |
| `src/ordessa_harness/codex/native.py` | `native_materialization.py`; production template independently uses `deploy/codex/config.toml`. | `wire_api` dialect; `config.toml`; family `codex`. | Z3 owns dialect/field mapping; Harness owns validated target path/codec. Remove old table only after both consumers use new owners and golden/negative tests pass. |
| `src/ordessa_harness/pi/native.py` | `native_materialization.py`; production template independently uses `deploy/pi/models.json`. | `api=openai-completions`; `models.json`; family `pi`. | Same split and gate as Codex; do not infer dynamic apply from template. |
| `src/ordessa_harness/claude/native.py` | `native_materialization.py`; production template independently uses `deploy/claude/settings.json`. | `ANTHROPIC_BASE_URL`; `settings.json`; family `claude-code` (directory `claude`). | Z3 field mapping, Harness target/codec; preserve alias, session-scoped route and negative non-Anthropic protocol refusal. |
| `src/ordessa_harness/opencode/native.py` | `native_materialization.py`; production template has `deploy/opencode/opencode.json`. | `npm=@ai-sdk/openai-compatible`; `opencode.json`. | Z3 mapping, Harness target; preserve existing startup baseline before deleting. |
| `src/ordessa_harness/hermes/native.py` | `native_materialization.py`; production template has `deploy/hermes/config.yaml`. | `transport=chat_completions`; `config.yaml`. | Z3 mapping, Harness target; preserve parser/codec and startup baseline. |
| `src/ordessa_harness/kilo/native.py` | `native_materialization.py`; production template has `deploy/kilo/kilo.json`. | Own copy of `npm=@ai-sdk/openai-compatible`; `kilo.json`. | Z3 mapping, Harness target; preserve independent family identity and startup baseline. |
| `src/ordessa_harness/dsh/native.py` | `native_materialization.py`. | Empty dialect map, `NATIVE_TARGET=None` are explicit refusals. | Z3 retains typed absence; Harness exposes no invented target. Remove old table only when refusal tests remain. |
| `src/ordessa_harness/qwen/native.py` | `native_materialization.py`. | Empty dialect map, `NATIVE_TARGET=None` are explicit refusals. | Same as dsh; do not convert empty pin into generic file write. |
| `src/ordessa_harness/generic/profile_store.py` | `generic/factory.py`, `generic/profile_provider.py`, `claude/profile.py`, `hermes/profile.py`, `opencode/profiles.py`; tests. | `harness-profile` provider; `context.agent_box_home/profiles/<harness_type>/<profile_id>/revisions/<n>/envelope.json`; envelope `schema_version=1`, revision and digest; `AgentBoxProfileV1` Ref. | Z1 owns user preset persistence; Harness owns immutable execution launch snapshot/Ref. Inventory real records with explicit sample metadata before any data migration. Delete old store only after exact reference/read compatibility or approved dry-run migration and no dual writer. |
| `src/ordessa_harness/generic/profile_provider.py` | No production import found by static search; re-exports `ProfileStore`. | Alias `ProfileProvider`; inherits `harness-profile` identity. | Remove with old store after import scan proves no plugin/export consumer; no compatibility alias. |
| `src/ordessa_harness/generic/profile_selector.py` | `generic/factory.py`. | Selector `<harness_type>-profile-selector`, contract `AgentBoxProfileV1`, exact revision. | Z1 supplies resolved profile selection; Harness consumes launch snapshot. Remove after registration and persisted Ref semantics are replaced/tested. |
| `src/ordessa_harness/generic/profile_manager.py` | `generic/factory.py` through `ProfileEnvelopeManager`. | Existing manager ID is harness type, revision/CAS and disabled state. | Z1 CRUD; remove after product Profile API owns the only writer and old manager registration is gone. |
| `src/ordessa_harness/generic/factory.py` and `entrypoints.py` | `plugin.py`, `pyproject.toml` `agent_box.plugins` entries (`harness-profile-store`, `codex`, `claude`, `opencode`, `hermes`, `pi`); Harness identity tests. | Distribution entry-point names and IDs above; descriptor `harnesses` namespace; execution IDs `<harness_type>-execution`. | C0 Harness integration consumes `pacthold.public` and stable plugin API. Preserve on-disk/entry-point IDs unless explicit migration approved. Delete generic registration path only after unique new registration and wheel/import tests; no `core` alias. |
| `src/ordessa_harness/resources/profile_codec.py` | `resources/__init__.py` re-export; no production direct call found. | Canonical JSON bytes used by legacy profile/resource format. | Resolve actual binary/data consumer before removal; preserve digest bytes if persisted refs depend on it. |
| `src/ordessa_harness/server_acp/plugin.py` | `products/server/src/ordessa_server_product/composition.py` and `plugins/server-compat/src/ordessa_server_compat/composition.py` import `AcpChannelServerPlugin` in merged B; the latter also imports `AccessEntryTransport`. | Plugin ID `ordessa.harness.acp`; wire `acp.channel.open`, `acp.channel.release`, stream `acp-channel`; dependency `ordessa.server-compat`. | C0 Harness integration keeps one ACP owner, replaces host-internal imports (`ordessa_server.errors`, `wire.handlers`) and old ports after B; remove compat dependency only after equivalent admission/refusal tests. |
| `server_acp/registry.py` | `plugin.py`, package `__init__.py`; channel pair `(harnessId, projectId)`. | `connectionId`, `executionId`, session/profile IDs and run ledger. | C0 keeps lifecycle/identity owner; adapt record ports after B; prove re-acquire/release/abnormal-exit races before replacing. |
| `server_acp/runs.py` | `registry.py`, package `__init__.py`. | Run state and terminal reason, linked to channel execution. | C0 keeps evidence writes through public Server port; remove direct legacy record coupling only when equivalent ledger assertions pass. |
| `server_acp/access_entry.py` | package `__init__.py`; `plugins/server-compat/src/ordessa_server_compat/composition.py` imports its public `AccessEntryTransport` re-export in merged B. | Owns access-entry transport process identity; no user profile store. | C0 retains raw/control split and close semantics; substitute launch port only after process and frame tests. |
| `server_acp/transport.py` | `access_entry.py`, package `__init__.py`. | Ephemeral NDJSON process/pipe; no on-disk schema. | C0 retains while single ACP relay uses it; verify close and no fabricated replies. |
| `server_acp/__init__.py` | Public package exports and tests. | Import path `ordessa_harness.server_acp`. | Update exports after B and API freeze; delete obsolete exports only after exact external import inventory. |
| `src/ordessa_harness/harnesses.toml` | `registry/loader.py` via installed resource; `generic/factory.py`; production templates derive capability claims via `registry/capability_claims.py`; tests. | `schema_version=1`, eight `harness_type` values (`codex`, `claude-code`, `opencode`, `hermes`, `dsh`, `qwen`, `kilo`, `pi`), driver IDs and descriptor fields. | C0 runtime descriptor authority; preserve IDs and declared ceilings. Consolidate with JS list only when both product and access-entry read one generated/validated descriptor and existing aliases are preserved. |
| `harnesses/index.mjs` | `listHarnesses`, `isKnownHarness`, `harnessLaunchContext` exported; no in-tree JS importer found by `rg`, so external/runtime consumer status is **UNKNOWN**. | JS keys include `claude`, `claude-code`, `codex`, `dsh`, `hermes`, `kilo`, `omp`, `pi`, `qwen`; differs from TOML (`opencode` versus `omp`, `claude` alias). | C0 sole descriptor generation/consumption. Preserve transport aliases and `HARNESS_UNDISCOVERED` refusal; remove list only after runtime bundle/import graph and controlled launch prove equivalent resolution. |

## Read-only cross-line and Server handoff checks

The ownership split above follows the frozen design: Z3 model/provider mappings,
Q1 Skills rules (`adapters/skill_observation.py` and family Skill rules), Z1
user Profile CRUD, C0 runtime/config targets, registration and ACP transport.
No Z1/Z3/Q1 source has been integrated into this C0 checkout; their interface
and source SHAs must be checked against each line's published checkpoint before
replacing callers. B final is merged, but C0's full production chain is still
under integration. In merged B, `plugins/server-compat` remains the caller of
`AccessEntryTransport` and `channel_run_view`, and the product selects
`AcpChannelServerPlugin`. Those call sites must be replaced or justified by
tests before T15 deletion; a static import inventory is not a production proof.

## Deletion gates

1. Enumerate imports/entry points in installed wheels and the bundled JS
   runtime, then map every active consumer to the new public API; no fallbacks
   or `sys.modules` aliases. A negative import test must fail with the retired
   module's own `ModuleNotFoundError`.
2. Preserve persistent IDs and bytes (`harness-profile`, `AgentBoxProfileV1`,
   `agent_box.plugins`, profile revision path, `ordessa.harness.acp`, wire
   methods, family aliases). If user data changes, dry-run on synthetic and
   consented samples before any production migration.
3. Prove one writer per config target and profile store; no core→business,
   Harness→Z3/Q1 implementation, or business→host-internals imports. Keep
   capability refusal and old-brand startup counterexamples.
4. Integrate B final and each business checkpoint first, then run the actual
   Server/channel/submit and wheel tests. Static `rg` alone cannot close T01.

## Static evidence command

`rg -n 'native_materialization|profile_store|profile_selector|profile_provider|profile_manager|profile_codec|ordessa_harness.server_acp|create_profile_store|create_codex|create_claude|create_pi' plugins/harness/src plugins/harness/runtime apps/server/src -g '*.py' -g '*.mjs'` exited 0. Targeted searches of `harnesses/index.mjs`, `harnesses.toml`, `products/server`, package entry points and each `native.py` also exited 0. Searches that included absent `plugins/profile`, `plugins/assets/model-provider` and `plugins/assets/skills` paths exited 2; those packages are not integrated in this tree. No tests or native/model calls were run.
