# Q1 Skills v2 — baseline seam inventory & gaps (read-only survey)

Survey scope: this worktree only (`/home/maoqh/projects/ordessa/worktrees/011-q1-skills`),
branch state before any C0/Z1/Z2 checkpoint merge. No checkpoint branches exist yet
(`specs/011-plugin-rollout/` has no `checkpoints/` dir; the protocol is defined in
`specs/011-plugin-rollout/contracts/checkpoints.md`). Every "exists" below is importable
today from this tree; every "missing" is stated without invented symbols.

Legend: ✅ exists & importable · ⚠️ partial / internal-only · ❌ does not exist in code.

---

## 1. Server plugin registration

### Exists

- **Published plugin contract package**: `packages/server-plugin-api`, dist name
  `ordessa-server-plugin-api` v0.1.0 (`pyproject.toml:6`), module `server_plugin_api`,
  zero dependencies. Stable exports (`src/server_plugin_api/__init__.py:43-67`):
  `SERVER_PLUGIN_API_VERSION` (`contract.py:8`), `PLUGIN_METHOD_ID` (`contract.py:15`),
  `ServerPluginDescriptor` (`contract.py:21`), `ServerMethodDescriptor` (`contract.py:56`),
  `StreamRouteDescriptor` (`contract.py:94`), `HttpRouteDescriptor` (`contract.py:123`),
  `ServerPluginContext` (`contract.py:163`), `ServerPluginRegistration` (`contract.py:186`),
  `ServerPlugin` protocol (`contract.py:216-222`, methods `descriptor()` / `build(context)`)
  and typed errors (`__init__.py:26-41`: `DuplicateMethodError`, `PortConflictError`,
  `InvalidDeclarationError`, `DependencyError`, `CyclicDependencyError`, …).
- **Method id grammar** (`contract.py:15`): `[a-z][a-zA-Z0-9]*(\.[a-zA-Z][a-zA-Z0-9]*)*`
  — a `skills.*` family (`skills.catalogue`, `skills.importBegin`, `skills.previewEffective`…)
  is valid; hyphenated words are not.
- **One-shot atomic method declaration**: `ServerMethodDescriptor(method_id,
  required_params, optional_params, handler, owner, availability)` (`contract.py:56-91`);
  handler receives only the params `Mapping` (`contract.py:71`). Availability predicate
  `(supported, reason)` never gates dispatch (`contract.py:50-53`).
- **Registration surface** `ServerPluginRegistration(methods, stream_routes, http_routes,
  provided_ports, start_hooks, disposal)` (`contract.py:186-214`).
- **Host enforcement** (`apps/server/src/ordessa_server/plugin_host/host.py`):
  `MethodRegistry.register` duplicate refusal (`:101-117`); `ServerPluginHost.activate_all`
  DAG validation over `requires`, plugin-granular transactional rounds (`:289-336`);
  ports = host facades + provided_ports of **declared** `requires` only, shadowing is
  `PortConflictError` (`:385-393`); owner mismatch is a typed refusal (`:404-409`);
  hello/dispatch read only this registry (`:95-99`, `wire/handlers.py:5-7`).
- **Host-provided ports** every plugin can read in `build()`:
  `database`, `objects`, `notifier`, `idempotency`, `credentials`, `secret_store`,
  `connectors`, `cursor.codec`, `workspace.wsl_connector`, `workspace.ssh_connector`,
  `workspace.local_provider` (`bootstrap/runtime.py:489-504`) plus
  `context.data_root` (`contract.py:178`; compat uses `data_root / "assets"`,
  `plugin.py:125`).
- **Worked examples**:
  - `plugins/server-compat/src/ordessa_server_compat/plugin.py` —
    `ServerCompatPlugin.descriptor()` (`:85-89`, `requires=("ordessa.workspace",)`),
    `build()` reading ports (`:93-101`), loop turning `_COMPAT_METHODS`/`_PARAM_SHAPES`
    (`core_wire.py:325`, `:222`) into `ServerMethodDescriptor`s (`:246-258`),
    `provided_ports` map (`:269-292`), `start_hooks`/`disposal` (`:293-294`).
  - Clean split example: `plugins/workspace/src/ordessa_workspace/plugin.py:48-206`.
