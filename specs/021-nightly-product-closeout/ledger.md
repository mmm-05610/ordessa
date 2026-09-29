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
| B-001 | P0 | desktop-build | （集成）trunk `c14d9296ff`；RV-1 PASS；Invalid URL 崩溃消除（/tmp 双重复现验证），server-bridge 48/48、tsc 零新增 | RV-1 报告 | 已修 | Lead | — | DONE | trunk 组合门 build/server-bridge/apps-desktop 全绿 | 遗留：server-bridge→apps/server 构建期 import 属可接受债 |
| B-003 | P0 | desktop-main | （集成）trunk `f4b8f1e405`；RV-1 PASS；三布局解析 + 5 条真实 IO 断言 + 装树仿真 14/14 | RV-1 报告 | 已修 | Lead | — | DONE | apps/desktop 130/130；dev 零回归 | 遗留：extensions.lock.json 未打包（W-021）、readProductManifests 无直测 |
| B-002 | P0 | packaging | （集成）trunk `11fb13dacd`；RV-2 PASS；16 包闭包经独立 AST 复核逐项相等；新 deb 45/45（含 6 新断言）；bundled server 实测 /live | RV-2 报告 | 已修 | Lead | — | DONE | deb sha256 `913f1007…`（该树取证） | 遗留见 W-021/W-023/W-024；C2 前需以 trunk 重出 deb |
| B-005 | P0 | server-bootstrap | 数据根"创建即立契"：python ensure_data_root 写 marker + 宿主 ensureDataRoot 创建时写 marker（0600）；外来根拒绝语义保留 | RV-3 PASS（产品级实证：全新根真实首启 marker 落盘 + listening + /live=200；外来根仍拒绝） | 双创建路径双修 | Lead | — | DONE | trunk `dab802d776`；红线偏离（补 host-main 测试）经 RV-3 裁定接受 | windows lockfile 未同步（归 W-021⑥） |
| I-001 | P1 | wire-seam | 桌面 wire seam 接通：HttpWirePort 对齐 JSON-RPC（旧信封 400→新信封真 server 200）+ 渲染代理诚实化 + 四资产入口消费 WirePort + 装配 + W-014 守卫对齐 | RV-3：信封/边界/无 fake green 全过；唯一阻塞=sandbox-settings 缺 config pin 必抛 → 按选项③整改 | EA-1 D-021-7 执行 | Lead | — | DONE | trunk `1053a4b930`..`8c27bc0ad8`；server-bridge 57P 含 live 3 例；build 17 扩展；typecheck 30 条（较基线 -1） | sandbox-settings 回装待 W-026；B-001 组合显形 FR-009 回归已修（trunk `7b8223d38e` 守卫白名单豁免 C-01 数据文件）；Accepted 非对象结果判 Unknown 的语义债已 RV-3 登记 |
| W-026 | P2 | product-assembly | `ordessa.sandbox-settings` 暂缓装配：entry 缺 `config.request.harnessId` pin 必抛，且全仓无 extensions.json `config` 注入机制 | RV-3 阻塞项 | entry 硬依赖产品事实 pin + 注入通道不存在 | Integrator（B-004/native 波） | — | NEW | — | 回装路径：native 波定 pin（或 entry 降级为诚实"未配置"区），同时在装配侧落 config 通道 |
| W-027 | P4 | arch-debt | FR-009 守卫白名单新增 C-01 layout JSON 豁免（trunk `7b8223d38e`）——平台→apps/server 构建期数据耦合从隐性变显性豁免 | 集成组合门（I-001×B-001 才显形） | B-001 取静态 import 方案 | — | — | DEFERRED | 守卫 5/5 绿，跨语言对照测试保持 | 正解（如构建期 alias/中性资产位）留架构债，不当晚阻塞 |
| W-021 | P3 | review-debt | RV 审查遗留打包/测试卫生批：① extensions.lock.json 未进 deb（装机诊断缺一项）② deb-contract `sh()` 未清 PYTHONPATH ③ resolveBundledRuntime 只查 python 目录不查解释器本体 ④ `tests/integration/packaging/.runtime-bundle`、`packaging/.test-extract` 未 gitignore（中断残留 ~700MB 有夹带风险）⑤ `scripts/verify-clean.sh:79` "28 pins" 文案陈旧（现 29）⑥ server-windows lockfile 未同步 tomli-w | RV-1/RV-2/B-005 报告 | 各自微小 | 随 I-002/收口波 | — | NEW | — | ①④ 随 I-002 优先；②③⑤⑥ 收口前批量 |

## Backlog（主动发现池，动态）

| 候选 | 来源 | 备注 |
| --- | --- | --- |
| installed-product smoke 脚本化（install→launch→project→session 链） | acceptance P0 | 服务于 C2 与最终 closeout |
| deb 资源完整性检查（icons/desktop entry/服务端 runtime） | acceptance Product Assembly | `scripts/packaging/clean-machine-accept.sh` 已有基础 |
| Profile facet 盘点（ owning plugin facet 列表 × Harness 支持矩阵） | acceptance Profile | Phase 4 输入 |

## 环境

- Live services 注册表：`docs/known-issues.md` §services —— **不 kill/restart**。
- 真实测试：隔离 data-root + 临时项目；用户登录态只读。
