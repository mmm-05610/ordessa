# T01 — Legacy inventory and read-only migration matrix

Frozen 2026-09-28. Every symbol and line number below was re-verified with grep
in this worktree at HEAD `96fef2db47f485091ccaadda96f5321400b249f2` before being
recorded. This document is **read-only analysis**: no legacy file is modified by
this line, and no legacy behaviour is deleted here.

## 1. What the legacy "subagent" mechanism actually is

`plugins/server-compat/src/ordessa_server_compat/profiles/subagents.py` (285
lines) is **server-side Profile delegation**, not a definition catalogue. It owns
no table and no persistence — it is pure functions over rows supplied by the
caller.

| Symbol | Line | Category |
| --- | --- | --- |
| `MAX_SUBAGENT_DESCRIPTION_CHARS = 160` | :28 | constant (capacity precedent only) |
| `MAX_ROSTER_ENTRIES = 32` | :29 | dispatch |
| `MAX_INLINE_NAMES = 8` | :30 | dispatch |
| `DEFAULT_TURNS_LIMIT / DEFAULT_TIMEOUT_SECONDS / MAX_TIMEOUT_SECONDS` | :31-33 | dispatch |
| `DelegationError` | :42 | dispatch |
| `grant_edges(rows)` | :54 | **authorization edge** |
| `resolve_roster(...)` | :63 | dispatch |
| `has_delegation(edges, profile_id)` | :101 | **authorization edge** |
| `check_cycle(chain)` | :106 | dispatch |
| `tool_definitions(*, roster, include_run=True)` | :123 | synthesises `list_subagents` / `run_subagent` |
| `validate_run_arguments(...)` | :182 | dispatch |
| `inline_available(error)` | :279 | dispatch |

