# Legacy Skills inventory — implementation-baseline input for Q1

Research artifact for workstream Q1 (Skills v2). READ-ONLY inventory.

- Legacy tree: `git show 752f148b1b01f58c0d090e79728948127173f9fb:<path>` (commit exists only in the object graph; all `plugins/assets/**` line quotes below are from blobs at that commit, not from the working tree).
- Current tree: working tree `codex/011-q1-skills` @ `96fef2db47` ("Prepare Spec Kit plugin rollout for Codex, ZCode and Qoder").
- Verified fact: `git diff --stat 752f148b1b HEAD -- plugins/server-compat/.../assets/ core_wire.py plugin.py profiles/clone.py packages/.../agent_skill_v1.py apps/server/tests/test_asset_hubs.py` is EMPTY — the compat surface did not drift between the legacy commit and HEAD.
- Anything not directly observed is marked **NOT VERIFIED**.

---

## A. Legacy package `plugins/assets/` @ 752f148b1b

### A.1 Package metadata (`plugins/assets/pyproject.toml`, 23 lines)

- Package name `ordessa-assets`, version `2.0.0a1` (pyproject.toml:6-7); description "Ordessa Assets domain: versioned skill content, bounded import, auditable projection" (:8).
- `requires-python = ">=3.9"` (:9); license MIT text (:10).
- Dependencies: `pacthold==2.0.0a1`, `PyYAML>=6,<7` (:11-14). Optional `dev = ["pytest>=7"]` (:16-17).
- setuptools find `where=["src"]` (:19-20); pytest `testpaths=["tests"]` (:22-23).
- **No entry points of any kind** — no `[project.entry-points]` section exists. Import package: `ordessa_assets`.

### A.2 Source modules by area (path : lines)

formats/agent_skills (the internal kind handler):
- `src/ordessa_assets/formats/__init__.py` : 2
- `src/ordessa_assets/formats/agent_skills/__init__.py` : 1
- `src/ordessa_assets/formats/agent_skills/frontmatter.py` : 134
- `src/ordessa_assets/formats/agent_skills/tree.py` : 49
- `src/ordessa_assets/formats/agent_skills/validator.py` : 85

library (called "server" area in legacy):
- `src/ordessa_assets/server/__init__.py` : 1
- `src/ordessa_assets/server/store.py` : 129
- `src/ordessa_assets/server/records.py` : 216
- `src/ordessa_assets/server/catalog.py` : 190
- `src/ordessa_assets/server/import_transfer.py` : 238
- `src/ordessa_assets/server/projection.py` : 208
- `src/ordessa_assets/server/service.py` : 174

contracts (pure types):
- `src/ordessa_assets/contracts/__init__.py` : 1
- `src/ordessa_assets/contracts/errors.py` : 41
- `src/ordessa_assets/contracts/evidence.py` : 30
- `src/ordessa_assets/contracts/identity.py` : 63
- `src/ordessa_assets/contracts/ports.py` : 50

harness_delivery (optional adapter):
- `src/ordessa_assets/harness_delivery/__init__.py` : 4
- `src/ordessa_assets/harness_delivery/capabilities.py` : 14
- `src/ordessa_assets/harness_delivery/delivery.py` : 82

profile_contribution (optional adapter):
- `src/ordessa_assets/profile_contribution/__init__.py` : 4
- `src/ordessa_assets/profile_contribution/binding_facet.py` : 55

root: `src/ordessa_assets/__init__.py` : 8 (domain docstring, cites `docs/specs/assets-skill/design.md` §4).

desktop (extension `ordessa.assets`):
- `desktop/build.mjs` : 2, `desktop/manifest.json` : 1 (`{"id":"ordessa.assets","version":"0.1.0","hostApi":"2","entry":"entry.js"}`), `desktop/package.json` : 11 (npm name `@ordessa/plugin-assets`, script `vitest run --maxWorkers=1`), `desktop/src/api.ts` : 68, `desktop/src/entry.tsx` : 36, `desktop/src/model.ts` : 141, `desktop/src/view.tsx` : 111, `desktop/src/wireGateway.ts` : 93, `desktop/tests/assets.test.tsx` : 123, `desktop/vitest.config.ts` : 8.

plugin registration: **there is NO plugin-registration module in the legacy tree.** No `plugin.py`, no entry points; the wire takeover was documented for a later "integration wave" (`specs/003-assets-skills/contracts/wire-compat.md` §1-§3, quoted in A.6). Closest artifacts: `tools/check_assets_boundaries.py` (127 lines; `AREAS` tuple at :23, `ADAPTERS` at :24, `check_tree(root)` at :88, `main(argv)` at :116) and the desktop `manifest.json` id above.

### A.3 Key public symbols (legacy)

