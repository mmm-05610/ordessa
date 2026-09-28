# P-A report — profile 解锁与产品就绪（014）

日期：2026-09-28。树 `worktrees/014-a-profile`，分支 `codex/014-a-profile`
（基线 = main 491aa92392 + merge `codex/plugin-profile` @ 30cb66d601）。

**终态一句话**：profile-api r2 以 SHA 交付并全门绿；四线解锁复验完成
（Q1 零漂移 433、Q3 28 条绿、Q4 漂移定性登记、Q5 634 绿）；桌面三包补到
extensions 通道就绪；三品牌矩阵受控版 12 条绿 + 金样钉定；S-08③ 裁定与
退役清单交付。整体 **PARTIAL（诚实口径）**——真实 CLI 装载、真实浏览器
几何、生产 admission/装配为如实登记的外部依赖，不冒充完成。

## 0. R0 基线与环境（含 F6 补录）

- 工具链：Python 3.12.14（本树 `.venv`）、Node 22.22.1 / npm 9.2.0，与
  `docs/baseline.md` 钉定一致。
- 安装序列（R0 实测，修复了 baseline 命令的两个顺序坑，已增补 S-10）：
  1. `pip install -r apps/server/lockfiles/server-linux-py312.txt`
  2. `pip install -e 'packages/pacthold[dev]' -e packages/server-plugin-api -e plugins/harness/api`
  3. `pip install -e plugins/assets/sandbox/{api,backend,adapters} -e plugins/permissions/{api,backend,adapters}`
     （**必须先于 products/server**：`products/server` 声明这些 dist 为依赖，
     且只存在于本地，否则 pip 从 PyPI 找 0.1.0 必红——第一手踩坑实录）
  4. `pip install -e 'apps/server[dev]' -e 'plugins/harness[dev]' -e plugins/workspace
     -e plugins/server-compat -e plugins/runtime-compat -e products/server -e plugins/profile`
     （`-e plugins/profile` = F6 补录项）
  5. `python -c "import pacthold, server_plugin_api, ordessa_harness_api,
     ordessa_server, ordessa_harness, ordessa_server_product, ordessa_profile,
     pacthold_runtime_compat, …"` → 全过
- npm：本树 `npm ci` 因根 lock 缺 profile 三 workspace 条目而红
  （`Missing: @ordessa/plugin-profile-api@0.1.0 …`）；按 011-z1 先例改
  `npm install` 本地重算，**lock 增量保持未提交**（根锁禁区 → S-02 增补，
  INT-02 定稿时一并纳入）。
- 消费 SHA：foundation `8844c475bc02a185ab194c69eed873122aa48349`（经 main
  合并线在位）；harness-api/chat-api 经 main 消费。

## 1. 提交链（本包全部提交，codex/014-a-profile）

| 提交 | 内容 |
| --- | --- |
| `51c7905108` | PA-1 回归：受控 runtime 替身适配合并后 C4 服务协议（140 口径全绿恢复；断言零改动） |
| `887d0700df` | PA-5 品牌矩阵受控版（12 条测试 + 三品牌金样） |
| `e6f720d347` | PA-4 桌面三包 manifest/build.mjs/诚实 entry |
| （本提交） | PA-2 checkpoint r2 + PA-7 退役清单 + 011-z1 report 增补 + seams 回填 + 本报告 + tasks 勾选 |

**r2 交付 SHA**：`implementationSha =
e6f720d347d3258bfb795c12ee703676c24ca24f`（实现终点；消费者按 012 规则以
SHA 合并）。checkpoint：`specs/011-plugin-rollout/checkpoints/profile-api.json`
version r2（dependsOn=foundation `8844c475bc…`；planAnchorRef=
`refs/heads/codex/014-a-profile`）；旧 ready ref `4943628f47` 未动。

## 2. PA-1 R0：回归门（修复说明）