- **Boundary rules a new plugin must honor** (pinned gates): plugin may import
  `server_plugin_api`, the host's neutral vocabulary (`ordessa_server.errors`, `.records`,
  `.ids`, `.idempotency`, `.credentials`, `.events`, `.connectors`,
  `.wire.{errors,envelope,projection,handlers helpers}`), `pacthold`, its own package and
  declared deps — never host business modules (`apps/server/tests/test_server_compat_boundary.py:16-21`;
  `apps/server/tests/test_dependency_direction.py:36-38`).
- **Compat surface may only shrink**: `FROZEN_COMPAT_METHODS`
  (`test_server_compat_boundary.py:33-49`) includes the current asset family
  `assets.list/publishSkill/publishMcp/publishPlugin/bind/unbind/bindings/syncCatalog/
  catalog/installFromCatalog/probe` (`core_wire.py:252-262`, handlers
  `core_wire.py:859` `assets_publish_skill`, `:936` `assets_bind`, `:959` `assets_bindings`).

### Missing / boundary facts

- ❌ **No public self-registration seam for a new plugin.** The activation set is hard-
  coded in `products/server/src/ordessa_server_product/composition.py:40-55`
  (`ServerProductComposition.default_plugins()` returns exactly `WorkspaceServerPlugin`,
  `ServerCompatPlugin`, `AcpChannelServerPlugin`), resolved through the single
  `ordessa.server_product` entry point (`bootstrap/runtime.py:388`, `:391-417`, `:514-527`).
  `products/**` is C0-owned (`specs/011-plugin-rollout/plan.md` §"C0 另独占").
- The current tree has **no** `register_contribution_point` / generic
  `Contribution(point_id, api_version, payload)` carrier (design-doc reference to the
  "platform tree", `docs/design/harness-v2/contracts.md:3`; grep finds nothing in code).

### Q1 can build today

Code against `server_plugin_api` + host semantics; unit-activate the plugin with
`build_runtime(data_root, server_plugins=(SkillsServerPlugin(), ...))` (explicit
selection, `runtime.py:433`, `:524-525`). The composition inclusion itself is request G1.

---

## 2. Harness configuration contribution point

### Exists / Missing

- ❌ **`harness.configuration-adapters` v1 does not exist in code.** Nor do
  `MountContent`, `RemoveOwnedContent`, `SetField`, `ResetField`, `BindSecret`,
  `InvokeAction`, `IntentSet`, or any `assess/compile/verify` symbol — all of these are
  target contracts in `docs/design/harness-v2/contracts.md` §C2-C4 (`:26-77`), plus the
  port `harness.configuration` with `inspect/plan/apply/query/reconcile` (`:63-71`).
  They appear in no `.py`/`.ts` file under `apps/`, `packages/`, `plugins/`, `products/`.