contracts/errors.py — `AssetDomainError(code, message, *, detail=None)` (:10); subclasses `SkillAssetError` (:20), `CatalogError` (:24), `BindingError` (:28), `ImportError_` (:32), `ProjectionError` (:36), `PreviewError` (:40). Codes are stable strings, e.g. `SKILL_FRONTMATTER_MISSING`, `SKILL_REVISION_EXISTS`, `IMPORT_CONTENT_DRIFTED`, `ASSET_NOT_FOUND`, `CAPABILITY_UNKNOWN`.

contracts/evidence.py — levels `STORED/SELECTED/PROJECTED/LOADED/UNKNOWN` (:9-13), `USED = UNKNOWN` constant (:16), `LADDER` (:19), `UNCONFIRMED` (:22), `highest(*levels)` (:25).

contracts/identity.py — `ASSET_KINDS = ("skill","mcp","command","plugin")` (:10), `ASSET_ID` regex (:12), `SKILL_NAME` regex (:13), bounds `MAX_ASSET_ENTRIES=512` / `MAX_ASSET_BYTES=32MiB` / `MAX_FRONTMATTER_BYTES=64KiB` / `MAX_DESCRIPTION_CHARS=1024` / `MAX_COMPATIBILITY_CHARS=500` (:17-21); frozen dataclass `SkillRevisionFacts` (:24) with `public_dict()` emitting camelCase keys `assetId/revision/treeDigest/name/description/metadata/retainedFields/fileCount/totalBytes/scripts/source` (:40-53).

contracts/ports.py — Protocols `SkillBindingFacet` (:15, methods `bindings_view`, `effect_view`), `ProfileRegistrationPort` (:23, `publish_skill_binding_facet`), `HarnessCapability` (:30, fields `harness, skill_mechanism, session_reload, evidence, progressive_disclosure, context_cap_bytes`), `HarnessDeliveryPort` (:39, `capability/project/load_evidence`).

formats/agent_skills/frontmatter.py — `_FRONTMATTER` fence regex (:24); `_StrictSafeLoader(yaml.SafeLoader)` refusing duplicate keys (:27, constructor `_construct_mapping` :31); `FrontmatterFacts(name, description, metadata, retained, body)` (:49); `parse_frontmatter(text, *, directory_name=None) -> FrontmatterFacts` (:82) enforcing name slug ≤64, name==directory_name when given, description ≤1024, metadata str→str only, compatibility 1-500, license/allowed-tools strings, retaining unknown legal fields (:131-132).

formats/agent_skills/tree.py — `TreeEntry(relative, size, path)` (:12); `scan_tree(root)` (:19): os.walk followlinks=False, symlink dirs/files/FIFO refused as `SKILL_ASSET_INVALID`, entry/byte budget charged while walking (`SKILL_ASSET_OUTSIDE_BOUNDS`) (:43-47).

formats/agent_skills/validator.py — `MAX_PREVIEW_FILE_BYTES = 256*1024` (:14); `ValidatedSkill(facts, entries, total_bytes, scripts)` (:17); `_script_markers` (files under `scripts/` or with exec bit) (:25); `validate_skill_directory(root, *, directory_name=None)` (:37); `file_preview(entry, root)` bounded text row, binaries path/bytes only (:61); `assert_regular_within(root, relative)` path-escape guard (:75). Note (:84-85): `_ = os.fspath(target)` is a no-op leftover.

library — server/store.py: `SkillRevisionStore(root)` (:22); `revision_dir` = `<root>/skill/<asset_id>/<revision>` (:28-29); `install(source, *, asset_id, revision, directory_name=None, source_ref="local:import")` staging+chmod 0o644+`runtime_artifact_tree_digest`+`os.rename`, files read from pacthold digest helper (:31-84); `verify` (:86), `revision_digest` (:93), `read_metadata` (:99), `list_revisions` (:116). Disk layout claimed byte-compatible with server-compat store (:3-4).

server/records.py: `now()` (:23), `opaque_id(prefix)` → `asset_<uuid-hex>` (:27), `asset_view(row)` camelCase wire view (:31); `AssetRecords(database)` (:46) with `publish(*, kind, name, revision, digest, description=None, source=None, asset_id=None)` (:50, requires `sha256:` digest :60, INSERT/UPDATE on `server_assets` :77-87), `get` (:90), `list` (:98), `bind(*, profile_id, asset_id, revision=None, enabled=True)` pinning latest-at-bind-time when omitted (:104-131, upsert on `server_profile_assets`), `update_binding` (:134), `unbind` (:160), `bindings(profile_id, *, enabled_only=False)` (:168). review-record §6 accepts the legacy read-then-write TOCTOU pattern of bind/update_binding as MINOR.

server/catalog.py: `KINDS = ("skill","mcp")` (:19); `parse_index(content)` validating `schema_version==1`, ≤512 entries, ≤1MiB, per-entry keys `{kind,name,path,origin,description}`, canonical-JSON sha256 digest (:25-78); `CatalogStore(root)` (:81) with `snapshot_path` = `<root>/<source_id>/index.json` (:87), `sync` staging+`os.replace` (:92), `snapshot` (:121), `annotate` installed flags (:127), `install_entry(...)` skill-kind only, provenance pinned as `<snapshot digest>:<origin>` (:138-174), `payload_path` containment check (:176).

