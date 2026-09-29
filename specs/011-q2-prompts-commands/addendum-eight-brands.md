# Addendum — 八家品牌面扩展与收尾（prompts + command-templates）

**裁定**（用户，2026-09-28）：①「指令与人格」**不另立新域**——本包的 prompts 域（`plugins/assets/prompts`）即该域，三种语义（instruction 追加 / persona 角色层 / systemReplacement 显式替换）沿用 `docs/design/prompts/harness-adapters.md` 既有裁定；②品牌面从 4 家（Pi/Codex/Claude 必做 + Hermes 后续）**扩到八家**（新增 OpenCode/dsh/Qwen/Kilo）；③本域归属 plugin 线（`codex/plugin-prompts`、`codex/plugin-command-templates` 两支）。

**命名纪律**：一律用插件目录名（prompts / command-templates）指代，不用历史线代号。

## 基线与起点（1+x，开工时重测）

- 起点 = 当时 `main` 实态 + merge `codex/plugin-prompts` + merge `codex/plugin-command-templates`（开工时重新核对两支 SHA 与 main 头，不沿用任何上一阶段实施树的树内状态）。
- **依赖**：Profile facet 端口（profile 插件的 r2 交付，含 import 修复）已并回——T08 及以后的任务以此为前置；未并回前 T03–T07 可先行。
- 环境按 `docs/baseline.md`（含既有补录要求：`-e plugins/assets/prompts`、`-e plugins/assets/command-templates` 若缺则登记 IR）。

## 账实偏差的处理（R0 必做）

分支任务账 36 项未勾/1 勾，但内容库实现（T03–T06 对应的 G01–G08 门测试文件）已存在。开工第一件事：**逐任务实测盘点**（以分支实现 + 测试实跑计数为准，不以账面勾选为准），把"已实现未记账"的项补勾并附证据 SHA，"账勾实缺"的项如实回退。此后账实一致往下走。

## 剩余工作（原账未勾项，语义不变）

prompts：T07（三品牌 adapter assess/compile/verify，G09–G12）→ T08（Profile facet 接线，G13/G14）→ T09（Settings 管理页，G15/G16）→ T10（Profile editor，G17）→ T11（提交路径冻结语义，G18）→ T12（三品牌真实装载受控证据，G19）→ T13/T14（产品装配与隔离差分，G20–G22）→ T15（报告 REVIEW_READY）。
command-templates：按其原账 T00–T09+ 顺延（G09–G19/G22/G23 清零）→ R4 查漏 → 交付。
两域完成后按 1+x 并回，交付以提交 SHA 计。

## 新增任务：八家品牌面（追加于 tasks.md 的 EXT 段）

设计事实（出自 `docs/design/harness-configuration/harnesses.md`，证据等级=官网/固定源码盘点，未实测）：

| 品牌 | 已核原生机制 | 候选路线（待核实后定） | 必须补证据 |
| --- | --- | --- | --- |
| OpenCode | `instructions` 字段 + AGENTS 兼容发现；层叠是**合并**非整文件替换 | instructions 字段注入，不覆写项目 AGENTS | 相对路径/URL/继承规则；多来源层叠顺序；ACP 变更面未实测 |
| dsh | `agent-instructions`（文件候选/预算/根发现）；**persona prefix/suffix**（八家唯一原生 persona 概念）；system-prompt 与 runtime context | persona 对接原生 prefix/suffix；instruction 走 agent-instructions | 文件候选发现顺序与预算语义；prefix/suffix 与本域合成规则（replacement→persona→有序 instructions）的组合；runtime context 边界 |
| Qwen | QWEN.md、`context.fileName`/import/includeDirectories、规则文件 | context 指向受管内容，不覆写项目 QWEN.md | import/includeDirectories 作用域；"memory"≠自动记忆陷阱；版本门槛 |
| Kilo | `instructions`、agent/default_agent 选择 | instructions 字段注入 | kilo.jsonc 层叠（用户/项目/.kilo）；不再隐式读 OpenCode 目录；schema 深度 |

约束沿用 `docs/design/prompts/harness-adapters.md` 全部规则：三语义不混称、合成顺序固定、单 adapter 写入、baseline 先于新增、验证分层（materialized ≠ confirmed）、无法安全更新走重启-resume、项目文件不碰。四家新增格一律**先判可用/不支持/未知 + 反例**，不为凑八家宣称支持；判定表并入 `docs/design/prompts/harness-adapters.md` 的原生机制表（本 addendum 已预置四行）。

## 门与 DoD

- 原包 G 门全部沿用；G09–G12（adapter conformance）与 G19（真实装载）**矩阵扩到八家**，缺格=该品牌该语义不得报 supported。
- dsh 的 persona prefix/suffix 对接属新语义格，须独立反例（组合后顺序、移除恢复 baseline）。
- 交付：两域报告 + 能力矩阵（八家 × 三语义）+ 未验项逐条 + SHA；不 push、不自动合并。
