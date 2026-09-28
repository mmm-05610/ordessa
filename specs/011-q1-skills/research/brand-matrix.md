# Brand capability matrix — what THIS repo proves (Q1 Skills v2 / T02 groundwork)

Compiled 2026-09-29 (read-only survey of worktree `011-q1-skills`). Every claim carries a
`file:line` (or file for JSON schema artifacts). Vendor-doc facts are NOT treated as capability;
they live in `docs/design/skills-v2/harness-adapters.md` and `research-and-reuse.md`.
Cells without in-repo evidence say **unknown — no in-repo evidence**.

All paths below are relative to the worktree root
`/home/maoqh/projects/ordessa/worktrees/011-q1-skills/`.

## 1. Toolchain / version pins found in-repo

| Item | Pinned value | Where pinned |
| --- | --- | --- |
| Go toolchain (bridge) | 1.24.13 linux-amd64, build reproduces digest `5fd6a37b…` | `docs/baseline.md:15,17` |
| Pi native coding agent | `@earendil-works/pi-coding-agent` **0.84.2** (inside packaged pi-acp closure) | `plugins/harness/packaging/pi/package-lock.json:45-46,538-547` |
| Pi ACP adapter | `@automatalabs/pi-acp` **0.5.0** | `plugins/harness/packaging/pi/package.json:9,13`; `plugins/harness/src/ordessa_harness/pi/production.py:76-77`; `harnesses.toml:377`; vendored tgz `plugins/harness/packaging/pi/vendor/automatalabs-pi-acp-0.5.0.tgz` |
| Pi adapter ACP-SDK drift | pi-acp 0.5.0 declares `@agentclientprotocol/sdk` 1.4.0; root overrides to 1.3.0 — registered inherited red | `plugins/harness/tests/install/test_acp_schema_drift_target.py:15,23`; `docs/known-issues.md:13` |
| Pi native run-chain resolution | PATH-only, **no native version pin in the run chain** (`version = "2.0"` is registry metadata) | `plugins/harness/src/ordessa_harness/harnesses.toml:393,396` |
| Codex native CLI | **0.147.0** (first-hand comment + constant) | `plugins/harness/src/ordessa_harness/codex/production.py:88` (`CODEX_CLI_VERSION`), `harnesses.toml:34-35`, `codex/production.py:331` |
| Codex ACP adapter | `@agentclientprotocol/codex-acp` **1.1.14** | `plugins/harness/packaging/codex/package.json:9,13`; `codex/production.py:85-86`; vendored tgz `packaging/codex/vendor/agentclientprotocol-codex-acp-1.1.14.tgz`; npx pin `third_party/harness_remote/bridge/src/harness-profiles.js:139` |
| Claude ACP adapter ("official pinned ACP runtime") | `@agentclientprotocol/claude-agent-acp` **0.81.2** — replaced the Go Claude mode (commits `e30f5ff6df` "Retire duplicate Go Claude adapter in favor of pinned official ACP runtime", merge `cd7d31f3cf`) | `plugins/harness/packaging/claude/package.json:13,16`; `plugins/harness/src/ordessa_harness/claude/production.py:66-67`; `harnesses.toml:94`; `plugins/harness/packaging/claude/PROVIDER-SESSION-PROBE.md:3`; `plugins/harness/adapters/acp-adapter/docs/DECISIONS.md:68` |
| Claude embedded SDK | `@anthropic-ai/claude-agent-sdk` **0.3.280** (+ platform CLI binaries) | `plugins/harness/packaging/claude/package-lock.json:24,42-56` |
| Claude CLI first-hand | **2.1.274** (comment-only first-hand observation; no pin constant) | `harnesses.toml:111-113` |
| Runtime artifact digests | Claude runtime artifact `sha256:03324c05…` built outside Git | `plugins/harness/packaging/claude/PROVIDER-SESSION-PROBE.md:28-29` |
| ACP test rig SDK | `@agentclientprotocol/sdk` 1.5.0 (tests/acp-connector, standalone) | `docs/known-issues.md:51` |
| Hermes / Qwen / Kilo / dsh natives (context) | 0.19.0 / 0.23.4 / 7.7.2 / 0.1.5-rc.1 | `harnesses.toml:194,257,298,344` |