server/import_transfer.py: `MAX_CHUNK_BYTES = 256*1024` (:26), `PREVIEW_TEXT_BYTES = 256*1024` (:27), `SESSION_TTL_SECONDS = 3600` (:30); session states `_PENDING/_RECEIVED/_PREPARED/_COMMITTED/_ABORTED` (:32-36); `ImportService(root, records=None, store=None)` (:43) with constructor-time orphan sweep `_sweep_expired` (:54), `begin(*, request_id, files, total_bytes)` (request_id deliberately unused; wire layer owns replay :70), `chunk(import_id, *, index, payload, sha256)` (:96), `prepare(import_id, *, source)` returning preview incl. `treeDigest/scripts/retainedFields` (:121-147), `commit(import_id, *, asset_id, revision)` re-verifying staged digest (`IMPORT_CONTENT_DRIFTED`) and returning `effect:"stored"` (:149-187), `abort` idempotent (:189), `preview` (:197). Sessions live in memory (`self._sessions`) — no DB persistence.

server/projection.py: marker regex `SKILL_LOADED:<asset-id>:sha256:<64hex>` (:21); `normalize_statement` validating capability statement keys against `_CAP_KEYS` (:23-51); `ProjectionLedger(root)` (:58) JSONL-persisted at `<root>/projections/log.jsonl` (:191), methods `capability` (:74), `capability_of` (:79), `record_projection` (:86), `record_loaded` (only door to LOADED; requires capability with evidence≠none + exact marker :105-130), `effect_view` (full ladder keys, `used` pinned to unknown, `unconfirmed` flag :134-172), `next_turn_allowed` FR-PROF-2 session-reload gate (:174-181); helper `facts_for` (:205).

server/service.py: `MAX_PREVIEW_BYTES = 256*1024` (:21); `AssetsService(root, database=None, ledger=None)` (:24) composing store/records/catalog/import_service/ledger (:26-32); `list_assets` (:36), `revisions` (:41), `skill_preview` bounded textual preview with script flag (:44-67), `diff(*, asset_id, from_revision, to_revision)` existence/bytes/sha256 map diff (:69-82, `_file_map` :140), `discovery_view(*, profile_id=None, harness=None)` metadata-only rows + disclosure caps (:86-132), `external_discovery(source)` read-only `source.list_skills()` (:154), `import_external(source, *, external_id, asset_id)` explicit import at revision 1 (:162).

harness_delivery/capabilities.py: `CAPABILITIES: dict[str, dict] = {}` — **intentionally empty registry** (:10); `statement_for(harness)` (:13). Docstring: every brand starts unconfirmed until controlled evidence lands.

harness_delivery/delivery.py: `HarnessDelivery(*, ledger, store, guest_root)` (:22); `project(session_ref, *, harness, asset_id, revision, target)` — copies revision into managed guest root, chmod 0o444/0o555, digest-verifies copy before recording PROJECTED, refuses escaping targets (:29-63); `verify_load(session_ref, *, harness, asset_id, revision, target)` — digest-checks the guest-side tree then records LOADED (:65-82). NOTE: `verify_load` itself re-derives the digest and calls `record_loaded`; the new design (research-and-reuse.md, 投影/证据 row) explicitly flags "摘要匹配就记 loaded 的假证据" for correction in v2.

profile_contribution/binding_facet.py: `SkillBindingFacetImpl(service)` (:15) with `bindings_view(profile_id)` (:20), `effect_view(profile_id, session_ref, *, harness=None)` separating selected/loaded/used (:25-44), `publish_to(port)` no-op when Profile plugin absent (:46-52), `close()` UI-only removal (:54).

desktop/src/api.ts — `AssetsGateway` interface (:52-68): `listSkills, revisions, previewFile, diff, listBindings, profiles, bind, unbind, importBegin, importChunk, importPrepare, importCommit, importAbort`; view types `SkillSummary/RevisionRow/BindingRow/EffectRow/PreviewFileRow/ImportPreview/CommittedImport/PickedFile`.
desktop/src/wireGateway.ts — `createWireGateway(wire: WireCaller)` mapping to `assets.list/revisions/skillPreview/diff/bindings/profileFacets/bind/unbind/importBegin/importChunk/importPrepare/importCommit/importAbort` (line refs :18-105 of the file). `assets.profileFacets` (:51) does **not** exist in wire-compat.md §1/§2 nor anywhere in either tree — the desktop extension was never wired to a real server (matches PARTIAL blocker 7).
desktop/src/model.ts — `ImportPhase` state machine (`idle/transferring/prepared/committed/failed`), `AssetsSnapshot`, `AssetsModel` (`subscribe/getSnapshot/refresh/select/importPicked/confirmImport/cancelImport`), client-side `sha256Hex` via `crypto.subtle` (:29-32 area of the file).

### A.4 Legacy tests (13 files, 69 test functions, 0 skips/xfails)

