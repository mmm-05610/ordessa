# Implementation Plan — Plugin 首版收口（三品牌）

**Branch**: `014-plugin-release` | **Date**: 2026-09-28 | **Spec**: [spec.md](spec.md)

**Input**: [spec.md](spec.md) · 三路实测底账（2026-09-28，主会话研究；关键事实已内联本文件，执行者 R0 须复核）

## Summary

把 plugin 侧从"011 各线 PARTIAL/REVIEW_READY 的归并中间态"补成**三品牌首版可验收**：Profile 解锁与产品就绪（A）、Provider/Model 真实应用链（B）、Chat 命令/附件/三态真实接缝（C）。三包写入面互不重叠（plugins/profile、plugins/assets/model-provider、plugins/chat+plugins/agent/{contracts,sessions,conversation}），全部基于 main（491aa92392）重建——**这是硬前提**：归并分支的旧基线缺 main 上的 harness-api/chat/connectors 内容，不并主干无法消费已发布契约。

技术路线：plugin 半边真实实现 + 受控 E2 矩阵（fake endpoint 为上限，E3 禁跑）+ 跨线需求全部走 [seams.md](seams.md) 接缝请求单（用户逐条与 core 线讨论，不预划界、不越界代写）。

## 关键实测事实（执行者直接使用，R0 复核）

| # | 事实 | 出处 |
| --- | --- | --- |
| F1 | profile-api r1 断裂 import **已修好**在 `codex/plugin-profile`（`plugins/profile/src/ordessa_profile/plugin.py:19-21`，指向 `pacthold_runtime_compat.resource_contracts`）；A 的工作是 r2 交付登记与解锁复验，不是改代码 | 分支实测 |
| F2 | REQ-Z3-1/2 的目标面**已在 main**：C2 注册点 `plugins/harness/src/ordessa_harness/contributions.py:21`（重复 adapter_id 拒绝 :187-190）；C4 `ConfigurationApplicationService`（`.../application/configuration_service.py:150`，ctor 强制注入 permits/journal）；permit 机制 `apps/server/src/ordessa_server/acp_admission.py:94-140`。api-requests.md 的冻结文本已过时，**按 main 实际符号对齐** | main 实测 |
| F3 | Chat 三项的真实断点**在中间层**：connectors（三态/命令/附件 port）与 Server 端 authorize 都已实现且有测试，但 facade（plugins/agent/contracts + sessions）无对应成员、`getNativeCommands` 全仓零消费、chat `facadeCommandCatalog` 恒 absent | main grep 实测 |
| F4 | Claude Code **不走 Go 桥**（Go 桥仅 codex\|pi，`cmd/acp/main.go:27-30`），走钉版官方 `@agentclientprotocol/claude-agent-acp@0.81.2`（`plugins/harness/packaging/claude/` 离线闭包，Work Order 43 生产化，自带 fake-endpoint 受控探针架式）。**附件＝旧负证据已推翻（源码实证）**：0.81.2 initialize 声明 `promptCapabilities:{image:true,embeddedContext:true}`（`acp-agent.js:1108`），图片双向转换在案（:7364/:7682），`resource_link`→URI 链接文本（:7341）；旧"握手 promptCapabilities 空"是 0.77 时代遗留观测（升版未重探）→ P-D 修复包。**命令目录＝未探针**：`parseNativeCommands` 品牌无关，adapter 是否播发 `available_commands_update` 无正反证据 → PC-10 探针定夺 | main 实测（adapter dist 源码直读） |
| F5 | codex/claude CLI 二进制本机不存在；Pi 0.86.1 曾离线探针通过 → 三品牌 E2 以 in-repo adapter + 受控 fake endpoint 为上限（Z3 verification.md E2 定义允许），真实 CLI 装载格如实 unknown | Q4/Z3 report |
| F6 | 各插件分支树内无 `plugins/runtime-compat`；`pacthold_runtime_compat` 靠 venv `-e plugins/runtime-compat` 提供；`docs/baseline.md` 安装清单**缺 `plugins/profile` 与 model-provider 各包**（R0 补录并登记 S-10） | baseline.md:41-43 |
| F7 | 011 tasks.md 已被主会话重置为未勾选裸表（main 491aa92392，"归并≠验收"）；真实完成态以各线 report.md 为准 | main 实测 |
| F8 | integration-request §6 的 C7 import map 三处机械切换**已在 main 落地**，勿重复做 | chat research |

## 分包方案：4 个实施包（A/B/C 互不重叠并行；P-D 独立于三包，只与 P-C 在附件 DTO 形状上对齐）

