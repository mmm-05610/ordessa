# Reuse decisions, provenance and licence ledger (T01 input to T15)

Required by `docs/design/native-subagents/research-and-reuse.md` §"复用实施门"
("T01 保存上面每个实际源文件/测试、许可证和可复用单元核对表") and by
`specs/011-plugin-rollout/checklists/readiness.md` item "复用来源/许可、迁移/删除/
数据兼容与卸载处理明确".

Repository licence, measured: `LICENSE` → `MIT License, Copyright (c) 2025 Nous
Research` (HEAD `96fef2db47`).

## 1. What Q3 actually took from elsewhere

**Zero third-party source was copied, vendored, or added as a dependency.** Q3's
package has stdlib-only runtime dependencies and its test dependencies are
`pytest` (already the repo-wide dev convention).

| Source examined | Version / provenance | Licence (measured) | How used | Was any bytes copied? |
| --- | --- | --- | --- | --- |
| `@agentclientprotocol/claude-agent-acp` | `0.81.2`, pin at `plugins/harness/src/ordessa_harness/claude/production.py:66-67`; installed with `npm install --no-save` **outside** the repo into `/home/maoqh/ordessa-evidence/q3/claude-pkg` | `package/package.json` `"license": "Apache-2.0"`, `LICENSE` present (10 783 B) | Read-only static inspection to fill `capability-matrix.md` rows C-1…C-7 | **No** |
| `@agentclientprotocol/codex-acp` | `1.1.14`, vendored in-repo at `plugins/harness/packaging/codex/vendor/agentclientprotocol-codex-acp-1.1.14.tgz` | `"license": "Apache-2.0"`, `LICENSE` = `Copyright 2025 JetBrains s.r.o.` under Apache-2.0 | Read-only inspection (extracted to仓外 root): proved the `.agents` root is the **skills** root and that no subagent discovery exists at this pin | **No** |
| `@automatalabs/pi-acp` | `0.5.0`, vendored at `plugins/harness/packaging/pi/vendor/automatalabs-pi-acp-0.5.0.tgz` | `"license": "Apache-2.0"` | Read-only inspection: no `subagent` / agents-directory surface at the pin | **No** |
| `plugins/server-compat/.../assets/{records,catalog,skills}.py` | same repo, same commit | MIT (repo) | **Pattern reuse only** (digest validation, stage-then-rename, bounded walk, pinned provenance). Not imported — it is a sibling plugin, and plugin→plugin imports would break the boundary tests | **No** |
| `plugins/server-compat/.../profiles/subagents.py` | same repo | MIT | Read-only inventory to mark the dispatch surface REJECT (FR12). The `160`-char description cap is used as a *precedent value*, restated as a Q3-local constant | **No** |
| `plugins/harness/src/ordessa_harness/qoder/native_config.py:41-137` | same repo | MIT | Shape inspiration for a registered-keys vs unregistered-keys table | **No** |
| `plugins/harness/src/ordessa_harness/registry/loader.py:23-35` | same repo | MIT | Shape inspiration for `"sha256:" + sha256(text)` document digest | **No** |
| Pi official `examples/extensions/subagent/{index.ts,agents.ts}` | upstream GitHub, **not** present on this host (searched the Pi install tree, not found) | Not assessed | **Not used at all.** It is the subject of the C0-owned audit A1–A7 in `pi-extension-audit.md`; Q3 neither vendors nor installs it | **No** |
| Upstream documentation (Claude/Codex/Pi URLs in `research-and-reuse.md`) | as of 2026-09-28 | n/a (prose) | Treated as *claims about latest*, never as proof about the repo pins — that is exactly G01's negative column | n/a |

## 2. Per-module reuse resolution (the §"逐模块复用决议" table, executed)

| Design module | Planned reuse | What Q3 did | Deviation & reason |
| --- | --- | --- | --- |
| Native launch / session identity | Consume Harness C1/C2 public API only | Did not touch Harness; emitted typed intents and filed SR-1/SR-2/SR-3b | No deviation — `harness.configuration-adapters/v1` has zero code hits, so there was nothing to consume |
| Old subagent tool semantics | Read-only inventory / migration reference | `legacy-inventory-matrix.md`, every symbol classified REJECT/KEEP-LEGACY/UNKNOWN | None |
| Content inventory & safety checks | Reuse by symbol if a shared module truly exists, else keep a thin own store | Kept a **domain-owned thin store**; reused the *safety patterns* by re-implementing them with tests | Documented deviation: `AssetRecords`/`SkillAssetStore` are real but live in the `server-compat` **plugin**; importing across plugins collides with `apps/server/tests/test_server_compat_boundary.py:152` and would create the "second AssetsService" the design forbids. Recorded as **SR-8** for C0 to decide |
| Profile contribution / editor | Consume published facet/UI interfaces | Not implemented; SR-4 request + the resolver expressed as the single source of truth | Blocked: `codex/011-profile-api-ready` absent, `plugins/profile/` does not exist in this worktree |
| Front-end UI / Chat menu | Use public contribution points | Not implemented; SR-5 | Blocked: `codex/011-chat-api-ready` absent |
| Pi sample extension | Borrow capability-probe and isolation counter-examples only | Probed the real host CLI instead (`pi --version`, `pi list`, `pi --help`) and wrote the A1–A7 review checklist | Stronger than the plan: no sample code touched |
| Versioned definition store & scope resolution | Ordessa-implemented thin domain logic | Implemented in-package; **not** folded into Pacthold or Server; no schema-version change | None — `PRODUCT_SCHEMA_VERSION` untouched (still 21) |

## 3. Licence obligations created by Q3

None. Since no Apache-2.0 (or any third-party) file was copied, no NOTICE entry,
no licence-text obligation and no dependency-closure addition is created by this
line, and `apps/server/lockfiles/*` and the root `package-lock.json` stay
unchanged by Q3 (see `integration-request.md` I-1/I-2). The inspected artifacts
remain **outside** the repository (`AGENTS.md` rule 4: no binaries in git).

## 4. Honest limits of this ledger

- The Claude inspection required a network `npm install` because that pin is not
  vendored in-repo. If the same evidence must be reproduced offline, C0 should
  vendor `@agentclientprotocol/claude-agent-acp@0.81.2` the way Pi and Codex are
  vendored; that is a shared-surface change and deliberately left to C0.
- The Apache-2.0 licence strings were read from each package's own
  `package.json`/`LICENSE`; no SPDX scan tool was run, and no full dependency
  closure of those packages was enumerated (only their top-level licence was
  needed because nothing is redistributed).
- The Pi official example extension's licence was **not** assessed, because it is
  not present on this host and Q3 did not fetch it — that assessment is item A1 of
  the C0 audit.