No `skip/xfail/mark("skip`) occurrences in any legacy test file (grep of all 13 files at the commit). Guarantee IDs below are a best-effort mapping onto `docs/design/skills-v2/verification.md` G01–G22 (lines 6-27); legacy tests were written against AC-1..AC-7 of specs/003, not against G-IDs.

| file (: lines) | test fns | apparent G coverage |
| --- | --- | --- |
| tests/test_absence.py : 64 (3) | 3 | G20 (plugin/adapter absence tolerated; facet unload keeps records) |
| tests/test_boundary_gate.py : 65 (5) | 5 | architectural guard for G20/G22 (import direction AST checks; incl. real-tree check :17) |
| tests/test_catalog_snapshot.py : 106 (5) | 5 | G04 (install never moves bindings), G03-adjacent (snapshot atomicity, provenance pin) |
| tests/test_delivery.py : 97 (3) | 3 | G16 (selected→materialized→loaded ladder; tampered target cannot become loaded; guest-root escape refusal) |
| tests/test_discovery_view.py : 117 (4) | 4 | G02 (metadata-only discovery, bounded text preview, diff), G11-adjacent (external source read-only until explicit import) |
| tests/test_frontmatter_spec.py : 108 (11) | 11 (4 parametrized) | G01 (format fidelity incl. retained nested metadata) |
| tests/test_import_session.py : 186 (7) | 7 (1 parametrized) | G03 (chunk digest refusal, preview-then-commit drift, atomic failure, TTL sweep of dead-process staging) |
| tests/test_isolation.py : 68 (3) | 3 | G09/G13-adjacent (session_ref-scoped loaded evidence; two profiles opposite pins) |
| tests/test_no_execution.py : 88 (3) | 3 | G02/G03 (AST no-execution primitives; scripts copied as bytes, never run) |
| tests/test_projection_evidence.py : 118 (9) | 9 | G16 (unconfirmed ceiling, marker-only promotion), G10/G13 (capability statement, next-turn session-reload refusal) |
| tests/test_records_pinning.py : 96 (7) | 7 | G04/G08 (bind pins latest-at-bind-time; new revision never moves bindings; explicit update) |
| tests/test_store_atomic.py : 82 (5) | 5 | G01 (digest==tree digest, tamper detection, no half-landed installs) |
| tests/test_tree_bounds.py : 69 (4) | 4 | G02 (symlink/FIFO/entry/byte bounds refusals) |

No legacy coverage exists for: G05/G06 (six-layer assignment resolution, tri-state overrides), G07 (project/authorized scoping), G11/G12 (managed vs native discovery split, name-conflict pre-rejection), G14/G15 desktop state coverage beyond 8 vitest cases, G17/G18 (Chat menu/commit-freeze flow), G19 (real-brand L3 enable/update/remove chains), G21 (install/build gates), G22 (per-ID suite diffing — partially embodied by shared-suites-ledger practice).

Desktop tests: `desktop/tests/assets.test.tsx` — 3 `describe` blocks (:55, :88, :112), 8 `test(...)` cases; evidence ledger records `npx vitest run` = **7 passed** for this file (see A.5 discrepancy note; the recorded run predates the current file state).

### A.5 Recorded verdicts / evidence at 752f148b1b (quotes verbatim)

`specs/003-assets-skills/evidence/red-run.md` (command: `python -m pytest plugins/assets/tests -q`):
- `E   ModuleNotFoundError: No module named 'ordessa_assets.server.service'` (×2), `'ordessa_assets.server.catalog'`, `'ordessa_assets.formats.agent_skills.frontmatter'`, `'ordessa_assets.server.projection'`, `'ordessa_assets.server.store'` (×2), `'ordessa_assets.harness_delivery.capabilities'`, `'ordessa_assets.server.records'`, `'ordessa_assets.formats.agent_skills.tree'`.
- `ERROR test_absence.py / test_catalog_snapshot.py / test_discovery_view.py / test_frontmatter_spec.py / test_isolation.py / test_no_execution.py / test_projection_evidence.py / test_records_pinning.py / test_store_atomic.py / test_tree_bounds.py`
- `10 errors in 0.11s`; prose: "10 个域测试模块在实现存在前即失败" + "边界门禁（基础设施）同命令绿：5 passed".
- Exit codes: **NOT VERIFIED** (not recorded in the evidence files).

`specs/003-assets-skills/evidence/green-run.md` (same command):
- ```89 passed in 0.45s``` ; prose: "89 passed（含 boundary 门禁 5 条、合成违例反例与 staging 清扫反例）".
- Internal inconsistency (verbatim): comparison table row says `10 模块 ModuleNotFoundError | 全部收集并 88 通过` — **88 vs 89 conflict inside one file**; review-record.md resolves it: "域测试：89 passed（追加 sweep 反例后）".