**Go bridge version provenance:** codex app-server JSON schemas are regenerated from the *installed
pinned codex binary* and hash-pinned via `adapters/acp-adapter/Makefile:8-26` (`schema` /
`schema-check` + `internal/codex/schema/SHA256SUMS`); committed under
`adapters/acp-adapter/internal/codex/schema/`.

## 2. Brand matrix

### Pi

| native version | adapter version | discovery roots | project/user extra discovery | isolation method | reload/reset/resume | explicit invocation | loaded evidence | probe test IDs | status(proven/unknown) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0.84.2 in the **packaged** closure (`packaging/pi/package-lock.json:45-46`); run chain = PATH-resolved, unpinned (`harnesses.toml:396`) | `@automatalabs/pi-acp` 0.5.0 (`packaging/pi/package.json:13`; `pi/production.py:76-77`) | guest `/runtime/home/skills/{skill_id}` (`harnesses.toml:406`); `--skill-dir /runtime/home/skills` per skill + `--agent-dir /runtime/home` (`pi/projection.py:27,35`); agent home `PI_CODING_AGENT_DIR=/runtime/home/.pi/agent` (`pi/production.py:84,92`) | unknown — no in-repo evidence (project `.pi` discovery is vendor-doc only, `docs/design/harness-configuration/harnesses.md:73`) | read-only `declare_source("skill-tree", …)` mounts (`adapters/generic_cli.py:35`; `packages/pacthold/src/pacthold/extensions/runtime_composition/protocol.py:307`); real OS sandbox (bwrap) port is retired — only `runtime_composition/fake.py` port exists in-tree → declaration-proven, enforcement-unknown | reload: unknown — no in-repo evidence (`/reload` is vendor-doc, `docs/design/skills-v2/harness-adapters.md:11`). resume: **observed** — same native id via `session/load` journal (`tests/test_capability_declarations.py:134-137`; `harnesses.toml:376-388,423-426`); CLI `--session` injection (`pi/projection.py:29-33`) | unknown — no in-repo evidence (`/skill:name` is vendor-doc, `harnesses.md:80`); the pi-acp 0.5.0 bundle contains **zero** "skill" strings (inspected `packaging/pi/vendor/automatalabs-pi-acp-0.5.0.tgz`) | **projected only.** `adapters/skill_observation.py:19-30` can emit `SkillLoadedEvidence("LOADED")` from a guest-dir digest, but it has **no callers and no tests in-repo** (repo-wide grep: only its own file + `docs/design/harness-v2/migration.md:9` which re-assigns it to Skills) | `test_capability_declarations.py::test_the_golden_matrix_declared_column_equals_the_registry` (:510), `::test_the_golden_matrix_observed_column_matches_the_contract_levels` (:518); `tests/install/test_acp_schema_drift_target.py::test_the_acp_schema_a_closure_carries_satisfies_the_adapter_that_needs_it` (:190) | adapter pin **proven**; skill discovery/loading **unknown** (no brand loader observation exists in-repo) |

### Codex

