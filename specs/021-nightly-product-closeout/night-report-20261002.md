# 夜间收口报告 — 2026-10-02 夜（N1–N5）

执行者：ZCode 主执行者（唯一提交者）。合同：`night-proposal-20261002.md`。
分支 `nightly/021-harness-rollout-opencode-hermes-dsh-kilo`，开工 HEAD
`1fc304f51b`（基线检查点 865f3ab45f 之上）。真实模型调用：**零**。
未触碰用户 `~/.ordessa`、登录、密钥环、运行窗口；未 push、未 merge main、
未切分支。`.zcodeignore` 与 `docs/ui-preview/01-empty.png` 为他属改动，
未纳入任何提交。

## 逐项终态

| 项 | 终态 | 检查点 |
| --- | --- | --- |
| N1 Profile 逆向切换定位与修复 | IMPLEMENTATION_REVIEW_READY | `ebfecf9e1c` |
| N2 模型/Profile 交互回归 | CONTROLLED_UI_VERIFIED | `276c77092d` |
| N3 三品牌装配回归与汇总 | 完成（汇总见 §N3） | 本文件 |
| N4-R1 核心职责盘点 | 完成（盘点+守卫+架构事实） | `cfe7612c0f`/`24b97f91ba` |
| N4-R2 Workbench 内部整理 | 完成（纯文件归组） | `db36f13887`+`f92d8bcab1` |
| N5 资源插件接线（Skills） | CONTROLLED_WIRING_VERIFIED | `6ffdd34c45` |

## N1：Profile 逆向切换 unknown — IMPLEMENTATION_REVIEW_READY

**症状**：Profile A 会话→单独模型 B→再选回 Profile A，发送前准备返回
unknown，journal 原因 `Native provider restoration is unproven`
（用户 2026-10-02 14:37:03 UTC 事件）。

**定位（分段核对，首个失配条件）**：

1. 该消息唯一来源是 `products/server/.../profile_configuration.py` 的
   restoration 执行分支——`restoration_service.execute` 返回非 observed。
2. 真实适配器零推理探针（新工具
   `plugins/harness/packaging/pi-profile/probe-reverse-switch.py`，合成凭证、
   私有 HOME、创建走生产 `prepare_native_creation` admission 路径、
   `modelPrompts=0`）证明：**规范三步序列在已安装 v2 资产上全绿**
   （逆向重注册 observed→选回 A/first confirmed）。设计的接缝本身可完成
   逆向切换。
3. 资源漂移变体（创建后 endpoint 或凭证字节变化）在真实适配器上复现生产
   故障形状。首个失配条件：**Pi 适配器在创建任何 operation record 之前
   拒绝**（live catalogue 已有该 provider 且启动 admission 摘要与漂移后的
   provider 对象不一致；源码核实 provider-registration.mjs 所有拒绝点先于
   `records.set`）。Python 包装把这一"已答复的拒绝"折叠为
   `unknown` 并因 pending 门卡死该会话后续全部注册准备。
4. 生产当次漂移的确切环境来源（资源行改版/凭证轮换/其他）在零推理约束下
   无法定谳——登记为开放观察项，不影响修复义务（修复覆盖整个拒绝类）。

**修复（全部包装层，身份检查零放松，Escalation-Architect 两轮裁决通过）**：

- Pi 注册服务：query 检查按原求值顺序拆为白名单条件码（`PI_*`，纯名义，
  不携带任何摘要/id/值）；同 channel+owner 钉死下取得原生 invalid-params
  应答证据的 → 终态 `refused`（`PI_REGISTRATION_REFUSED`），效果一次性保持、
  绝不重发；query 对 refused 终态早退。
- registry：加性只读 `query_native_operation_state`（仅 -32602 应答判
  refused；超时/丢失/其他错误类照旧不可判定）；`_configuration_rpc` 默认
  行为逐字节不变（`fold_errors` 显式可选）。
- 产品接缝：refused → 既有 `ApplyRejected('rejected-unchanged', 码)` 词表
  （零发送许可、草稿保留、非 sticky）；unknown reason 透传条件码。
  pending 门零改动——refused 后新操作键可立即重新准备（解卡）。

**红→绿证据**：