`specs/003-assets-skills/evidence/review-record.md` (T11 review):
- Review deviation: "独立审阅子代理因平台配额限制（"exceed quota limit"，三次尝试）不可用，由 lead 按同一审查清单执行并留痕" — no true second-opinion review happened.
- FIXED finding: "ImportService 原只实现显式 abort，缺协议承诺的重启孤儿清理（TTL 1h）——已实现构造期 sweep + 反例测试".
- MINOR (accepted): assetId derived heuristically from name in the wizard; bind/update_binding keep the legacy two-phase read-write TOCTOU shape.
- Lane facts: only two files outside the lane touched — `package-lock.json` (+7 lines workspace registration) and `products/desktop/extensions.lock.json` hash drift, "已还原".
- AC status: "AC-5 的真实品牌证据为 PARTIAL（已在 §PARTIAL 登记）".

`specs/003-assets-skills/evidence/shared-suites-ledger.md` (2026-09-27):
- Command: `python -m pytest apps/server -q   # HEAD(0e0cc2ad) 与基线 82d807364a 各跑一次`
- Result verbatim: `HEAD: 90 failed / 670 passed / 10 skipped / 158 errors`; `base: 完全相同的失败/错误 ID 集合（248 条）`; `diff /tmp/base-ids.txt /tmp/assets-head-ids.txt   # 0 行差异`. Conclusion: "本特征分支对 apps/server 套件零影响（新增失败 0，修复 0）"; inherited red attributed to "环境工件缺失相关（worker 二进制/旧命名路径 ABSENT)". Note: **no individual failing test IDs are enumerated in this file** — only the aggregate counts — so per-ID reasons are NOT VERIFIED here (they live in `docs/known-issues.md`-style baselines).
- `harness：2F/308P/3S — 与 docs/baseline.md 及 docs/known-issues.md 第 13 行继承项同 ID。` `pacthold：238P，GREEN_NO_SKIPS。`
- Desktop gates: `npm ci` needs workspace registration (lockfile +7 lines); `npm run typecheck` 通过; `npx vitest run`（plugins/assets/desktop）：**7 passed**; `npm test`：**146 passed / 13 files**; `npm run build`：**Built 9 enabled extensions**（与基线相同；`ordessa.assets` 未入产品清单，仅被发现不启用——集成波项）.

`specs/003-assets-skills/tasks.md` — delivery verdict: "**PARTIAL** —— 本树可独立完成的全部条目均有可复现证据；其余条目被明确的外部依赖阻断". All T1–T12 checked `[x]`. Blockers table (summarized, exact text in the file):
1. `ordessa-assets` 未进入 Server 插件宿主注册 — blocked by coordination §Sequential convergence 2（本波禁写 `apps/server`、`server-compat`）。
2. `server-compat` 旧 `assets.*` 未退役/禁双注册 — 同上。
3. 产品清单未启用 `ordessa.assets` — 本波禁写 `products/desktop`。
4. Pi/Codex/Claude 真实品牌装载证据（AC-5 前半）— 需受控 Harness 目标与真实运行授权；机制侧仅 fake 目标测试证明。
5. 投影记录入 SQLite — 共享 schema 变更需迁移评审（宪法 III）。
6. 独立审阅第二意见 — 子代理配额 "exceed quota limit" 三次尝试失败。
7. 桌面扩展与真实 Server wire 连线 — 共享 AgentClient 契约不暴露通用 wire 调用。
- Discrepancy: T6 plans `server/import_transfer.py` + `server/staging.py`（"ImportSession 状态机"）— **`staging.py` does not exist in the delivered tree**; the state machine lives inside `import_transfer.py`. Quote tasks.md:18: "`server/import_transfer.py` + `server/staging.py`（ImportSession 状态机，按 contracts/import-protocol.md）".
- Exit codes for any command: **NOT VERIFIED** (evidence files record outputs and counts but never an exit code number).

### A.6 Legacy wire-compat plan (`specs/003-assets-skills/contracts/wire-compat.md`)

Takeover table §1 keeps `assets.list/publishSkill/bind/unbind/bindings/syncCatalog/catalog/installFromCatalog` for ordessa-assets and explicitly leaves `assets.publishMcp / assets.publishPlugin / assets.probe` in server-compat ("不属于 003 范围"). §2 defines 15 NEW methods: `assets.importBegin/importChunk/importPrepare/importCommit/importAbort/revisions/updateBinding/skillPreview/diff/projection/projectionRecord/loadedEvidence/harnessCapability/externalDiscovery/importExternal`. §4 red lines: disk IDs, `sha256:` digests, `server_assets`/`server_profile_assets` behavior, camelCase wire field names, and `assets.bind` without `revision` (pins latest-at-bind-time) all preserved.