| native version | adapter version | discovery roots | project/user extra discovery | isolation method | reload/reset/resume | explicit invocation | loaded evidence | probe test IDs | status(proven/unknown) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| **0.147.0** (`codex/production.py:88`; first-hand comments `harnesses.toml:34-35`, `codex/production.py:331`) | `@agentclientprotocol/codex-acp` **1.1.14** (`packaging/codex/package.json:13`; `codex/production.py:85-86`; `harness-profiles.js:139`) | guest `/runtime/home/skills/{skill_id}` + `CODEX_HOME` env (`harnesses.toml:32-33`; `generic_cli.py:35-38`); `CODEX_HOME=/runtime/home/.codex` pinned in adapter env (`codex/production.py:92,102-105`); Codex itself writes `sessions/`, `skills/` under the state subtree (`codex/production.py:25-27` docstring, `:321-324` stateProjection) | **protocol-declared, not exercised**: pinned-binary schema `skills/list` takes `cwds[]`, `perCwdExtraUserRoots` (extra user-scoped roots) and `forceReload` (cache bypass) — `adapters/acp-adapter/internal/codex/schema/v2/SkillsListParams.json`; but **no .go/.js code in the repo calls any `skills/*` method** (repo-wide grep zero) | ro projection of `config.toml`/`models.json` + bounded state projection with `ephemeralPaths: [".tmp","shell_snapshots"]` (`codex/production.py:260-265,321-324`); native `plugins`+`shell_snapshot` features off (`deploy/codex/config.toml:42-44`; `codex/production.py:185`); bwrap enforcement itself retired from this tree (`docs/known-issues.md:23`) | reload: `skills/changed` notification + `forceReload` exist in the vendored schema (`schema/ServerNotification.json`, `v2/SkillsConfigWriteParams.json` {enabled,path} → response {effectiveEnabled}) — **declared surface only, zero runtime calls** → unknown. resume: **observed** — same native id via `session/load` with replay (`tests/test_capability_declarations.py:100-101,110-112`); Go bridge wires `thread/resume` (`adapters/acp-adapter/internal/codex/client.go`, methods `thread/start`, `thread/resume`, `turn/start` per grep) | unknown — `SkillMetadata.command`/`SkillToolDependency.command`/`defaultPrompt` fields exist in `schema/v2/SkillsListResponse.json` (declaration); `include_skills_usage_instructions = false` in the pinned catalog (`deploy/codex/models.json:23,90`); no invocation-event plumbing in-repo | **projected only** + approval surface declared: `schema/SkillRequestApprovalParams.json` (itemId+skillName) is vendored but never handled by Go code. Old `harness_delivery.verify_load` (digest-match → "loaded") is NOT in this tree (retired; `docs/known-issues.md:27`, ruling in `docs/design/skills-v2/harness-adapters.md:16`) | `tests/test_codex_plugin.py:23` (input limit `agent-box.skill@1: (0,32)`); `test_codex_remote.py:50-75` (config/catalog bytes incl. skills flag); `test_codex_production_template.py`; `test_capability_declarations.py::test_codex_observes_exactly_what_its_production_gate_proved` (:534). NOTE: `codex-production-chain-gate.py` cited at `codex/production.py:166` and gate reports `docs/server-round1/fullstack/*.md` cited by `test_capability_declarations.py:55-69` are **absent from this worktree** | native+adapter pins **proven**; skills protocol surface **proven as schema declaration**; every runtime skill cell (discovery/reload/explicit/loaded) **unknown** |

### Claude Code

| native version | adapter version | discovery roots | project/user extra discovery | isolation method | reload/reset/resume | explicit invocation | loaded evidence | probe test IDs | status(proven/unknown) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CLI **2.1.274** — comment-only first-hand, not a machine pin (`harnesses.toml:111-113`); SDK **0.3.280** locked (`packaging/claude/package-lock.json:24,42-56`) | `@agentclientprotocol/claude-agent-acp` **0.81.2** (`packaging/claude/package.json:13,16`; `claude/production.py:66-67`; `harnesses.toml:94`). Go Claude mode retired (`DECISIONS.md:68`) | guest `/runtime/home/.claude/skills/{skill_id}` (`harnesses.toml:110`); `CLAUDE_CONFIG_DIR=/runtime/home/.claude` pins config home (`claude/production.py:74,80-84`); orphaned writer `claude/profile.py:45-46` puts `SKILL.md` at `<root>/<execution>/.claude/skills/<name>/SKILL.md` — its launcher `ClaudeLaunchAdapter` (`claude/launch.py:12`) has **no in-repo caller** | unknown — no in-repo evidence (native priority stack is vendor-doc, `harness-adapters.md:12`) | runtime-artifact mount + CLAUDE_CONFIG_DIR isolation (`claude/production.py:63-84`); provider isolation verified against **fake loopback endpoints only** (`PROVIDER-SESSION-PROBE.md:12-18`; commit `508d8f7264`) | reload: unknown — no in-repo evidence. resume: **observed** — non-replay `session/resume`, same native id (`test_capability_declarations.py` claude-code row :207-235, `checkpointNativeIdStable=true`); 0.81.2 session-scoped recreation on env/settings change proven with fake endpoints (`PROVIDER-SESSION-PROBE.md:4-6`; commit `7089c0fd5d`); `--resume` flag in orphaned launcher (`claude/launch.py:22`) | unknown — no in-repo evidence | **projected only** — the live production chain never observes a Claude skill load; the `verify_load`-as-loaded pattern is explicitly rejected (`harness-adapters.md:16`) | `test_claude_production_template.py:42` (asserts ADAPTER_VERSION=="0.81.2"); `packaging/claude/provider-session.test.mjs` + `provider-routing-smoke.mjs` (2/2 lifecycle, A=1/B=2/C=1 turn counts, `PROVIDER-SESSION-PROBE.md:15-16,27-28`) | pins + resume **proven**; every skill cell (discovery roots actually scanned, reload, explicit invocation, loaded) **unknown** |

