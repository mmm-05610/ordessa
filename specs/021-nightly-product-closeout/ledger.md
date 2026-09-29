# ledger.md — blocker/backlog 动态真相源

Lead 维护。每发现一个问题先入表再处置；"发现 blocker"不是完成。

优先级：**P0** deb/install/launch/core runtime 完全阻塞 · **P1** 普通 Harness
Desktop 主路径 broken · **P2** 重要已有产品能力 broken · **P3** UX/hardening/
secondary feature · **P4** architecture/cleanup/test quality。

状态：NEW → INVESTIGATING → ASSIGNED → FIXING → REVIEW → VERIFY →
DONE；特殊：BLOCKED_EXTERNAL / DEFERRED。

Lead 工作队列：NOW / NEXT / REVIEW / VERIFY / BACKLOG（NOW 快空时提前从 NEXT 拉）。

## Blocker / Issue 表

| ID | Priority | Area | Symptom | Reproduction | Root Cause | Owner | Branch | Status | Verification | Disposition |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| W-001 | P1 | product-assembly | 默认桌面装配 14 项 vs 仓库 23 个扩展包（8 缺装配：skills/asset-mcp/sandbox-settings/model-provider/permissions-chat/subagent-settings/assets-subagents-ui/model-provider-chat）；server `default_plugins()` 仅 8 插件（skills/mcp/prompts/memory/subagents/extensions/runtime-preferences 未选）；且 3 个可构建扩展 entry 形态损坏（sandbox-settings/profile-chat 无 default export、model-provider default 非 factory、skills factory 期望注入） | SC-1 盘点（矩阵见其报告） | 三层断：assembly 缺 id + server 组合缺插件 + wire 注入 seam 缺失 | Integrator（待 C2 后） | — | CONFIRMED | — | 拆 B-004；seam 方案待 EA-1 裁决 |
| W-002 | P4 | backend | harness 套件 2 inherited failures（npm closure：`@agentclientprotocol/sdk` override vs `@automatalabs/pi-acp` 声明） | `python -m pytest plugins/harness` | 依赖漂移（上游树继承） | — | — | DEFERRED | inherited（known-issues 登记） | 与 baseline 对比；非今晚新增不 block |
| W-003 | P4 | backend | server 套件 inherited-red 台账（783P/43F/10S/25E；59 同 ID inherited + 6 scope-reds） | `python -m pytest apps/server` | 见 `docs/migration/backend-build-test.md` 逐项裁定 | — | — | DEFERRED | inherited | 只对新增 regression 追 disposition |
| W-004 | P4 | backend | `tests/acp_orchestration` reds（worker-entry retirement 裁定） | 运行该套件 | hd004 裁定：不复活 compat chain | — | — | DEFERRED | inherited | 保持 visible；禁止 green-by-revival |
| W-005 | P3 | CI | `test_external_adapter_product.py` 干净 CI runner 上 error（pip 子进程构建 fixture 分布解析不同；本地 3/3 过） | CI ledger step | fixture 构建输入未钉死 | — | — | DEFERRED | CI-env（2026-09-29 登记） | follow-up：pin fixture 输入/offline wheelhouse |
| W-006 | P3 | desktop-UI | approval card 无 timeout 显示 | Round H 登记 | UI debt | — | — | DEFERRED | inherited | 今晚 UX 波次候选 |
| W-007 | P3 | desktop-UI | 输入框滚出视野（待确认） | Round H 登记 | UI debt | — | — | DEFERRED | inherited | 今晚 UX 波次候选 |
| W-008 | P4 | bridge | `TestE2EACPPlanUpdateMappedFromTurnPlanUpdated` flaky（2/3 失败曾观测） | Go 侧 e2e | Go-side flaky | — | — | DEFERRED | inherited flaky | 观测；不计 regression |
| W-009 | P4 | server-arch | `bootstrap/runtime.py` start/stop 仍达 Core 内部（configure_database/get_conn）而非实例级 Store；S1c 组合裁定未落 | specs/010 B lane T014-S1c | 架构搬家未完 | — | — | DEFERRED | registered | 仅当阻塞 P0/P1 才动；否则不碰 |
| B-001 | P0 | desktop-build | Electron 主进程 bundle 加载即崩：CJS 打包把 `import.meta.url` 落成 `{}`，`data-root.ts` 顶层 `layout()` 抛 `Invalid URL`；dev/installed 同崩，全部 electron gate 连带红 | `npm run test:agent-shell`；`/tmp/021-direct-launch.log`（RE-1/SC-2 双重复现） | `server-bridge/src/data-root.ts:59,70` + `apps/desktop/scripts/build.mjs` cjs bundle | Blocker-Surgeon | nightly/021-b001-electron-main-crash | ASSIGNED | 待 | 阻塞 C2；修复面小（JSON 构建期内联/去 import.meta 依赖） |
| B-002 | P0 | packaging | deb 缺 server 产品闭包（build-deb 仅装 pacthold/server-plugin-api/apps/server，缺 products/server→SERVER_PRODUCT_MISSING 及 workspace/server-compat/runtime-compat/harness/sandbox/permissions 链）；`/opt/ordessa/harnesses` 未 staging→BUNDLED_RUNTIME_MISSING；serverCommand 把 python 目录当可执行文件（runtime.ts:62,78） | SC-2 Q1/Q3；C-09 契约 | `packaging/build-deb.mjs:120-142` 闭包不全；layout.harnesses 缺失；pythonBin 未被 runtime.ts 使用 | Blocker-Surgeon | nightly/021-b002-deb-server-closure | ASSIGNED | 待 | 装机三连炸的第二、三环 |
| B-003 | P0 | desktop-main | 安装版扩展发现路径错：`main.ts:148` dev 相对路径在装机解析为 `/opt/products/desktop/dist`（不存在）→ 零扩展空壳白屏；`readProductManifests` 同病 | SC-2 Q3 算术复现 | dev/installed 双布局未区分（build-deb 已把两 dist 合并进 app/dist） | General-Worker | nightly/021-b003-installed-discovery | ASSIGNED | 待 | 阻塞 Workbench 出现；dev 路径不得回归 |
| B-004 | P1 | product-assembly | W-001 接通执行：server `default_plugins()` 增补 skills/mcp/prompts/runtime-preferences/memory/subagents；extensions.json 增补可构建扩展 id；坏 entry 形态修复；chat resolver 映射 | SC-1 §1/§4-⑤ | 三层断（组合/装配/seam） | Integrator | 待开分支 | NEXT | — | 在 B-001..003 集成后开波；seam 先拿 EA-1 裁决 |
| W-011 | P3 | tools | `npm run test:packaging` Node 22.22.1 目录参数 MODULE_NOT_FOUND（测试本体 glob 直跑 39/39 绿） | RE-1 A | node --test CLI 行为 | 随 B-002 | — | ASSIGNED | — | B-002 同波顺手改 glob |
| W-012 | P3 | tests | skills/desktop chatContribution "session guard" 1 红（124P/1F，上游 "incomplete work retained"） | RE-1 B | 上游合并遗留 | — | — | NEW | — | backlog；不计今晚 regression |
| W-013 | P3 | tests | acp-connector rig 2 个 ui 套件 import 已删除的 conversation view | RE-1 B | 014 P-C 退役未迁移 rig | — | — | NEW | — | backlog |
| W-014 | P2 | guard | `contract-ownership.test.mjs` 仍断言已退役 `ordessa.agent-conversation` 为 enabled → 静态必红 | RE-1 B + SC-1 | S-03 退役后守卫清单未更新 | 随 B-003/B-004 | — | NEW | — | 顺手修 |
| W-015 | P3 | build | `build:examples` 红：`@assistant-ui/react` 随 conversation 退役缺失；级联 ui-service/ui-foundations/agent-ui-probe | RE-1 B | 退役依赖未清理 | — | — | NEW | — | backlog；不阻塞 deb |
| W-016 | P4 | docs | `docs/baseline.md` editable 清单缺 018 并入包；桥 sha 钉值过期（实际复现 `714044a5…` vs 钉 `5fd6a37b…`） | RE-1 E/F | 文档滞后于 018 合并 | Lead | — | NEW | — | 收口时更新 baseline 文档 |
| W-017 | P2 | profile | `ordessa.profile-chat` 无 default export → 每次启动 alert；`profile-frontend` 空 stub；Profile 桌面 UI 名存实亡（三扩展 enabled 但不干活） | SC-1 §1/§4 | entry 形态/未实现 | Integrator | — | NEW | — | C4 Profile 波次主修；alert 不阻塞启动 |
| W-018 | P3 | env | 非交互 sudo 不可用；真实安装验证走 userns chroot（clean-machine-accept 需先下载 ubuntu-base.tar.gz）；该脚本不启动 GUI，不能单独当 C2 证据 | SC-2 Q5/Q6 | 环境限制 | Release-Engineer | — | ASSIGNED | — | C2 策略见 decision-log D-021-6 |
| B-005 | P0 | server-bootstrap | 全新数据根首启必炸 `DATA_ROOT_UNOWNED`：`ensure_data_root` 只建目录不写 owner marker，`DataRootOwner.acquire` 拒绝"存在且无 marker"；桌面 `ensureDataRoot` 同病 → 装机首启死在数据根这步 | B-002 实测：bundled python `--data-root <new>` → RuntimeError；预置 marker 后 2s `/live`+handshake（证明闭包本身端到端可用） | `data_root.py:288-312` + `runtime.py:160-163`（+ `electron/data-root.ts:82-88`） | Blocker-Surgeon（B-002 组） | nightly/021-b005-data-root-marker | ASSIGNED | — | 保留外来根拒绝语义（test_stage_a_server.py:205）；顺带 W-020 |
| W-020 | P1 | lockfile | `tomli-w` 不在 `apps/server/lockfiles/server-linux-py312.txt`，harness `materialization.private_generation` 模块级 import → B-004 接通后即 ImportError | B-002 解剖 | 018 并入 harness 物化链时未补锁 | 随 B-005 | — | ASSIGNED | — | pip 实装验证闭包 |
| W-019 | P2 | desktop-test | `test:agent-shell` 期望陈旧：断言已退役 agent/conversation 的 "Conversation" 页（实测产品 pages=["Sessions"]），且 `connected.errors deepEqual []` 被 profile-chat 告警（W-017）打破 | B-001 验证实测 | 014 P-C 退役后测试壳未随产品更新（2026-09-25 graft 自 agent-box-desktop-next） | 待派（B-001/B-003 集成后） | — | NEW | — | 更新断言对齐当前真实产品形态；**不删断言换绿** |

## Backlog（主动发现池，动态）

| 候选 | 来源 | 备注 |
| --- | --- | --- |
| installed-product smoke 脚本化（install→launch→project→session 链） | acceptance P0 | 服务于 C2 与最终 closeout |
| deb 资源完整性检查（icons/desktop entry/服务端 runtime） | acceptance Product Assembly | `scripts/packaging/clean-machine-accept.sh` 已有基础 |
| Profile facet 盘点（ owning plugin facet 列表 × Harness 支持矩阵） | acceptance Profile | Phase 4 输入 |

## 环境

- Live services 注册表：`docs/known-issues.md` §services —— **不 kill/restart**。
- 真实测试：隔离 data-root + 临时项目；用户登录态只读。