Mapping legacy → new layout (`docs/design/skills-v2/plan.md:9-16`): `contracts/*` → `api/`; `formats/agent_skills/*` → `formats/agent_skills/` (直接迁); `server/{store,records,catalog,import_transfer}.py` → `library/`; `server/service.py` → split (skill management stays one service; generic Assets façade/mcp/command/plugin NOT into Skills per research-and-reuse.md 旧 AssetsService row); `server/projection.py` + `harness_delivery/{capabilities,delivery}.py` → `harness_adapters/` (concept only; actual writes move to Harness, false-evidence path removed); `profile_contribution/binding_facet.py` → `profile_contribution/`; desktop → Settings contribution; `assignments/` and `native_discovery/` have **no legacy predecessor** (new scope-resolution code is the "新增核心" per research-and-reuse.md closing paragraph); `plugin.py` (registration) likewise has no legacy predecessor (A.2).

---

## B. Current tree (codex/011-q1-skills @ 96fef2db47)

### B.1 What exists today

`plugins/server-compat/src/ordessa_server_compat/assets/` (identical to 752f148b1b, see header):
- `__init__.py` : 7 — "Order 58: managed skill and MCP assets, separate from configuration… materialised as read-only projections into a Harness's declared slots."
- `skills.py` : 173 — `SkillAssetError` (:35), `parse_skill_frontmatter` (:45) — **regex flat-scalar parser, refuses `[ { | >` values (:67-74), returns only `{name, description}`**; `_walk_bounded` (:87); `SkillAssetStore(root)` (:110) with `revision_dir` `<root>/skill/<asset_id>/<revision>` (:116-117), `install(source, *, asset_id, revision)` staging+0o644+rename (:119-166), `verify` (:168). Bounds `MAX_ASSET_ENTRIES=512`, `MAX_ASSET_BYTES=32MiB` (:26-27). No metadata/retained-fields/tree-digest-in-facts (facts return `files` count only, :158-166).
- `records.py` : 230 — `KINDS = ("skill","mcp","command","plugin")` (:19); `AssetRecords(database, idempotency)` (:23): `publish` (:28), `get` (:81), `list` (:88), `bind` (:93), `unbind` (:117), `copy_bindings` (:126, used by profile clone), `bindings` (:166), `asset_view` camelCase (:218). No `update_binding`.
- `catalog.py` : 223 — `KINDS=("skill","mcp")` (:28), `CatalogError` (:34), `parse_index` (:44), `CatalogStore` (:99): `snapshot_path` (:105), `sync` (:110), `snapshot` (:139), `annotate` (:145), `install_entry` (:163), `payload_path` (:209).
- Non-skill siblings: `mcp.py` : 172 (`canonical_definition` :61, `definition_digest` :123, `McpAssetStore` :128, layout `<root>/mcp/<asset_id>/<revision>/server.json` :135,166), `mcp_probe.py` : 130 (`probe_stdio` :40 — spawns the stdio server, i.e. the only executing asset path), `plugins.py` : 108 (`PluginAssetStore` :49, layout `<root>/plugin/<asset_id>/<revision>` :54, `PLUGIN_SUFFIXES=(".js",".mjs",".ts")` :25), `rendering.py` : 126 (`render_json_config` :69, `render_toml_config` :77, `RENDERERS` :94, `render_for_family` :100).
- `accounts/assets.py` — separate encrypted account-asset store (`write_asset/read_asset/reclaim` :176-216); not part of `server_assets`.

`core_wire.py` : 2146 — asset wire surface:
- param-shape table `_PARAM_SHAPES` entries (:252-262): `assets.list`, `assets.publishSkill`, `assets.publishMcp`, `assets.publishPlugin`, `assets.bind`, `assets.unbind`, `assets.bindings`, `assets.syncCatalog`, `assets.catalog`, `assets.installFromCatalog`, `assets.probe`.
- method→handler map (:344-354) to `assets_*` handlers.
- handlers: `assets_sync_catalog` :779, `assets_catalog` :793, `assets_install_from_catalog` :811, `assets_probe` :830, `_require_assets` :850, `assets_list` :854, `assets_publish_skill` :859 (takes host path `sourcePath` :860-868), `assets_publish_mcp` :882, `assets_publish_plugin` :905, `assets_bind` :936, `assets_unbind` :951, `assets_bindings` :959; profile-clone binding copy at :1286-1299 (`asset_records.copy_bindings`).

`plugin.py` : 399 — composition root `ordessa.server-compat` (docstring :1-8 "owns… 59 wire methods"): builds `assets_root = context.data_root / "assets"` (:125), `AssetRecords(database, idempotency)` (:136), `SkillAssetStore` (:137), `McpAssetStore` (:138), `PluginAssetStore` (:139), `CatalogStore(assets_root / "catalogs")` (:140); exported provided_ports names (:279-283): `asset.records`, `asset.skills`, `asset.mcp`, `asset.plugins`, `asset.catalogs` (and `account.assets` :278).

`profiles/clone.py` : 146 — `MIGRATION_ITEMS` (:28-38, incl. `"skill"`), `plan_migration(...)` (:50); skill/mcp/plugin bindings travel when target declares slot (:104-115).