## 3. Existing skills plumbing (current behavior)

- **`plugins/harness/src/ordessa_harness/adapters/skill_observation.py`** — frozen dataclass
  `SkillLoadedEvidence` + `observe_loaded_skill()` (guest dir SKILL.md presence + `content_digest`
  match → level `"LOADED"`, marker `SKILL_LOADED:<id>:<digest>`) and `observe_loaded_marker()`
  (fake-target marker) (`:9-39`). Evidence level: deterministic fake/native-target "LOADED",
  *claimed* only against a Harness-owned fake. **Zero callers, zero tests in-repo.**
  `docs/design/harness-v2/migration.md:9` re-assigns it to the future Skills harness_adapters.
  Writes nothing; reads a guest root only.
- **`adapters/generic_cli.py:20-38`** (shared by Pi/Codex/Claude/etc. adapters,
  `adapters/__init__.py:13`) — consumes `agent-box.skill@1` resolved inputs, refuses
  `SKILL_TARGET_UNDECLARED` / `SKILL_SOURCE_CAPABILITY_MISSING` / `SKILL_TARGET_COLLISION`,
  mounts each skill tree **read-only** at the registry `skill_target` inside the sandbox;
  sets `skill_env` to the guest home. Evidence: **projected** (mount declaration). Does **not**
  touch user HOME; host source path comes from `source.projection_source()` capability — but the
  *producer* is the retired `agent-box-skills` plugin (`docs/known-issues.md:27`): `ResolvedAgentSkill`
  appears only in a docstring (`packages/pacthold/src/pacthold/resource_contracts/agent_skill_v1.py:4`)
  and no in-tree provider yields it. The consumption path is orphaned end-to-end today.
- **`registry/schema.py:69-75,140`** — validates `skill_target` as canonical bounded template
  (`{skill_id}` required, no `..`) and input limits (0..32).
- **`pi/projection.py:26-43`** — argv `pi --agent-dir /runtime/home … --print`; repeats
  `--skill-dir /runtime/home/skills` per `profile.skill_dirs` entry (same path each time, `:35`);
  resume via `--session` (`:29-33`). `pi/config.py:92` accepts host `skill_dirs` paths with
  `expanduser()` — config-time input, not a write. Projected only.
- **`claude/profile.py:36-51`** — `ClaudeProjection.materialize` writes settings/instructions/mcp/
  **skills** into an execution-local directory under the *profile-store root* (product data dir, not
  user HOME) and a `agent-box-manifest.json` file list; `cleanup` = `shutil.rmtree`. Evidence:
  **projected** (manifest of written files). Currently uncalled in the live chain.
- **`opencode/projection.py:71-74,84`** — copies profile `config.skills` list into
  `opencode.json`, manifest declares `skills_target: "skills/"`. Projected.
- **`hermes/projection.py:18,22`** — creates `home/skills` dir and lists skills in the projection
  manifest `shared_slots`. Projected. **`hermes/production.py:231-232`** —
  `HERMES_IGNORE_USER_CONFIG=1`/`HERMES_IGNORE_RULES=1` explicitly block ambient user skills
  ("no … preloaded skills may reach a managed run", `:204-205`). Isolation precedent for the
  project/user-extra-discovery cell.