Persistence and wiring (all **outside** this line's write surface):

- Table `server_subagent_grants (parent_profile_id, child_profile_id, created_at)`
  — DDL at `packages/pacthold/src/pacthold/storage/database.py:238`, created by
  migration `_migrate_16_to_17` at `:419`. `PRODUCT_SCHEMA_VERSION = 21` (`:11`).
- Writers: `profiles/repository.py:140 grant_subagent` (rejects self, rejects
  would-be cycles, `INSERT OR IGNORE`), `:168 revoke_subagent`, `:178
  subagent_grants`.
- Wire methods `profiles.subagentGrants / grantSubagent / revokeSubagent` —
  `core_wire.py:336-338` with handlers at `:1104-1140`.
- Run path: `execution/delegation.py` — `DelegationService.list_for` (:98),
  `.run` (:115), `_merged_posture` narrowing (:384), child-turn insert (:483-494),
  `_await_terminal` timeout+stop (:538-560).
- Exposed to models as a synthesised MCP entry `agentbox-subagents`
  (`composition.py:1079-1140`), served by
  `plugins/harness/runtime/subagent-bridge.mjs`.
- Call history is **not a table**: `server_turns.parent_turn_id` added by
  `_migrate_17_to_18` (`database.py:314-321`); read by
  `sessions/repository.py:947 turn_ancestry_profile_ids`, `:1106
  turn_message_deltas`, `:688 get_turn_context`; event `turn.accepted`.

**Key structural fact:** there is no legacy "subagent definition" row. The legacy
role *content* is the `server_profiles` row itself (`name`, `harness_type`) plus
its config object digest (`config_revision`, `config_object_digest`); the
`description` that `resolve_roster` reads (`subagents.py:91`) is a projection
field, **not a column** of the `server_profiles` DDL (`database.py:40-60`). This
is decisive for the migration matrix: a "definition" cannot be recovered purely
from a definitions table because no such table exists.

FR12 / G10 consequence: `grant_edges`, roster, `run_subagent`, cycle detection,
turn/timeout limits and the `agentbox-subagents` MCP synthesis **must not** be
copied into `plugins/assets/subagents/`, and must not be repurposed as the new
definition authorisation store.

## 2. Content-store precedents worth reusing (by pattern, not by import)

`plugins/server-compat/src/ordessa_server_compat/assets/` is a *plugin* module;
importing it from another plugin would create a plugin→plugin edge, so this line
reuses the **pattern** and keeps a lightweight domain-owned store
(`research-and-reuse.md` §"逐模块复用决议" allows exactly this: "若共享模块真实
存在才复用，否则保留本域轻量 store").

| Symbol | Location | What it proves |
| --- | --- | --- |
| `AssetRecords.publish(*, key, request_digest, kind, name, revision, digest, description, source, asset_id)` | `assets/records.py:28` | idempotent replay, `sha256:` digest validation (:40), caller-chosen slug honoured on first publish (:58-64), `source=COALESCE` never silently overwritten (:73-75) |
| `AssetRecords.bind(*, profile_id, asset_id, revision, enabled)` | `records.py:93` | pinned-revision CAS: `chosen > latest_revision ⇒ 409` (:100), `ON CONFLICT(profile_id,asset_id) DO UPDATE` (:109) |
| `AssetRecords.copy_bindings` / `bindings` | `records.py:126`, `:166` | bulk re-bind with `enabled_only` filter |
| `parse_skill_frontmatter(text)` | `assets/skills.py:45` | YAML-frontmatter-over-Markdown parsing precedent |
| `_walk_bounded(root)` | `skills.py:87` | `MAX_ASSET_ENTRIES=512`, `MAX_ASSET_BYTES=32 MiB`, **no symlinks** |
| `SkillAssetStore.install` / `.verify` | `skills.py:119`, `:168` | staging dir + `os.rename`, tree digest via `pacthold.resource_contracts.runtime_artifacts.runtime_artifact_tree_digest`, duplicate revision refused (:137) |
| `CatalogStore.sync` | `assets/catalog.py:110` | stage-then-`os.replace`, "failed sync lands nothing" (:124-136) |
| `CatalogStore.install_entry` | `catalog.py:163` | pinned provenance `f"{snapshot['digest']}:{entry['origin']}"` (:184) |
| `CatalogStore.payload_path` | `catalog.py:209` | escape check (:215) |

Tests for these patterns: `apps/server/tests/test_asset_hubs.py` (`:40`
frontmatter, `:64` install/digest, `:211` catalogue+bindings, `:410` wire face,
`:595` snapshot/install provenance, `:644` index refusals, `:704` plugin asset),
`test_import_asset_request_id_129.py`, `test_asset_surface_refusals_147.py`.

## 3. Migration matrix (read-only, dry-run scope)

Legend — `MIGRATE`: content is provably a pure role definition with a
re-derivable source and stable identity. `KEEP-LEGACY`: stays with its current
owner (dispatch/security history). `REJECT`: must never enter the new store.
`UNKNOWN`: cannot be proven from data alone; requires an explicit approval step.

| Legacy artifact | Location | Decision | Rationale | Rollback unit |
| --- | --- | --- | --- | --- |
| `server_subagent_grants` rows | `database.py:238`, `_migrate_16_to_17` | **REJECT** | Authorization edges for the old dispatcher (FR12). Not definition content. | n/a — never written by this line |
| `run_subagent` / `list_subagents` tool schemas | `subagents.py:123-181` | **REJECT** | Dispatch surface; belongs to `execution/delegation.py` owner | n/a |
| Cycle/turn/timeout validation | `subagents.py:106,182-269` | **KEEP-LEGACY** | Runtime policy of the delegation service, not a definition ceiling | n/a |
| `server_turns.parent_turn_id` call history | `database.py:314-321` | **KEEP-LEGACY** | Run history; spec says run history is not migrated by default (data-model §状态和迁移) | n/a |
| `agentbox-subagents` MCP synthesis | `composition.py:1079-1140` | **KEEP-LEGACY** | Old authorization edge retains its owner (T13 requires *keeping* it, not deleting it) | n/a |
| `server_profiles` row where the profile is used *as* a delegate (name + harness_type + description projection) | `subagents.py:88-94` | **UNKNOWN** | Only a *candidate*: the description has no column, so content provenance is not provable from the row alone. Import requires per-item approval (G05) and records `SourceApproval(origin="user-upload"/"git-revision")`. | Per-item: skip → nothing written |
| `server_assets` (`kind,name,description,latest_revision,digest,source`) | `database.py:197-207`, `_migrate_12_to_13:474-496` | **UNKNOWN → MIGRATE only for `kind` explicitly holding role bodies** | Generic asset catalogue; only rows whose digest-referenced content decodes as a role body qualify. | Dry-run manifest lists id+digest; no write |
| `server_profile_assets` bindings (`revision` pin, `enabled`) | `database.py:208-216` | **MIGRATE as assignment intent, not as approval** | A binding is a *desired choice*; promotion to an enabled assignment needs `approveAssignmentUpdate` (FR02: editing does not auto-update a fixed assignment) | Mapping table `legacy(profile_id,asset_id,revision) → assignment` id |
| `skills` frontmatter content under an asset root | `SkillAssetStore` root dirs | **REJECT** | Skills are a different domain owned by Q1 | n/a |

### Identity, format and idempotency rules for the import (G10)

- `definitionId` is **never** derived from a name/slug (data-model §1); an
  imported row gets a fresh opaque id, and the legacy key is recorded in
  `SourceApproval.origin_ref` so the mapping is reversible.
- Import runs in two steps: `import_preview` (read-only, produces per-file digest
  + diagnostics, writes nothing) then `approve_import` (explicit principal +
  expected row version + operation key). Re-running `approve_import` with the
  same operation key and same payload digest **replays** the recorded result; a
  different payload under the same key is refused.
- Byte/ID equality check: the dry-run manifest is a sorted list of
  `(legacy_key, content_digest, target_definition_id, target_revision)`. A
  rollback sample is produced by re-importing the same manifest into a fresh
  store root and asserting the manifest is identical, i.e. the importer is a
  pure function of approved input.
- Nothing from a real user HOME or a live data root is used as a fixture; tests
  use synthetic fixtures under `tmp_path` only. Real user-data migration is out
  of scope for this round and is called out in `report.md` as untested.

## 4. Boundary rules this line must keep passing

- `apps/server/tests/test_dependency_direction.py:128`
  `test_pacthold_imports_isolated_from_every_product_package`, `:135`
  `test_the_host_imports_isolated_from_every_plugin_package`, plus the
  "legacy business entries no longer exist" assertions.
- `apps/server/tests/test_server_compat_boundary.py:101`
  `test_the_host_core_imports_no_plugin_no_product`, `:152`, `:159` (plugins may
  not import host privates).
- Consequence for `ordessa_assets_subagents`: may depend on stdlib and the
  published vocabulary packages; must not import `ordessa_server_compat`,
  `ordessa_harness` internals, `ordessa_server_product`, or any host private.
  Runtime dependencies of this package are recorded in
  `integration-request.md`; adding it to `products/**` composition is C0's
  exclusive write surface.