`packages/pacthold/src/pacthold/resource_contracts/agent_skill_v1.py` : 49 — `AgentSkillV1` frozen dataclass (:14) with `contract_id = "agent-box.skill@1"` (:15), validation (`skill_id` ≤96, `name` ≤128, `description` ≤512, revision ≥1, `sha256:` digest, format must be `agent-skills`, manifest `SKILL.md` :25-35), `public_dict()` (:37). Exported in `resource_contracts/__init__.py:13,46,61`. Docstring references `ResolvedAgentSkill` which **does not exist in this tree** (grep across all .py returns only the docstring) — stale/aspirational reference.

Schema (`packages/pacthold/src/pacthold/storage/database.py`):
- `PRODUCT_SCHEMA_VERSION = 21` (:11).
- Tables created in `_migrate_12_to_13` ("Order 58: managed skill/MCP assets and their profile bindings", :474-496):
  - `server_assets(id TEXT PK, kind TEXT NOT NULL, name TEXT NOT NULL, description TEXT, latest_revision INTEGER NOT NULL, digest TEXT NOT NULL, source TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)`
  - `server_profile_assets(profile_id TEXT NOT NULL REFERENCES server_profiles(id), asset_id TEXT NOT NULL REFERENCES server_assets(id), revision INTEGER NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY (profile_id, asset_id))`
  - Same DDL duplicated in the base-schema constant at :197-216. Neither table stores content; content lives under the assets root, content-addressed (:477-481).

Tests (`apps/server/tests/`): `test_asset_hubs.py` : 808 — **17 test functions**, names at :40,46,64,79,88,104,116,149,163,211,258,410,595,644,662,704,758 (covers skills store, mcp canonicalize/render, records bind/no-content invariant, wire face incl. `assets.publishSkill/bind/bindings/syncCatalog/installFromCatalog/probe`, catalog provenance, mcp probe bounds, plugin store preview + `assets.publishPlugin` wire). Related: `test_asset_surface_refusals_147.py` (wire refusal ownership for the asset surface, header :1-12), `test_import_asset_request_id_129.py` (`accounts.importAsset` requestId idempotency — account assets, not skills), `test_server_compat_boundary.py` (pins declared edges of server-compat).

Harness-side consumers (must stay compatible):
- `plugins/harness/src/ordessa_harness/harnesses.toml`: `contract_id = "agent-box.skill@1"` input declarations at :46 (codex), :167 (opencode), :219 (hermes), :408 (pi); `skill_target` slots at :32 codex `/runtime/home/skills/{skill_id}`, :110 claude-code `/runtime/home/.claude/skills/{skill_id}`, :164 opencode, :216 hermes, :314 qwen `/runtime/home/.qwen/skills/{skill_id}`, :406 pi.
- `plugins/harness/src/ordessa_harness/registry/schema.py:140` — pins skill contract shape: `target == "skill-tree"`, `minimum 0`, `maximum ≤ 32`.
- `plugins/harness/src/ordessa_harness/adapters/generic_cli.py:20,35` — consumes `agent-box.skill@1` resolved inputs, declares `skill-tree` read-only sources with provenance `skill:<skill_id>:<revision>`.
- `plugins/harness/tests/test_codex_plugin.py:23` — asserts `{"agent-box.skill@1": (0, 32)}` input limits.

Gap fact: in the current tree **skills are stored/bound but never materialised into a session** — `grep -ri skill plugins/server-compat/src/ordessa_server_compat/execution/` is empty; the only materialisation path exercised by tests is MCP (`test_asset_hubs.py:258`). Whether that is intended is NOT VERIFIED.

### B.2 Externally-compatible identifiers to preserve (concrete list)