- **`plugins/server-compat/src/ordessa_server_compat/assets/skills.py`** — `SkillAssetStore`
  installs immutable `skill/<assetId>/<revision>` trees with digest `verify` under
  `context.data_root / "assets"` (`plugin.py:125,137`) — managed store, never a brand-native dir.
  Tests: `apps/server/tests/test_asset_hubs.py::test_install_publishes_one_revision_and_verifies_its_digest`
  (:64) etc.
- **`harnesses.toml` skill slots/targets** — codex `:31-33`, claude `:107,110`, opencode `:163-165`,
  hermes `:215-217`, qwen `:311,314`, pi `:405-406`; inputs contract `agent-box.skill@1` max 32
  (`:45-52` codex, `:166-173` opencode, `:218-225` hermes, `:407-414` pi — none for
  claude/dsh/kilo/qwen).
- No code anywhere writes brand skill dirs under the real user HOME; all skill targets are
  `/runtime/home` (guest) or the product data root.

## 4. Go ACP bridge (`plugins/harness/adapters/acp-adapter`)

- `internal/codex/schema/**` Skills types (`SkillsListParams/Response`,
  `SkillsConfigWriteParams/Response`, `SkillsRemoteRead/WriteParams/Response`,
  `SkillsChangedNotification`, `SkillRequestApprovalParams/Response`) are **vendored schema
  artifacts** generated by `codex app-server generate-json-schema` (`Makefile:8-11`, README.md,
  `SHA256SUMS`). Method names present in protocol: `skills/list`, `skills/config/write`
  (client requests), `skills/changed` (server notification) — `ClientRequest.json`,
  `ServerNotification.json`, `codex_app_server_protocol.schemas.json`.
- **Actual Go code uses none of them.** Repo-wide `grep -i skill --include="*.go"` → zero matches;
  no `/reload`, no `skills/*` request/response handling in `cmd/acp`, `internal/acp`,
  `internal/codex`, `internal/pi`, `pkg/*`. Methods actually wired: `initialize`, `thread/start`,
  `thread/resume`, `thread/list`, `turn/start`, `turn/interrupt`, `account/*`
  (`internal/codex/client.go` string grep).