| 项 | P-A profile | P-B model-provider | P-C chat | P-D claude 附件 |
| --- | --- | --- | --- | --- |
| **worktree** | `worktrees/014-a-profile`（`codex/014-a-profile`） | `worktrees/014-b-model-provider`（`codex/014-b-model-provider`） | `worktrees/014-c-chat`（`codex/014-c-chat`） | `worktrees/014-d-harness-claude`（`codex/014-d-harness-claude`） |
| **基线** | main 491aa92392 + merge `codex/plugin-profile`（已完成） | main 491aa92392 + merge `codex/plugin-model-provider`（已完成） | main 491aa92392（chat 已在 main，无合并） | main（plugins/harness 已在 main，无合并） |
| **写入面** | `plugins/profile/**`、`specs/011-plugin-rollout/checkpoints/**`（仅 profile-api 条目）、`specs/011-z1-profile/**`（报告增补）、`specs/014-plugin-release/reports/P-A-*.md` | `plugins/assets/model-provider/**`、`specs/011-z3-model-provider/**`（报告增补）、`specs/014-plugin-release/reports/P-B-*.md` | `plugins/chat/**`、`plugins/agent/{contracts,sessions,conversation}/**`、`specs/011-z2-chat/**`（报告增补）、`specs/014-plugin-release/reports/P-C-*.md` | `plugins/harness/**`（窄用：packaging/claude 探针、harnesses.toml、src/ordessa_harness/claude/**、tests/test_capability_declarations.py、claude-production-packaging.md）、`specs/014-plugin-release/reports/P-D-*.md` |
| **消费** | foundation（经 main） | harness-api、chat-api（经 main）；**profile-api r2 = P-A 交付 SHA**（弱依赖：未交付前 fixture 先行并登记） | harness-api、chat-api r3、connectors（均在 main） | connectors 附件 DTO（只读，对齐 PC-9 冻结形状） |
| **禁区** | 其他 plugins/**、products/**、tooling/**、根锁、packages/**、apps/** | 同左 + plugins/harness/**（只读消费） | 同左 + plugins/commands/**（只读；它不是 Chat 菜单） | connectors/**（只读消费其附件 DTO）、plugins/chat/**（P-C 域）、products/**、tooling/**、根锁 |

**P-D — claude 附件通路（harness）**：worktree `worktrees/014-d-harness-claude`（分支 `codex/014-d-harness-claude`，基线 = main，plugins/harness 已在 main，无需合并）。写入面：`plugins/harness/**`（窄用：`packaging/claude` 探针、`src/ordessa_harness/harnesses.toml`、`src/ordessa_harness/claude/**`、`tests/test_capability_declarations.py`、`docs/server-round1/fullstack/claude-production-packaging.md` 证据）+ 014 报告。目标：用钉版 0.81.2 的第一手探针推翻 0.77 时代的附件负证据，翻绿 `attach`，并把 claude 通路附件投递接通（图片=真实附件块、非图片=resource_link URI 链接，audio 未声明——语义如实呈现）。与 P-C 分工：P-C 管聊天侧通用附件 UI/refs（PC-3/PC-9），P-D 管 harness 侧能力声明与通路。用户已裁定：必须解决（2026-09-28）。

**依赖关系**：P-B 的 PB-6（Profile glue）依赖 P-A 的 PA-2 交付 SHA；其余全并行。P-B 若先行到 PB-6 而 A 未交付，用受控 fixture 推进并登记依赖，**不得**自己改 plugins/profile。

## 跨包集成归属

- **包间**：B 消费 A 的 SHA（合并式消费：merge A 分支或 cherry-pick 对应提交，记录 SHA 与复跑计数）；C 独立。
- **对 core（pi/013 线）**：一切 `products/**`、`tooling/**`、根锁、packages/apps 的改动 = [seams.md](seams.md) 请求单，由用户转交讨论；本线**零越界**。装配实测（extensions.json 启停生效、产品三组合、浏览器矩阵）在接缝落地后的集成轮做，本期只交"插件侧就绪 + 启用清单 + 受控证据"。

## 验证与证据（每包必交）

| 项 | 要求 |
| --- | --- |
| R0 基线 | 环境安装命令逐条记录（含 F6 补录）、各套件计数与退出码、消费 SHA 回填 |
| 先红后绿 | 每个真实接缝的正例 + 反例（缺席/拒绝/断连），守卫在资源缺席时必须失败 |
| E2 矩阵 | 三品牌 × 该包门矩阵逐格证据；缺格如实 PARTIAL，该品牌不得报 ready |
| 红账本 | 继承红（Harness 2 / Server 67 等）同 ID 同数不增；新增红 = 0 |
| 诚实缺席 | 生产链未通的部分以 refused/unknown/absent 呈现并说明，不假绿 |
| 交付 | 终提交 SHA + report（`specs/014-plugin-release/reports/P-*-report.md`）+ 各线 011 report 增补段 |

## 写入面纪律（三包共同）

1. 只写自己的写入面；兄弟树与 core 只读。
2. 已发布契约（foundation/harness-api/chat-api r3/permissions-api r6，经 main）**只消费不修改**；确需变更 → 停该项、写接缝请求、报主会话。
3. 不操作 git 远端：不 push、不合并到 main/core、不动其他 worktree；分支内正常提交，按 012 以 SHA 交付。
4. 不 kill/restart 用户服务（`docs/known-issues.md` §services）；零真实模型调用（E3）。
5. 受控 fixture 明确标注；不得以局部测试冒充整线通过；PARTIAL 不写成 DONE。
6. 子代理（若开）：只做声明的独立单元，不写契约/报告、不执行 git 写操作；深度 ≤1、并发 ≤4，请求数记入报告。

## 完成口径

014 三包完成后报告**「plugin 侧三品牌首版就绪（受控证据级）」**，不是「首版已发行」：F2/F3 的最终验收要等产品装配（接缝落地）后在真实安装产物上复跑；真实模型调用仍需另行授权。此口径与 013 的「core 发行能力就绪」对偶，两线在发行门 F1–F5 汇合。

## 插件改动清单（对照 011 plan 所有权）

| 目录 | 本期动作 | 所属包 |
| --- | --- | --- |
| `plugins/profile/**` | r2 交付 + 桌面三包补齐 + 品牌矩阵受控版 | A |
| `plugins/assets/model-provider/**` | 真实应用链（C2/C4/permits/error-families）+ 三品牌 E2 + profile glue | B |
| `plugins/chat/**`、`plugins/agent/{contracts,sessions}/**` | 命令目录/附件/三态接通 + generation 透出 | C |
| `plugins/agent/conversation/**` | 退役（语义已迁 chat；等价测试覆盖已声明） | C |
| 其他 plugins/** | 只读或不动 | — |