- 单测：Pi 注册 21 项（含逐条件码、三步序列、refused 终态/解卡/钉死反例）、
  registry 状态分类 5 项（对基线代码红、新代码绿）、产品接缝 26 项。
- 真实探针：canonical 全绿；drift-endpoint / drift-credential 修复前
  `unknown + PI_EVIDENCE_UNAVAILABLE`+卡死 → 修复后
  `refused + PI_REGISTRATION_REFUSED` + `retryAfterRefusalPrepared=true` +
  零副作用（`models.json` 不存在、全局哨兵不变、进程退出 0）。证据存档
  `.cleanup-evidence/night-20261002/pi-reverse-*.json`。
- 回归：`plugins/harness/tests/` + `products/server/tests/` 全量失败集合与
  基线**逐字相同**（完整环境下 6 项既有失败：platform-secrets 真实后端 2、
  install 漂移 3、verifier 部署 1；环境不完整时的 43 项系缺包所致，补装
  editable 包后消失，非代码回归）；`apps/server` 74 失败/1178 通过与基线
  一致（inherited-red ledger）；model-provider server 282 通过 + 1 基线既有
  失败；pi-profile 打包 node 测试 13 通过。
- 未验证边界：真实聊天（含逆向切换）验收留待用户；codex/claude 的
  restart-resume 路径存在同形状 `except: pass`，因无"拒绝先于效果"等价
  证据本轮未改（登记后续项，先取证再移植）。

## N4-R1：核心职责盘点 — 完成

- 交付 `specs/021-nightly-product-closeout/core-inventory-20261002.md`
  （404 行）：五区公开入口/消费者/注册 owner、职责图与依赖/装载图分开、
  Server→Pacthold 记为合规使用。
- **两套 Settings 入口结论（源码证据链）**：两个独立注册表实例，无桥接；
  平台侧 `SettingsContribution` 注册表零产品消费者且默认产品不可达
  （宿主入口被 root view 隐藏）；Workbench `addSettingsSection` 是唯一
  活跃登记事实（6 个插件族）。已钉成 layering 回归断言。R3 决策输入，
  本轮未做任何合并（等用户批准）。
- 边界问题 B-01..B-08（file:line 级）。新增守卫：pacthold 内核方向 6 项、
  extension-host 边界 7 项、workbench 分层 8 项。两个 JS 守卫的端到端
  变异证据已由主执行者补做：向真实插件源文件注入宿主内部值导入 →
  plugin-host-boundary 红（1 failed）→ 回滚后 7/7 绿；向 model.ts 注入
  越包导入 → layering 红（1 failed）→ 回滚后 8/8 绿（变异零提交）。
- docs/architecture.md 事实更新；AGENTS.md 的旧简称差异如实标注（未改）。
- 补跑两个构建级 guard：token-single-instance（0 失败）、
  contract-ownership（5/5）。

## N4-R2：Workbench 内部整理 — 完成

按第 3 轮裁决只做纯文件归组：sidebar/sidebar-width→navigation/、
popover→overlays/、region-header→layout/、styles.ts→styles/index.ts
（`'./styles'` 导入解析不变）。model.ts/shell.tsx 不拆（闭包共享状态，
拆分属状态所有权重构，超出本轮证据标准）。公共面 sha256 前后一致
（api/workbench.ts、package.json、entry.tsx、shared/registry.ts；快照
`.cleanup-evidence/night-20261002/r2-*-sha256.txt`）；diff 为 5 个纯重命名
+3 个仅导入行修改。workbench vitest 70、node --test 守卫 7、
extension-host 103 全绿；18 扩展重建后的 extensions.lock.json 仅 workbench
entry.js 摘要更新（合法产物，随 f92d8bcab1 提交）。

## N2：模型/Profile 交互回归 — CONTROLLED_UI_VERIFIED

子代理 A 交付 6 个新测试文件、零生产代码改动；主执行者独立复验全绿。
- chat-contribution：Profile→模型/模型→Profile/无模型 Profile/模型后覆盖
  （4）；running/starting/stop-requested 下选择只 inspect+queue，不
  cancel/interrupt/二次 prompt，方法白名单断言，typing 零配置调用，真实
  completed 仍核对（6）；两会话交替+迟到应答不升级新挑选（4）；
  unknown/refused 草稿保留、告警 DOM 跨重投影同一节点、读回失败不拿历史
  当现状（4）。
