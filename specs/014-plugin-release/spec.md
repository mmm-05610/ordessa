# Feature Specification: Ordessa Plugin 首版收口（三品牌）

**Feature Branch**: `014-plugin-release`（实施树 `codex/014-a-profile` / `codex/014-b-model-provider` / `codex/014-c-chat` / `codex/014-d-harness-claude`）

**Created**: 2026-09-28

**Status**: Draft（随派单一并交用户审）

**Input**: 用户裁定（2026-09-28）：首版按 **Pi / Codex / Claude Code 三品牌全过发行门**；plugin 侧本期开 A/B/C 三棵树；C0 未完成的接缝不预划界，**届时提出与用户讨论**（汇总于 [seams.md](seams.md)）；同日追加裁定：**Claude 附件必须解决**（不接受缺席）→ 增 P-D（旧负证据经 0.81.2 源码实证推翻，见 S-07）。

**上游依据**: `docs/release/first-release-handoff.md`（发行门 F1–F5；注意该文件尚未入库）、`specs/011-z1-profile/report.md`、`specs/011-z2-chat/report.md`、`specs/011-z3-model-provider/report.md`、`specs/012-branch-consolidation/README.md`（1+22 分支纪律、以 SHA 交付）、`specs/013-desktop-product/plan.md`（013 登记的插件线缺口：chat 主题 C-05、harness 可用性 C-08——两者等 013 契约实现落地后再排，不在本期）。

---

## 范围裁定（用户已定）

| 项 | 裁定 |
| --- | --- |
| 首版品牌承诺 | 三品牌全过门；**桥级握手、假对端、仅有配置形状不算可用**（handoff F2 口径） |
| 真实模型调用（E3） | **未授权，一律不跑**；固定真实 adapter + 受控 fake endpoint 的 E2 允许（verification.md E2 定义） |
| `products/**`、`tooling/**`、根锁 | 归 core（012 规则）；本线只写 `plugins/**` 自己的目录，跨线需求一律走 [seams.md](seams.md) |
| MCP / Subagents / Skills 全能力、Q2 prompts 域 | 不阻塞首版，不塞进本期三包 |
| 浏览器矩阵 / Electron 门 / 产品装配实测 | 待产品装配后；本期以受控与 jsdom 证据为界，未验项如实登记 |
| 交付形态 | 按 012：以提交 SHA 交付，不发阶段 ready 分支；**不 push、不合并主干**（git 检查点归用户/主会话） |

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 三品牌都能用 Profile 选择与覆盖 (Priority: P1，包 A)

用户在任一品牌会话里选择/切换 Profile、做会话级覆盖、执行 reset，各品牌配置面按自己的 dialect 正确落盘；profile-api 作为公共契约可被 Skills/Subagents/MCP/Permissions 消费。

**Why this priority**: F3 门要求"Profile 切换遵守会话边界"；profile-api r2 是 Q1/Q3/Q4/Q5 四条线的共因解锁件。

**Independent Test**: 受控品牌矩阵（pi/codex/claude-code × 字段投影/覆盖清除/reset/restart-resume）经**真实 adapter 接口**驱动（不是只调 ProfileDB）；四线解锁复验在组合树实测。

**Acceptance Scenarios**:
1. **Given** 三品牌受控对端，**When** 切换 Profile 并应用，**Then** 每品牌字段投影与该品牌 golden 渲染一致，无跨品牌残留。
2. **Given** 会话内已做覆盖，**When** 切换 Profile，**Then** 覆盖清除且不影响其他会话。
3. **Given** Q1/Q3 消费树合并本线 profile-api r2 SHA，**When** 跑 facet 测试，**Then** Q1 的 6 条、Q3 的 28 条从红转绿（旧账口径 433 / 671，允许实测漂移但须记录）。
4. **Given** 桌面三包（profile-api / profile-frontend / profile-chat）补齐 manifest+build，**When** core 启用，**Then** 可直接进 extensions 通道，无需再改插件。

### User Story 2 - Provider/Model 切换下轮真实生效 (Priority: P1，包 B)

用户原子地选择 (provider, model)，下一轮经**真实应用链**（注册→plan→apply+permit→verify→prompt）生效；双会话隔离；受控重启 resume 同一原生会话。