- ⚠️ **Closest existing mechanisms** (real names, none is a registration point):
  - Brand-internal projection code inside the harness plugin:
    `ordessa_harness.claude.profile.ClaudeProjection.materialize` writes
    `kind=="skill"` resources to `<root>/<execution_id>/.claude/skills/<name>/SKILL.md`
    (`plugins/harness/src/ordessa_harness/claude/profile.py:40-52`);
    `HermesProjection.materialize` (`hermes/projection.py:11-27`); Pi gets a hardcoded
    `--skill-dir /runtime/home/skills` argv injection (`pi/projection.py:35`,
    `pi/config.py:32,58,92` field `skill_dirs`).
  - Sidecar turn assembly in server-compat: `composition.py:995-1167` iterates
    `runtime.asset_records.bindings(profile_id, enabled_only=True)` but **only renders
    kind `"mcp"`** (`composition.py:1018-1020` filter `binding["kind"] != "mcp": continue`)
    plus hooks; targets must live under `/runtime/home/` (`:1043-1046`); slot conflicts
    with deployment `_projection_mounts` raise `ASSET_SLOT_CONFLICT` (`:1141-1153`);
    deployment `projectionFiles` → `_projection_mounts` (`:687-705`). **Skill bindings are
    stored but not applied to any turn today** — there is no existing skill delivery path.
  - "Loaded" observation: `ordessa_harness.adapters.skill_observation` —
    `SkillLoadedEvidence` (`:9-16`), `observe_loaded_skill` (digest-verified manifest read,
    `:19-30`), `observe_loaded_marker` (fake-target marker `SKILL_LOADED:<id>:<digest>`,
    `:33-39`). Harness-owned, bounded, not extensible by plugins.
  - Capability vocabulary: `ordessa_harness.registry.capability_claims.capability_claims`
    (`registry/capability_claims.py:14`) over `CANONICAL_CAPABILITY_IDS = (start, observe,
    finish, attach, steer, stream, permissions, native_continuation)`
    (`packages/pacthold/src/pacthold/resource_contracts/harness_capabilities.py:30-33`) —
    no skills/config facet.
  - ACP channel owner: `ordessa_harness.server_acp.plugin.AcpChannelServerPlugin`
    (`server_acp/plugin.py:46`) registers `acp.channel.open` / `acp.channel.release`
    (`:122-133`), stream route `acp-channel` (`:137-138`), provides port `acp.channels`
    (`:142`), `requires=("ordessa.workspace", "ordessa.server-compat")` (`:58`).
  - `HarnessDescriptor` with `security_locked_controls`
    (`plugins/server-compat/src/ordessa_server_compat/execution/__init__.py:59,85`;
    parsed from deployment JSON at `composition.py:874`).

### Gap (request G2, owner C0)