合并线上 `pytest plugins/profile/tests` 首跑 **3 failed / 137 passed**
（`test_harness_real_service.py` 三条）。定性：**非 profile 域回归，是测试
替身协议漂移**——合并 `codex/plugin-profile` 时 harness 的
`ConfigurationApplicationService` 已被 consolidation（edca4049b1）收紧为
"仅 operation 绑定的 native owner receipt + 一致 readback 可 Confirmed"
（`configuration_service.py:455-478`），而 profile 测试的本地受控 Runtime
替身仍是检查点时代协议（旧签名、无 receipt）。替身在 `plugins/profile/tests/`
（本包写入面内），按 harness 自家受控测试同一协议更新；**全部断言零改动**。
修复后：

| 门 | 结果 |
| --- | --- |
| `pytest plugins/profile/tests -q` | **140 passed**（修复后、矩阵加入前） |
| `bash plugins/profile/tests/boundary_check.sh` | OK 0 violations |
| `bash plugins/profile/tests/run_counterexamples.sh` | 12/12 |
| tsc ×3 / vitest ×3 | 0 错误 / 28 passed（9+9+10） |

加入 PA-5 矩阵后全套件：**152 passed**（140 旧账 + 12 矩阵）。

## 3. PA-2 r2 交付

见上 §1 与 checkpoint JSON。要点：
- `plugin.py:21` 修复在位核对通过（无需恢复提交）；
- checkpoint 原位更新为 r2（派单指名原文件；v1 由未动 ready 分支 + git
  历史保真）；
- 011-z1 report 增补「014 / profile-api r2」段（修复 SHA、解锁复验、交付 SHA）。

## 4. PA-3 四线解锁复验（scratch 组合树，不落本分支）

每线：`git worktree add --detach /tmp/pa3-qN HEAD` → merge 对应
`codex/plugin-*` → 共享依赖经本树 venv（三树与本 HEAD 在非 assets 路径
`git diff` 为空，逐字节一致）+ 该线包 editable 安装 → 测试 → 删树。

| 线 | merge 点（源分支 @ tip → 组合提交） | 命令 | 实测 | 旧账与漂移 |
| --- | --- | --- | --- | --- |
| Q1 skills | `codex/plugin-skills` @ b0d4f2686a → `1163f46d06` | `pytest plugins/assets/skills/tests -q` | **433 passed**；6 条指名 ID 全绿：`test_registration_uses_the_published_facet_api_only`、`test_provider_compile_declares_zero_config_intents`、`test_real_resolve_round_trip`、`test_profile_layer_is_read_only_no_writes_behind_the_back`、`test_absent_profile_refuses_with_a_type`、`test_harness_port_absence_keeps_their_typed_block` | 433 = **零漂移** |
| Q3 subagents | `codex/plugin-subagents` @ 5109f1ea7d → `7cc74652e3` | `pytest …/tests/test_profile_facet_t10.py -q`；整包 | t10 **28 passed**；整包 **890 passed** | 671 → 890：**漂移 +219**，原因 = 合并线为 consolidation 分支（提交明文 "incomplete work retained"），011 后批次新增测试；无新增红 |
| Q4 mcp | `codex/plugin-mcp` @ ba891aff05 → `ef9e0204f0` | `pytest plugins/assets/mcp -q`；import 链 | **518 passed / 4 failed / 2 errors**；`import ordessa_profile, backend, ordessa_server_compat.assets.mcp` 链通；T08 未实现（backend 零 `ordessa_profile` import，仅 profileRevision 数据字段） | 461 → 518P + 6 红新增，**漂移定性（归 mcp 线，本包不代写）**：WCG01/04 = mcp 自带 registered drift ledger 过期（`archiveDefinition→archive` 改名已落地、账未销）；WCG02/03 = TS 契约 interface 改名后 fixture 解析 `ValueError: substring not found`；controlled_chain ×2 = mcp 的 runtime 替身未适配合并后 C4 receipt 协议（与 profile 替身同类问题） |
| Q5 permissions | 无需 merge（main 已含） | `python -c "import ordessa_profile"`；`pytest plugins/permissions -q` | import OK；**634 passed** | glue（T06 两域）未实现——如实登记，归 Q5 线 |

门对照：Q1 六 ID 实测绿 ✓；组合树可跑 ✓；漂移全部带原因记录 ✓。