- Profile Chat integration：交替会话隔离、迟到确认不覆盖新挑选、store 级
  不变量（6）。Chat 前端：普通输入/光标不触发配置路由、pane 阻止发送后
  草稿保留（2）。
- 红→绿为真实变异（已回滚，逐例记录）：M06 绑定提交守卫、running 早退+
  effect 依赖数组的合取防线、markRegistered 身份护栏、unknown 分支清草稿。
- 回归：chat-contribution 114（基线 96）、profile chat 77（71）、chat 前端
  78（73）、model-provider desktop 37。
- **边界（如实）**：全部为受控组件级证据（真实生产模块+受控替身），无真实
  Server/ACP/模型；「后操作覆盖前操作」的后端 action_seq 台账裁决在 N1
  接缝（已有 overlay 语义测试）；五契约场景的真实 Electron 端到端列入未测
  范围。sendError 页面级告警观察项已登记 known-issues（f92d8bcab1）。

## N3：三品牌装配回归与汇总 — 完成

- 三品牌系统资产 verifier 只读核验全部通过：pi `sha256:444515c3…`（与
  pi-startup-admission-v2 记录一致）、codex、claude-code。
- 默认产品 18 扩展 build 成功；root typecheck 通过；`git diff --check`
  exit 0。
- Python 全量（完整环境下）：plugins/harness 4 失败/821 通过（install 漂移
  3 + verifier 部署 1，基线逐字相同；platform-secrets 2 项偶发 flaky）、
  products/server 全绿、apps/server 74 失败/1178 通过（inherited-red
  ledger，与基线一致）、pacthold 218 通过、model-provider server 282 通过
  +1 基线既有。全部按测试 ID 对比：**零新增失败**。
- JS 受影响套件：chat-contribution 114、profile chat 77、chat 前端 78、
  model-provider desktop 37、workbench 70+7 守卫、extension-host 103、
  contract-ownership 5、pi-profile 打包 13——全绿。
- Profile 缺席装配直证：`test_product_injects_real_turn_ports_without_profile`、
  `test_without_profile_choice_applies_through_shared_c4`、
  `test_profile_unload_keeps_shared_authority_and_model_route` 等 4 套件
  64+29 项通过——实际 route 不依赖 Profile ledger，无自动建全局 Profile
  旁路（组合测试 + N4-R1 边界守卫）。
- **未验证边界**：真实聊天（含三品牌真实会话、逆向切换实机复验）未验收，
  留待用户；本报告不声明“产品全部通过”。

## 费用

真实模型调用 unavailable（本轮为零）；无任何 API key 读取。

## 待安装项

本夜新增待安装项：**无**（无新系统资产构建；Pi 使用的仍是上一班已安装并
verifier 核验的 `profile-pi-startup-admission-v2`）。既有未装/验证器缺口
（opencode/hermes/dsh/kilo）见 `docs/known-issues.md` 对应行——非本夜
产生、状态未变。

## 明早用户最短操作清单

1. **真实聊天验收**（唯一必须由你完成的验收）：启动/重载产品（系统资产与
   `~/.ordessa` 不变；当前安装的 Pi 资产为上一班的
   `profile-pi-startup-admission-v2`，`sha256:444515c3…`，见 §N3——本次
   验收即在该资产上进行），走一次 Pi 首轮 Profile → 单独模型 → 逆向切回
   Profile → 发送。若逆向再失败：journal 现在会记录白名单条件码
   （unknown 携带 `PI_*` 码）或诚实的 `rejected-unchanged +
   PI_REGISTRATION_REFUSED`——把码转给执行者即可精确定位，无需截图猜测。
2. **R3 裁决**（一句话）：Settings 登记事实选 Workbench（平台侧入口零
   产品消费者、默认产品不可达，冻结即可，无需迁移/转发）。
3. **AGENTS.md 措辞**（一句话确认）：是否按 architecture.md 的修正表述
   更新 §"What this repo is" 的"Profile / Provider / Workboard"段。
4. **资源插件后续批次决定**（一句话）：Skills 已闭环验证
   （CONTROLLED_WIRING_VERIFIED，§N5）；是否放行 MCP / Prompts 按同形态
   推进（先读 spec→链路盘点→单闭环，各约 2–3 小时）。