- Wire methods (11): `assets.list`, `assets.publishSkill`, `assets.publishMcp`, `assets.publishPlugin`, `assets.bind`, `assets.unbind`, `assets.bindings`, `assets.syncCatalog`, `assets.catalog`, `assets.installFromCatalog`, `assets.probe` — core_wire.py:252-262, 344-354.
- Wire param names: `requestId, assetId, revision, sourcePath, definition, profileId, enabled, sourceId, sourcePath, entryName` (core_wire.py:253-261).
- Wire response fields (camelCase, `asset_view`): `assetId, kind, name, description, latestRevision, digest, source, createdAt, updatedAt`; binding view: `assetId, kind, name, revision, digest, enabled` (compat records.py:218+ / legacy records.py:31-43).
- Tables + columns: `server_assets(id,kind,name,description,latest_revision,digest,source,created_at,updated_at)`, `server_profile_assets(profile_id,asset_id,revision,enabled,created_at,updated_at)` with PK `(profile_id,asset_id)` (database.py:197-216, 484-496); created by migration 12→13, current schema version 21 (database.py:11).
- On-disk layout under `data_root/assets/`: `skill/<asset_id>/<revision>/`, `mcp/<asset_id>/<revision>/server.json`, `plugin/<asset_id>/<revision>/`, `catalogs/<source_id>/index.json` (plugin.py:125,140; skills.py:116-117; mcp.py:134-135,166; plugins.py:53-54; catalog.py:105-108).
- Digest spelling `sha256:<hex>` via `pacthold.resource_contracts.runtime_artifact_tree_digest` (tree digest v1) (skills.py:22,149; mcp.py:123).
- Asset-id forms: lowercase slug regex `[a-z0-9][a-z0-9._-]{0,63}` and opaque `asset_<uuid-hex>` (compat records.py:20 + opaque_id path).
- Contract id `agent-box.skill@1` (upstream identifier kept per AGENTS.md rule 6; pinned by pacthold/tests/test_brand_rename.py:44-45, test_resource_contracts.py:18, harness schema.py:140, harnesses.toml, test_codex_plugin.py:23).
- Harness slot strings: `target = "skill-tree"`, `skill_target` paths incl. `{skill_id}` placeholder (harnesses.toml, generic_cli.py:20,35).
- Catalog index format: `{"schema_version": 1, "entries": [...]}` canonical JSON digest (both trees' `parse_index`).
- Extension id `ordessa.assets` exists only in the legacy tree (manifest.json); not yet in any product manifest — reserved identifier for the new plugin (NOT VERIFIED whether other extension ids collide).
- Error code strings surfaced over the wire: `SKILL_FRONTMATTER_MISSING, SKILL_FRONTMATTER_INVALID, SKILL_NAME_INVALID, SKILL_DESCRIPTION_MISSING, SKILL_ASSET_INVALID, SKILL_ASSET_OUTSIDE_BOUNDS, SKILL_REVISION_EXISTS, SKILL_ASSET_MISSING, ASSET_INVALID, ASSET_NOT_FOUND, ASSET_REVISION_UNKNOWN, PROFILE_NOT_FOUND, BINDING_NOT_FOUND, CATALOG_INVALID, CATALOG_ORIGIN_MISSING, CATALOG_ENTRY_UNKNOWN, CATALOG_SOURCE_MISSING` (compat skills/catalog/records; legacy errors codes follow "legacy store's spelling", errors.py:1-6).

### B.3 Non-Skill kinds sharing the tables/services today

- `mcp`: owned by server-compat (`assets/mcp.py` store, `assets/rendering.py` per-family renderers, `assets/mcp_probe.py` live stdio probe, handlers core_wire.py:882,830). skills-v2 wire-compat §1 and §3 explicitly keep mcp out of the Skills takeover "直至 mcp/plugin 资产域另立接管单".
- `plugin` (JS/TS code assets, distinct from desktop extensions): owned by server-compat `assets/plugins.py` + handler `assets_publish_plugin` (core_wire.py:905).
- `command`: listed in `KINDS`/`ASSET_KINDS` (compat records.py:19; legacy identity.py:10) but **no publisher, installer, or wire method for kind `command` exists in either tree** (grep for `"command"` asset kind in server-compat/apps-server finds only MCP-stdio `command` fields and hook handler types). Ownership: NOT VERIFIED / dormant enum value.
- `account` assets: separate store (`accounts/assets.py`, encrypted via secret_store), separate wire family `accounts.*` — not in `server_assets`.

### B.4 Surprise / risk register (for the adjudication doc)

1. Legacy package never registered: no plugin.py/entry point; PARTIAL blockers 1-3 mean the old `assets.*` compat surface is and remains the only live implementation (A.2, A.5).
2. `tasks.md` T6 names `server/staging.py` — file absent (delivered as part of `import_transfer.py`).
3. `green-run.md` self-contradicts 89 vs 88 passed; review-record fixes it at 89.
4. No exit codes recorded in any evidence file; "collect/passed/failed" numbers exist only for aggregate runs; apps/server per-failing-ID reasons not enumerated in the ledger (inherited red 90F/158E with "0 行差异" vs base).
5. Desktop `wireGateway.ts` calls `assets.profileFacets`, a method defined nowhere (unwired; blocker 7).
6. `harness_delivery/capabilities.py` registry is empty by design — zero confirmed brand capabilities; AC-5 real-brand evidence PARTIAL (blocker 4). New design must not carry a "second static brand table" (research-and-reuse.md 能力注册表 row).
7. `harness_delivery/delivery.verify_load` treats a matching digest as LOADED evidence — the v2 spec calls this class of false evidence out (research-and-reuse.md 投影/证据 row); do not migrate that path 1:1.
8. Compat frontmatter parser (skills.py:45-84) is regex/flat-scalar only; legacy parser (frontmatter.py) is YAML + retention. Byte-fidelity of *stored* files is preserved because stores copy files verbatim; *parsed metadata* differs (fields like nested `metadata` are refused by compat, retained by legacy) — a G01 adjudication point.
9. validator.py:84 `_ = os.fspath(target)` dead statement; projection ledger is JSONL not DB (blocker 5).
10. Current tree stores/binds skills but has no skill materialisation into sessions (server-compat execution grep empty), while pacthold `AgentSkillV1` + harness `skill-tree` slots already define the runtime-side contract — the Q1 seam is between these two.