Caller: Q1 `harness_adapters/` (pi/codex/claude modules). Desired operation: register a
configuration adapter per `(facet=assets.skills, harness_id, version-range)` with pure
`assess/compile/verify`; compile output restricted to typed `MountContent`/
`RemoveOwnedContent`/declared actions referencing `assetId/revision/treeDigest`, bound to
`runtimeGeneration/projectId/profileRevision/assignmentRevision`. DTO: the C2/C3 types
frozen by harness-v2 (do not invent; Q1 will consume whatever `harness-api` publishes).
Failure expectation: overlapping facet/harness/entry ranges refused at registration; no
absolute paths accepted from adapters; `unknown` distinct from `unsupported`. C0 owns
this per `specs/011-plugin-rollout/plan.md:23` ("Harness v2 API/注册/应用/生命周期…发布
harness-api"). Independent Q1 work meanwhile: pure brand format modules + the
`SkillLoadedEvidence` level taxonomy tested against `observe_loaded_marker`.

---

## 3. Profile

### Exists

- No `plugins/profile/` package in this tree (top-level plugins: agent, commands,
  connections, connectors, harness, server-compat, workbench, workspace). Profile lives
  in server-compat (Z1 will retire it; frozen list §1).
- Records: `ordessa_server_compat.profiles.ProfileRecords`
  (`plugins/server-compat/src/ordessa_server_compat/profiles/repository.py:19`) —
  `create` (`:24`), `get` (`:53`), `update_configuration` (`:87`), `clone_from` (`:106`),
  `set_permissions` (`:190`), `bind_account` (`:218`); `config_revision` bump at `:260`.
  Service: `ProfileService` (`profiles/service.py`). Wire methods
  `profiles.list/create/update/updateConfig/archive/clone/memory/subagentGrants/
  grantSubagent/revokeSubagent/setPermissions` (`core_wire.py:226-236`).
- Schema `server_profiles` (`packages/pacthold/src/pacthold/storage/database.py:40-59`):
  `id`, `version`, `harness_type`, `config_revision`, `native_generation`,
  `config_object_digest` (content-addressed config object in `ObjectStore`),
  `credential_id`, `account_id`, `permission_preset`, `permission_rules_json`,
  `archived_at`. **Revision identity** = row `version` + `config_revision` + object
  digest; CAS via `expectedVersion` on every mutating method.
- `server_profile_assets` (`database.py:208-216`): `(profile_id, asset_id)` PK +
  `revision`, `enabled` — this is the fixed-revision binding the data-model doc preserves.
  Code: `AssetRecords.bind` (`assets/records.py:93`), `unbind` (`:117`),
  `copy_bindings` (`:126`), `bindings` (`:166`); skill content store
  `SkillAssetStore` (`assets/skills.py:110`, `install` `:119`, `verify` `:168`,
  `revision_dir` = `<assets_root>/skill/<assetId>/<revision>` semantics via `:116`).
- Session item override (today's only per-session mechanism): `overrides` param on send
  intents, `SessionService.accept_intent` (`sessions/service.py:93-97`), merge into
  effective config `configuration.update({item["controlId"]: item["value"] …})` (`:142`),
  refused against `security_locked_controls` (`:185-199`); the effective object is frozen
  per turn with `profile_revision` / `captured_profile_revision`
  (`database.py:104-105,117`, migration semantics `database.py:342-352`).

### Missing

- ❌ Facet / contribution mechanism: profile config is a single opaque `configuration`
  dict (`sessions/service.py:110-135`); no `assets.skills` facet, no per-domain fragment
  registry, no public profile-api package. Nothing named "facet" exists in profile code.
- ❌ No profile *plugin* import surface: everything above is `ordessa_server_compat`
  internals — Q1 may not import it (boundary rule §1).

### Gap (request G3, owner Z1)

Caller: Q1 `profile_contribution/`. Desired: public Profile API exporting (a) facet
registration for `assets.skills` with tri-state `inherit | enable(revision) | disable`
per assetId, (b) session item override read at resolve time, (c) revision identity tuple
`(profileId, configRevision, configObjectDigest)` usable in a Skills snapshot, (d) an
explicit migration ledger mapping existing `server_profile_assets` rows to
`enable(revision)`. DTO: item-level ops keyed by `profileId + expectedVersion`, typed
refusals for stale CAS, archived profile, unapproved revision. Independent meanwhile:
Skills' own assignment store and resolution order; the old binding rows are read-only
history for Q1.

---

## 4. Chat

### Exists

- No chat plugin in `plugins/`. Chat UI = desktop extensions `ordessa.agent-sessions`
  (`plugins/agent/sessions/`) and `ordessa.agent-conversation`
  (`plugins/agent/conversation/src/entry.tsx:6-13`; consumes `WorkbenchToken`,
  `AgentSessionsToken`).
- `plugins/commands` is a **desktop extension-host command registry**, not chat slash
  commands: `Commands` contract (`packages/desktop-platform/contracts/commands/src/commands.ts:3-9`,
  `CommandsToken` `:9`), impl `createCommands` (`plugins/commands/src/entry.ts:4-16`,
  provider id `ordessa.commands` `:18`), scope-owned registry helper
  `registry`/`ordered` (`plugins/commands/shared/registry.ts:3-16`). Consumed by the
  Workbench (`plugins/workbench/src/entry.tsx:5` `requires: [CommandsToken]`).
- Chat session surface: `AgentClient.send(sessionId, text)` /
  `createAndSend(workspaceId, text, requestId)`
  (`packages/desktop-platform/contracts/agent/src/agent.ts:118,154`); per-harness option
  menu `AgentOption{id,title,value,availability}` (`agent.ts:68-74`, in snapshot
  `:83`) — the closest analogue to a consumable "menu" and it is host-owned (models/
  modes), not a plugin contribution point.

### Missing

- ❌ Any `/`-slash or `+`-attachment **contribution registry** (grep across
  `plugins/agent`, `apps/desktop/renderer`, `packages/desktop-platform/contracts`: zero
  hits for slash/attachment/contribution in this sense). ❌ No `SkillChoice` type.
  ❌ No ACP explicit skill-invocation route.

### Gap (request G4, owners Z2 primary + C0 for the ACP leg)

Caller: Q1 `frontend/` chat menu glue. Desired: a chat command/attachment contribution
point accepting `SkillChoice { targetSession, assetId, revision, nativeName, description,
origin, state, explicitInvocationSupported, invokeDescriptor? }` sourced from the current
confirmed snapshot only. Failure expectations: stale `runtimeGeneration` responses must
not update the menu; name clash refused or namespaced (never overwrite system commands);
selection never auto-sends. Explicit-invoke route: if absent at first chat-api, browsing
still ships but US6 "invoke" stays honestly blocked (contracts.md `:40`,
`specs/011-plugin-rollout/plan.md` Q1/Z2 clauses).

---

## 5. Workspace

### Exists

- `ordessa_workspace.plugin.WorkspaceServerPlugin`
  (`plugins/workspace/src/ordessa_workspace/plugin.py:48`): methods
  `workspaces.browse/open/list/archive/gitStatus` (`:42-45`); provides ports
  `workspace.service` (`WorkspaceService`, `service.py:25`) and `workspace.records`
  (`WorkspaceRecords`, `records.py`) (`plugin.py:200-203`); no `requires`.
- **Consumption seam for Q1**: declare `requires=("ordessa.workspace",)` in the plugin
  descriptor → `workspace.service`/`workspace.records` appear in `context.ports`
  (host rule `plugin.py`-agnostic: `host.py:385-393`; precedent: server-compat
  `plugin.py:88`, `:170`).
- **Identity is a stable server-generated ID, not a client path**: `ws_<uuid hex>` via
  `opaque_id("ws")` (`apps/server/src/ordessa_server/ids.py:12-13`; minted at
  `WorkspaceRecords.create` `records.py:27` and `upsert_by_location` `records.py:68,87`);
  normalized path stored server-side (`records.py:100`), `get(workspace_id)` is the lookup
  (`records.py:59`). Sessions carry `workspace_id`, host binds resolution through
  `wire.bind_workspace_resolution` (`runtime.py:536-537`; `WireService.workspaces`
  `handlers.py:221-225`); native mode validates it via injected `native_workspace_validator`
  (`sessions/service.py:65-70`).

### Missing / caveats

- ❌ **No principal/serverScope concept anywhere in server code** (grep `principal` in
  `apps/server/src`, `packages/pacthold/src`, server-compat: only unrelated sidecar hits).
  Authorization today = per-data-root bearer token (`runtime.py:458` `_ensure_token`);
  the "已授权 projectId" in skills-v2 contracts reduces to "workspace row exists in this
  single-user data domain". A handler receives only the params mapping
  (`contract.py:71`) — no auth context is injected.

### Gap (request G5, owner C0, low urgency for v1)

Caller: Q1 `assignments/`. Desired: either an explicit statement that serverScope = the
Server data-root instance identity (and `workspaceId` existence check via
`workspace.records.get` is the authorization), or a typed context on
`ServerMethodDescriptor` handler calls. Counter-example expectation: cross-server or
fabricated `workspaceId` must refuse, not resolve. Q1 builds the lookup against
`workspace.records`/`workspace.service` today; only the *statement* is pending.

---

## 6. Desktop / frontend contributions

### Exists

- Extension model: `@ordessa/extension-api`
  (`packages/desktop-platform/extension-api/src/index.ts`) — `Token` (`:45`, lumino),
  `PluginContext { root.mount, resources }` (`:34-37`), `ResourceScope` (`:28-31`),
  `Contributions` (`:45`; `src/contributions.ts`), `scoped` (`:40-44`),
  `HOST_API_VERSION = '2'` (`:47`). Host runtime `runtime`/`Shell` from
  `@ordessa/extension-host` (`packages/desktop-platform/extension-host/src/index.ts:1-4`).
  Plugin import path for shared contracts is by extension id:
  `@extensions/ordessa.contracts/contract.js` — the contracts extension is
  `packages/desktop-platform/contracts/foundation` (manifest id `ordessa.contracts`,
  re-exporting commands+workbench, `src/contract.ts:1-2`); agent+connections contract is
  `ordessa.agent-contracts` (`contracts/agent-ui/src/contract.ts:1-2`).
- **Settings page seam**: `WorkbenchComposition`
  (`packages/desktop-platform/contracts/workbench/src/workbench.ts:37-46`) —
  `forScope(scope).addModule(WorkbenchModule)` (`:8-15`), `addOverlay` (`:19-22`),
  `addSettingsSection(WorkbenchSettingsSection{id,title,order,component})` (`:25-30`, `:41`),
  `openSettings(sectionId?)` (`:45`); exposed as optional
  `Workbench.composition` (`:56-57`); implemented in the product:
  `plugins/workbench/src/model.ts:120-130` (`composition` incl. `addSettingsSection`) and
  `openSettings` (`:108-117`); `WorkbenchToken` (`workbench.ts:59`).
- **Concrete example plugin** doing view/UI contribution: `plugins/agent/conversation`
  (`src/entry.tsx:6-13`); settings-section contributions exercised in
  `plugins/workbench/tests/composition.test.tsx:178,385,403-404` (no product plugin
  contributes one yet).
- Product assembly is a locked list: `products/desktop/extensions.json` (+
  `extensions.lock.json` content hashes); adding an extension id is C0-owned
  (`specs/011-plugin-rollout/plan.md` §C0 独占 `products/**`).

### Missing

- ❌ **Profile-editor section contribution point**: no profile editor UI exists anywhere
  in this tree (grep `profile` in `apps/desktop/renderer`, `plugins/workbench`,
  `plugins/agent` finds only wire-client usage in connector tests). The first editor UI
  ships with Z1; Q1's "Profile editor 登记 Skill 选择区" needs Z1 to expose a section
  slot (request G6, owner Z1).
- ❌ Workbench project-context registration point — explicitly out of scope for v1
  (`docs/design/skills-v2/contracts.md:23`).

### Q1 can build today

The full Settings page (content library, sources, global + project assignments with a
project picker fed from `workspaces.list`) as a `WorkbenchModule` + `addSettingsSection`
contributor against `@ordessa/extension-api` / contracts, unit-tested with the fixtures in
§7; wiring it into `products/desktop` is the C0 integration request.

---

## 7. Test / conformance fixtures already provided

### Exists

- **In-process Server harness**: `build_runtime(data_root, server_plugins=…)`
  (`apps/server/src/ordessa_server/bootstrap/runtime.py:420-433`) — explicit sequence
  composes exactly those plugins; `()` is the sanctioned bare host
  (`runtime.py:442-447`); activation failure releases the data-root lock (`:528-532`).
  Direct host objects importable: `ServerPluginHost`, `MethodRegistry`,
  `StreamRouteRegistry`, `HttpRouteRegistry` (`ordessa_server.plugin_host`,
  `host.py:61-64`); gate precedent `apps/server/tests/test_plugin_host_gate.py`.
- **Host wire vocabulary for handler tests**: `WireService` (`ordessa_server.wire.handlers`),
  `WireError` (`wire/errors.py`), `CursorCodec` (`wire/envelope.py`), param helpers
  `_require/_bounded/_version/_request_id/_assignments` (`handlers.py:27-90` — the same
  helpers workspace/compat consume, documented as "host generic vocabulary").
- **pacthold runtime composition fakes**: `pacthold.extensions.runtime_composition.fake`
  — `FakeHost`, `FakeSandbox`, `FakeTerminal`, `FakeCompositionCoordinator`
  (`packages/pacthold/src/pacthold/extensions/runtime_composition/fake.py:15-101`).
- **Harness-side skill evidence fake**: `observe_loaded_marker` accepts a
  `SKILL_LOADED:<id>:<digest>` marker "emitted by a Harness-owned fake target"
  (`plugins/harness/src/ordessa_harness/adapters/skill_observation.py:33-39`).
- **Fake ACP peers (test-local, not published)**: `apps/server/tests/fixtures/`
  (`stateful_acp_peer.mjs`, `isolation_acp_peer.mjs`, `home_probe_acp_peer.mjs`,
  `artifact_probe_acp_peer.mjs`, `shared_store_acp_peer.mjs`, `fake_mcp_server.py`,
  `fixture_native_driver.mjs`), `apps/server/tests/fake_native_acp_peer_hd002.mjs`,
  `tests/acp_orchestration/`, `tests/acp-connector/`.
- **Desktop plugin fixtures**: `runtime` from `@ordessa/extension-host`, `OwnedResources`
  and `Contributions` from `@ordessa/extension-api` (`index.ts:6-37`, `contributions.ts`),
  factory functions `createCommands` (`plugins/commands/src/entry.ts:4`) and
  `createWorkbench` (`plugins/workbench/src/model.ts`) — the pattern used by
  `apps/desktop/renderer/foundation.test.tsx:4-9` and
  `plugins/workbench/tests/composition.test.tsx`. Vitest configs:
  `apps/desktop/vitest.config.ts`, `plugins/workbench/vitest.config.ts`.

### Missing

- ❌ A published **conformance fixture package** for plugin authors ("统一 conformance
  fixtures" is assigned to C0, `specs/011-plugin-rollout/plan.md:23` — not delivered; no
  checkpoint JSON exists). Today each suite reconstructs the harness inline; `conftest.py`
  files (`apps/server/tests/conftest.py`, `plugins/harness/tests/conftest.py`) only do
  sys.path/presence plumbing.

### Gap (request G7, owner C0)

Caller: Q1 tests. Desired: a published `harness`/plugin conformance kit exposing the
fake ACP peer + bare-host composition + `SkillLoadedEvidence`-style target as importable
fixtures (not test-dir files). Failure expectation carried from design: fake-green guards
(no loaded without marker/digest evidence). Q1 ships its own pytest fixtures against
`build_runtime(server_plugins=…)` meanwhile; only cross-domain conformance waits on C0.

---

## Gap register (for `api-requests.md`)

| # | Owner | Gap (missing symbol/surface) | Q1 caller | Blocking? |
| --- | --- | --- | --- | --- |
| G1 | C0 | Plugin selection seam: `SkillsServerPlugin` inclusion in `ServerProductComposition.default_plugins` (`products/server/src/ordessa_server_product/composition.py:40-55`) or a published contribution group merged at `runtime.py:514-527`; plus compat `assets.*` retirement ledger (`test_server_compat_boundary.py:33-49`) | `plugin.py` registration | Blocks product wiring; not development |
| G2 | C0 | `harness.configuration-adapters` v1 + `IntentSet` (`MountContent`/`RemoveOwnedContent`/…) + `harness.configuration` port (inspect/plan/apply/query/reconcile) + loaded-observation API — target names per `docs/design/harness-v2/contracts.md:26-77`, none in code | `harness_adapters/` | Blocks plan step 4 (brand apply) |
| G3 | Z1 | Profile facet `assets.skills` write/read public API, session item override public API, revision identity tuple, `server_profile_assets`→`enable(revision)` migration contract | `profile_contribution/` | Blocks plan step 3 Profile leg |
| G4 | Z2 (+C0 for ACP route) | Chat `/` and `+` contribution registry accepting `SkillChoice`; explicit native invocation routing; snapshot-generation guard | `frontend/` chat glue | Blocks plan step 5 menu; browsing-only fallback honest |
| G5 | C0 | serverScope/principal statement or auth context on method handlers (today: bearer-token single user; `contract.py:71` params-only handlers) | `assignments/` | Non-blocking; document semantics |
| G6 | Z1 | Profile-editor section contribution slot (editor itself does not exist yet); Settings sections seam itself is READY (§6) | `frontend/` profile section | Blocks only Skill-in-profile-editor |
| G7 | C0 | Published conformance fixture package (fake peers / in-process composition helpers) | `tests/` | Non-blocking; Q1 self-fixtures |

## Seams Q1 can build against today (no dependency)

`server_plugin_api` full contract (§1) · bare-host `build_runtime(server_plugins=…)` test
loop (§7) · host storage ports (`database/objects/idempotency/notifier/data_root/assets
root`) · `server_assets`/`server_profile_assets` schema & `SkillAssetStore` digest
semantics for the migration ledger (§3, §5) · `workspaces.*` methods + `workspace.service`
port with stable `ws_…` IDs (§5) · `WorkbenchComposition.addModule/addSettingsSection` +
`CommandsToken` desktop seams (§6) · extension-api `Contributions`/`Token`/scope
discipline and the `createWorkbench`/`createCommands` test factories (§7) ·
`observe_loaded_marker` evidence shape for offline load proofs (§2).