**Why this priority**: F3 门"provider/model 切换遵守会话边界"是首版基本交互范围的硬项；现状 MP-05/06/11 生产闸门全缺。

**Independent Test**: 三品牌 E2 受控矩阵（in-repo adapter + 受控 fake endpoint），验证**下游实际路由**而非 option ack。

**Acceptance Scenarios**:
1. **Given** A/B 双会话不同 choice，**When** 交错两轮，**Then** 各自路由正确、互不串扰。
2. **Given** apply+verify 已完成且持有一次性 permit，**When** 下次 prompt，**Then** 使用新 choice 并有下游路由证据。
3. **Given** 无 permit，**When** 裸调用 apply，**Then** 类型化拒绝（不静默放行）。
4. **Given** 品牌进程受控重启，**When** resume，**Then** 同 native id、HOME 字节不变、`session/new` 冒充 resume 必红（MP-06）。
5. **Given** 重叠 adapter 注册，**When** 第二个注册，**Then** registry 拒绝且第二 client 必红（MP-11）。

### User Story 3 - 斜杠命令与附件经真实接缝生效 (Priority: P1，包 C)

用户打开斜杠面板看到**品牌原生命令目录**的真实投影；附件经 prepare→ref→submit 真实传输，内容哈希往返一致。

**Why this priority**: F3 门明文"命令与附件经真实接缝生效；仅有 UI 控件、仅能保存数据、失败后静默回退均判红"。

**Independent Test**: 命令目录经 connectors→facade→chat 全链四态投影；附件受控往返 sha256 一致。

**Acceptance Scenarios**:
1. **Given** 品牌 ACP 通道有原生命令目录，**When** 打开斜杠面板，**Then** 目录为该品牌真实命令集的 ready/loading/error/absent 四态投影，无伪命令。
2. **Given** 附件能力就绪，**When** 选择附件并发送，**Then** prepare 产出不透明 ref（含 sha256），submit 携带 refs，对端收到的内容哈希一致。
3. **Given** prepare 被拒，**When** 提交，**Then** 附件保留在草稿并显示原因，不静默丢弃。
4. **Given** Claude Code 通道（官方 claude-agent-acp 0.81.2；附件能力由 P-D 重探针翻绿，命令目录由 PC-10 探针定夺），**When** 查看命令/附件，**Then** 有证据即接线、无证据则诚实缺席 + 原因，不留空也不假绿；附件语义分层如实（图片=真实附件块、非图片=URI 链接、audio 不宣称）。

### User Story 4 - 发送结果三态可知 (Priority: P1，包 C)

提交结果是 `accepted / refused(reason) / unknown` 可判定；unknown 保留 requestId、禁止自动重发；拒绝不清草稿。

**Why this priority**: "失败后静默回退判红"的反面就是三态可知；现状 `send(): Promise<void>` 无法判定。

**Independent Test**: 受控三态注入下，chat→facade→connector→server 逐级保真回归。

**Acceptance Scenarios**:
1. **Given** 服务端拒绝提交，**When** send 返回，**Then** `refused(reason)` 且草稿保留。
2. **Given** 断连后结果不可判定，**When** 观察，**Then** `unknown`、requestId 保留、无自动重发。
3. **Given** admission 后端未就绪（S-06 未落地），**When** 生产环境提交，**Then** 诚实 refused/unknown，**不得**假绿成 accepted。

### User Story 5 - 能力缺失时诚实缺席 (Priority: P1，全部三包)

任一接缝/能力缺失时，UI 与测试都呈现缺席与原因，不假可用。

**Acceptance Scenarios**:
1. **Given** 任一上游（目录/附件/admission/接缝）缺席，**When** UI 呈现与门执行，**Then** 显示缺席原因；守卫在资源缺席时**必须失败**（缺席即红）。
2. **Given** 某品牌 E2 某格缺证据，**When** 汇报，**Then** 该品牌不得报 ready，整体只能 PARTIAL 并逐条列缺。

## 明确不在本期

真实模型调用（E3）· MCP/Subagents/Skills 全能力 · Q2 prompts 域收尾 · 013 两缺口（chat 主题收敛 C-05、harness 可用性 C-08）· 产品装配与 deb 实测 · 浏览器矩阵/Electron 门 · onboarding · push/远端发布。