5. 可选：model.ts / shell.tsx 拆分与 harness-availability 迁移（R4）已在
   盘点中列明证据标准，留待白天批次。

## N5：资源插件接线（Skills）— CONTROLLED_WIRING_VERIFIED

门控历程：第 3 轮裁决设定严格门槛（剩余时间 ≥ 闭环估时 1.5 倍、N3 已交付、
无 INSTALL_REQUIRED）；第 4 轮裁决在 01:10 实际窗口下批准启动，且至多
Skills 一个资源、不碰打包/安装/wire 面。N3 汇总交付后执行。

**Skills 单资源闭环（已验证，检查点 6ffdd34c45）**：

- 链路盘点（只读）：`ordessa.skills` 在 18 扩展启用清单中；
  `plugins/assets/skills/` 已具备 profile_facet/profile_contribution/
  harness_adapters（三品牌 + apply_chain/producer）；组合级测试已走
  `skills.list`/`skills.resolve` wire 派发；各段（六层解析 g05、
  apply_chain t13、producer t14、facet contribution）各有密测试——缺的
  是把它们串成一条闭环。
- **闭环测试（新增 `test_n5_single_resource_closed_loop.py`，5 项）**：
  用生产装配路径（`SkillsService(profile_services=…)` 派生
  `ProfileApiLayerPort`）在隔离数据根上走真实全链：合成技能安装+批准 →
  Profile 稀疏选择（经公开 facet API 写、`resolve_preview` 读）→ 共享
  解析器（`selectedBy.layer == "profile"`）→ Harness 侧
  `agent-box.skill@1` 交付集（契约名、treeDigest、修订源目录逐项核对）。
  边：项目级禁用只影响本项目（层序：Profile 层高于 project 层，按解析器
  钉定顺序如实断言）、系统级 user-global 选择、A/B 会话覆盖交替不串、
  无 Profile 时原生选择照常交付、未安装修订拒绝交付且零对象。
- **红→绿（真实变异，已回滚）**：facet 读取清空 → 3 红 → 回滚 → 5 绿。
- 完整 skills 套件 438 通过；diff-check exit 0。
- **如实边界**：交付等级按 spec 钉在 `projected`（原生会话内加载证据不在
  本轮范围）；默认发布装配是否携带 Skills 是已登记的升级裁决
  （docs/known-issues.md，2026-10-01），本轮未动；零模型调用。

**MCP / Prompts（未启动，保留下一个批次）**：按第 4 轮裁决本轮至多
Skills 一个资源。`ordessa.asset-mcp` 的服务器组合缺位同样在
known-issues 登记（default composition 缺 McpAssetServerPlugin）；Prompts
未盘点。两者可按 Skills 同形态（先读 spec→链路盘点→单闭环）在下一批次
推进。

## 登记项（本轮新增）

- **开放观察**：生产 14:37 逆向切换失败的确切环境漂移源未定谳（零推理
  约束）；修复后该类事件会带条件码落地 journal，下次发生即可归因。
- **后续技术债**（不在本轮）：codex/claude restore 的同形状 `except: pass`
  （先取证"拒绝先于效果"再移植 B/C 方案）；`profile_configuration._transitions`
  无淘汰机制（容量 4096 上限，既有问题）；B-05/B-06 connectors type-only
  跨层 import 的防值 import 守卫（由边界 owner 采纳）；B-08 chat token
  字面量补入 TOKEN_WATCHLIST；平台侧 7 个零消费者服务端口的去留。
- **环境备注**：夜间发现 `.venv` 缺多个 editable 包（model-provider、
  profile、profile-contribution、skills 等）已按 `docs/baseline.md` 闭包
  补齐；此前记录的部分"既有失败"计数系环境不完整所致，完整环境下
  plugins/harness 真实既有失败为 4 项（install 漂移 3 + verifier 部署 1；
  platform-secrets 2 项为偶发 flaky）。
- **证据目录**：本夜探针/快照存于 `.cleanup-evidence/night-20261002/`
  （pi-reverse-*.json、r2-*-sha256.txt）；该目录按设计 gitignore 不提交。