## 5. PA-4 桌面三包产品就绪

对照 `plugins/commands`（manifest `{"id","version","hostApi":"2","entry":"entry.js"}` +
`build.mjs`）与 `plugins/chat/api`（entry+contract 双 entry）补齐：

| 包 | 新增 | 说明 |
| --- | --- | --- |
| `plugins/profile/api` | `manifest.json`（ordessa.profile-api）+ `build.mjs`（entry+contract 双 entry） | contract.js 产物对接 S-04 CONTRACT_SOURCES |
| `plugins/profile/frontend` | `manifest.json`（ordessa.profile-frontend）+ `build.mjs` + `src/entry.ts` | entry 为诚实无副作用桩（对齐 permissions-chat 先例）：workbench/Token 供给是 core 装配面（S-01），不注册假视图 |
| `plugins/profile/integrations/chat` | `manifest.json`（ordessa.profile-chat）+ `build.mjs` | 已有 entry.ts（createProfileChatGlue）直接用 |

构建演练：`ORDESSA_PRODUCT_OUTPUT_ROOT=$HOME/.cache/pa4-build-drill`（演练
重定向，**未触 products/**）→ 三包均产出 `entry.js + manifest.json`
（api 另出 `contract.js`）。补齐后 tsc ×3 / vitest（frontend 9 + chat 10）
复跑全绿。启用清单与依赖闭包已写回 **S-01**（profile-chat→chat-api；
frontend/chat→profile-api）。

## 6. PA-5 品牌矩阵受控版

`plugins/profile/tests/test_brand_matrix_pa5.py`（12 条 = 3 品牌 × 4 格）+
金样 `tests/goldens/brand_matrix/{pi,codex,claude-code}.json`。

- **驱动方式（门）**：每品牌的**真实 harness 品牌面只读消费**，不是只调
  ProfileDB——pi=`ordessa_harness.pi.projection.PiProjection`（argv+runtime
  sources）、codex=`ordessa_harness.codex.production.harness_deployment`
  （deployment 声明全量投影）、claude-code=`claude.profile.ClaudeProjection.
  materialize`（native 文件投影）；会话语义（覆盖/切换/reset/restart）走
  profile-api 公共 sessions 面 + 受控 `ScriptedConfigPort`（显式标注受控替身）。
- **四格**：①字段投影 golden（字节级钉定，两次跑金样还抓出并修掉夹具自身的
  跨调用残留：pi-home 目录树哈希泄漏前次 instructions、claude execution 目录
  泄漏前次 manifest——隔离修复）；②会话覆盖/切 Profile 清除（overlay 只在
  confirmed 切换时清、第二会话状态保持、切后品牌面无残留）；③reset 到品牌面
  （A→B 缺项 → 显式 reset intent 到端口（G08）+ 品牌面重渲染=干净 B 金样，
  绝不过滤不假装）；④restart-resume 保活（受控重启后 settled 绑定+receipt
  保持、无 pending 不重放 apply、pending 跨重启存活且恰好 apply 一次）。
- **F5 环境事实（第一手）**：`pi --version` → `0.86.1` rc=0（在位但钉版
  0.84.2 缺席；0.86.1 拒收投影面 `--agent-dir/--skill-dir`——011-q1-skills
  探针记录）；codex/claude CLI 本机缺席 → 三品牌矩阵停在受控面，**"真实 CLI
  装载"格三品牌均 unknown**，如实上报。
- **G18（浏览器几何/200% 缩放/键盘）**：只列 checklist 不执行（待装配）：
  管理器两级导航键盘全路径、设置页机制开关 200% 缩放布局、Chat picker
  键盘可达与焦点归还、无 Agent 状态徽标读屏语义、冲突横幅与未保存离开
  询问的焦点管理——全部待产品装配后按 quickstart §4 执行。

## 7. PA-7 退役准备（S-08③；只裁定不执行）

交付 `specs/011-z1-profile/retirement-request.md`：

- **仲裁裁定**：`agent-box.profile@1` 唯一声明者 = **profile-api**。依据：
  ① 双声明是登记在案的活动冲突——loader 规则"先加载者赢、后者 FAIL"
  （plugin.py:129-133 注释 + 011 integration-request 契约声明仲裁行），无
  并存选项；② v2 域所有权（facet/会话/policy/journal/迁移 + 140 门 + 边界门）
  在 profile-api；③ 消费面（S-01 三包、ProfilePluginServices wire 面、TS
  client、B 线 PB-6）全部以 profile-api 为基准；④ harness 声明点全清单
  （factory 裸注册链、品牌 façade、pi (1,1) 输入）已定位。
- **逐文件清单 R1–R10**：harness `generic/{profile_store,profile_manager,
  profile_selector,profile_provider}.py`、`harness-profile-store` entrypoint、
  `{claude,hermes,opencode}/profile*.py`、server-compat `server_profiles`
  writer——每文件列生产调用方（grep 实测）/测试覆盖/迁移归属/接续动作；
  R10 按 S-08 既有裁定归 **B 侧波次**（同文件防互撞）；R5 摘除须同波改
  `test_core_boundaries.py:15`；R6 摘除须同波改 PA-5 矩阵 face import。
- **执行归集成波次**（seams S-08），本包零删除、harness/server-compat 零改动。

## 8. PARTIAL 项逐条（诚实缺席）

| # | 项 | 状态 | 归属/解锁条件 |
| --- | --- | --- | --- |
| P1 | 真实 CLI 装载格（三品牌） | unknown | 钉版二进制缺席（pi 钉版 0.84.2 缺席、0.86.1 版本偏斜且拒收投影 flags；codex 0.147.0 / claude 钉版缺席）；待钉版闭包 |
| P2 | G18 真实浏览器几何/200%/键盘 | 未执行（checklist 已列） | 产品装配（S-01 落地）后 |
| P3 | Q4 MCP Profile facet（T08） | 未实现（import 链已验通） | mcp 线（本包不代写）；另 mcp 组合树 4F/2E 漂移归 mcp 线收口 |
| P4 | Q5 permissions glue（T06 两域） | 未实现 | Q5 线 |
| P5 | Q3 整包 671→890、Q4 461→518+6 红 | 漂移已记录 | 消费线 consolidation 后账目冻结归各线 |
| P6 | wire/装配（ProfilePluginServices 进 wire、extensions.json 启停、视图 Token 供给） | 未落地 | core（S-01/S-03/INT）；前端 entry 现为诚实桩 |
| P7 | 生产 admission ready=False | 未翻转 | S-06 机制（core）+ P-E（plugin 第二批） |
| P8 | S-09 canonical SessionRef 服务端映射 | 设计先行 | 014 后续波次，方案+迁移记录后请用户确认 |
| P9 | harness 侧替身协议适配的"生产级"复核 | 受控级 | 本包修复在 tests 替身（写入面内），生产链等装配后复跑 |

## 9. 红账本核对（继承红同 ID 同数不增；新增红 = 0）

- profile 旧账 140：全绿（含替身适配后）；新增 12 条矩阵测试全绿。
- 继承红（harness 2 / server ledger）：本包未触碰 harness/server 生产代码，
  计数未动（本树未跑全 harness/server 套件的红账复验——不在本包范围，
  归各线 R0）。
- Q4 组合树 6 红：**非本分支新增**（merge 消费线自带漂移，已定性登记，
  不落本分支）。

## 10. 过程与合规声明

- 写入面：仅 `plugins/profile/**`、`specs/011-plugin-rollout/checkpoints/
  profile-api.json`、`specs/011-z1-profile/**`、`specs/014-plugin-release/**`；
  harness/server-compat/apps/products/tooling/根锁零改动（根 lock 本地重算
  未提交，S-02 登记）。scratch 组合树在 /tmp，已全部删除。
- git：分支内正常提交；**未 push、未合并他处、未动兄弟树**（B 树 11:18 的
  npm 运行是其并行会话所为，与本包无关——第一手核查记录）。
- 真实模型调用：零。子代理：零派发（全部主代理直做；未遇配额失败）。
- 本包完成后**报待审并停止**，不无限空转（宪章合规）。