- The Claude Go mode was deleted here (`internal/claude/`, `pkg/claudeacp/` removed, commits
  `e30f5ff6df`/`cd7d31f3cf`); the pinned official Node adapter (`claude-agent-acp` 0.81.2) is the
  only Claude path. Whether the *Node* adapters (codex-acp 1.1.14, claude-agent-acp 0.81.2,
  pi-acp 0.5.0) speak skills/* is unexamined in-repo (only pi-acp's tgz was inspected: no skill
  strings; codex-acp/claude-agent-acp tarballs are vendored/locked but their dists unsearched here).

## 5. Runtime-instance API (what a plugin can hold today)

Public/real symbols, `packages/pacthold/src/pacthold/extensions/runtime_composition/`:
- `RuntimeSourceDeclaration` / `declare_source(kind, source_path, guest_target, access="ro|rw",
  provenance, authorized_scope="execution")` — dispatch-local dir/file mount with content digest
  (`protocol.py:281-319`); this **is** the "target directory handle" primitive a projector gets.
- `HarnessCommandSpec` (argv+cwd+env+runtime_sources+projector_id) (`protocol.py:322-`).
- `assemble_runtime_composition` → `(RuntimeBinding, RuntimeCompositionCoordinator)`
  (`assembler.py:25`).
- `RuntimeCompositionCoordinator.preflight / start(execution_id, dispatch_id) / present /
  cleanup(attempt) / projection_receipt` (`coordinator.py:41,65,81,145,156`) — start/cleanup of a
  generation is the owned-content lifecycle available today.
- `SandboxPort` protocol: `compose_sidecar_room`, `declaration_document(readonly_targets…)`,
  `probe` (`sandbox_port.py:147-168`); `register_sandbox_port_factory` (`:51`). Only a
  `FakeSandbox` implementation is in-tree (`fake.py`); the bwrap port is a retired external dist
  (`docs/known-issues.md:23`) — isolation enforcement is therefore *declared but not
  in-repo-verifiable*.
- Deployment-template side (`plugins/harness/src/ordessa_harness/*/production.py`):
  `runtimeArtifactMounts` (token→target→treeDigest) (`codex/production.py:294-296,310`),
  `projectionFiles` ro writes (`:260-265`), `stateProjection{target,ephemeralPaths}`
  (`:321-324`), `sessionStore: sessions-subtree` (`:328`).
- Instance handles & resume at the harness layer: `GenericExecutionProvider.start/get_handle/
  observe/finish` returning `GenericHandle` (`generic/execution_provider.py:8-27`); typed
  continuation contracts `PiContinuationV1` (`pi/contract.py`), `CodexContinuationResourceProvider`
  (`codex/continuation.py:7-15`), `ClaudeContinuationV1` (`claude/contracts.py`, profile.py:28-34).
- **There is no "mount arbitrary content into a running instance" or "remove owned skill content"
  runtime API and no per-brand skill enable/disable API exposed to plugins today** — unknown/no
  such symbol exists; skills today exist only inside the immutable pre-start command spec.

## 6. Provable vs unknown; minimal controlled probes (no paid model call)

Proven in-repo (with IDs above):
- Native/adapter pins: Codex 0.147.0 + codex-acp 1.1.14; claude-agent-acp 0.81.2 + SDK 0.3.280;
  pi-acp 0.5.0 + pi-coding-agent 0.84.2 (packaged closure).
- Same-native-id resume for all three (FAMILY_MATRIX observed rows).
- The skill *mount grammar* (target templates, collision refusal, bounded contract) and the fact
  that nothing writes to user HOME.
- Codex pinned-binary **protocol surface** for skills (schema artifacts + SHA256SUMS).

Unknown — minimal probes to fill (each loopback/fake-endpoint, no real model):
1. **Pi skill discovery/loading**: run packaged pi 0.84.2 (`--print`) with `--skill-dir` pointing at
   a fixture skill; capture the final skill list + an explicit-invocation turn against a loopback
   fake; then `/reload` via RPC. Cells filled: discovery roots actual vs declared, `/reload`,
   `/skill:name`, loaded evidence marker. Probe home: new `plugins/harness/tests/…` id, e.g.
   `test_pi_skill_discovery_0842`.
2. **Codex skills/list runtime behavior**: launch pinned `codex app-server` (0.147.0) with
   `CODEX_HOME` at a temp dir; call `skills/list` (with and without `perCwdExtraUserRoots`,
   `forceReload`) and `skills/config/write`; assert `skills/changed` after touching a fixture.
   Also check codex-acp 1.1.14 dist for skills/* passthrough. Fills: extra discovery, reload,
   enabled-state roundtrip, loaded-vs-projected distinction.
3. **Claude skill loading**: launch pinned claude-agent-acp 0.81.2 with `CLAUDE_CONFIG_DIR` at a
   temp home containing `.claude/skills/<name>/SKILL.md`; drive one ACP turn against the existing
   loopback fake endpoints (`provider-routing-smoke.mjs` rig pattern); inspect init/system messages
   or `available_commands` frames for skill visibility; verify plugin-provided vs project-dir
   priority and whether a nested `.claude/skills` in cwd is auto-scanned. Also inspect
   claude-agent-acp dist for skills handling.
4. **Producer path**: wire/repair an `agent-box.skill@1` provider (or a fake) so
   `generic_cli.py:20-35` is exercised end-to-end in a fake-sandbox composition test — proves the
   Ordessa→guest投放 leg; currently only unit-level refusals exist.
5. **Loaded-evidence machinery**: `skill_observation.py` needs at least one test with a
   fixture guest root + one real adapter target to prove/reject its "LOADED" claim level.
6. **Gate-report gap**: `docs/server-round1/fullstack/*.md` and `codex-production-chain-gate.py`
   cited by `test_capability_declarations.py`/`codex/production.py:166` are absent from this tree —
   re-locate them (`docs/reference-index.md`) or re-run gates before citing them as evidence.
