# 接缝请求单（014 ⇄ core/013 线）

> 用法：plugin 线对 core 线的全部跨线请求与答复账。plugin 侧在接缝落地前以受控 fixture / 诚实缺席推进，不越界代写。状态：`open` / `relayed`（已转 core）/ `agreed`（归属/做法已定）/ `landed`（已落地，回填 SHA）。**本文件已提交进 main，core 线可直接在此表下方回填。**

## 2026-09-28 core 线答复摘要（013 现状：三包完工未提交，基底 7adf5aeaca，plugins/** 零改动；三条折扣：红账本复验不完整 / P-C 接占位桩 / wire 生产接线仍 fixture）

| id | 请求 | 归属与状态 | 说明 |
| --- | --- | --- | --- |
| S-00 | 发行门依据入库（`docs/release/` + `specs/013-desktop-product/`） | core **INT-05 入库** | specs/013 已在 `codex/013-desktop-product-plan @ 7adf5aeaca`，未进 main；docs/release 仍未跟踪 |
| S-01 | `products/desktop/extensions.json` 启停 | **装配动作归 core；启用清单归 plugin 线（已给，见下）** | 启用：`ordessa.chat-api`、`ordessa.chat`、`ordessa.profile-api`、`ordessa.profile-frontend`、`ordessa.profile-chat`；退役：`ordessa.agent-conversation`（**条件**：P-C 完成等价覆盖核对后确认，见 PC-6）。core 提醒：`default_plugins()` import 的 `ordessa_permissions_adapters`/`ordessa_sandbox_adapters`/`ordessa_sandbox_backend` 三个发行版装配前必须装齐 |
| S-02 | `extensions.lock.json` 与根 lock | core **INT-02 定稿** | extensions.lock 是 `tooling/build-all.mjs` 的**产物**（每次构建重写），非源文件；`@assistant-ui/react` 摘除与 P-B 新增 `server-bridge` workspace 一并在 INT-02 干净构建重算 |
| S-03 | Server 默认插件集增 profile 入口 | **装配动作归 core**；model-provider 装配须在 S-08① 退役之后 | 同 S-01 清单；顺序约束已双方确认 |
| S-04 | `tooling/vitest-extensions.mjs` CONTRACT_SOURCES +2 行 | core 补；**路径已给** | `plugins/chat/api/src/contract.ts`、`plugins/profile/api/src/contract.ts`（均实测存在） |
| S-05 | 附件 prepare 生产 owner + `BackendAdmissionState` 供给 | **拆分裁定**：prepare/verify/release 语义、过期、跨连接规则=**插件业务**（plugin-layout §3）；core 只出「受信字节通道 + 摘要完整性校验」机制；Go 桥收非图片 resource link 归 harness 线。**DTO 冻结归 plugin 线**（P-C 窄口任务：`AcpAttachmentPreparePort` DTO 补 `preparedId`，SHA 交 core 后 core 再接）；`BackendAdmissionState` 生产供给归 plugin 线 harness 部分（P-D，第二批） | 互等解除：我们先冻 DTO |
| S-06 | admission `ready=False` 翻转链 | **机制归 core（在做）**：fail-closed 门 + 从产品组合取 authority + 注入观测事实；**不编码"什么算被许可"**（业务归 Q5）。依赖 plugin 侧两件：Q5 authority、harness `native_evidence` —— **均归 plugin 线，已排 P-D（014 第二批，A/B/C 收口后）**；core 机制侧可先行，互不阻塞 | 顺序答复已给 |
| S-07 | Claude Code 命令目录/附件承载 | **拆开（2026-09-28 二次修正）**：Claude 有 ACP 桥——钉版官方 `@agentclientprotocol/claude-agent-acp@0.81.2`（`plugins/harness/packaging/claude/` 离线闭包，Work Order 43），不走 Go 桥（Go 桥仅 codex\|pi）。**命令目录＝未探针（不是 unsupported）**：connectors 的 `parseNativeCommands` 品牌无关解析标准 ACP `available_commands_update`，adapter 是否播发无任何正反证据（capability 表本不记命令项）→ P-C 增 PC-10 受控探针（沿用 packaging/claude 既有 fake-endpoint 架式实测 pinned adapter）：播发→同一 NativeCommandReader 路径接线翻绿；不播发→诚实 absent+原因。**附件＝有第一手反证**：`harnesses.toml:86-89` 诚实移除 `attach`（真实握手 promptCapabilities 为空；对照 codex 行有 `attach`）；翻绿需 harness 线升级 adapter/补承载并重新取证。core 的「unsupported 标注」建议**仅适用于附件项** | 命令=探针项；附件=裁定项 |
| S-08 | compat/旧 writer 退役三件事 | **归 plugin 线（core 确认不碰插件文件，只配合 products 装配）**，**集成波次串行执行**（不在 A/B/C 并行段做，防 A/B 在 server-compat/core_wire.py 互撞与中途破坏 harness）：① server-compat `model_configs` writer（`core_wire.py:238-276`）退役→再装 model-provider；② harness 品牌渲染（`native_materialization.py:114-145`）退役（B 的 adapters 金样承接）；③ profile 旧 writer（harness `generic/profile_*.py`、`harness-profile-store` entrypoint、`{claude,hermes,opencode}/profile*.py`、server-compat `server_profiles`）退役 + `agent-box.profile@1` **双声明仲裁**。A 出 ③ 的裁定与清单（PA-7），B 出 ①② 的清单与装配顺序（PB-7）；执行时机=新 owner 就位 + core 装配排期后 | 已认领 |
| S-09 | canonical SessionRef 服务端映射 | **core 整条撤回**：会话业务语义归 session 域（`plugins/agent/sessions`），core 只在传输带不透明稳定 id。**plugin 线认领**：排 014 后续波次，产出「方案 + 迁移记录」设计件后**请用户确认**（数据兼容敏感）方可实施 | 已认领（设计先行） |
| S-10 | `docs/baseline.md` 安装清单补录 | core 补；**清单已给** | pip 可编辑包新增：`plugins/profile`（ordessa-profile）、`plugins/assets/model-provider/server`（ordessa-model-provider）、`.../adapters`（ordessa-model-provider-adapters）、`.../profile-contribution`（ordessa-model-provider-profile） |
| S-11 | desktop PluginContext wire invoke 生产绑定 | **半 landed**：`packages/desktop-platform/server-bridge/src/wire-port.ts`（`HttpWirePort`，含测试）已交付；宿主接线 `apps/desktop/electron/main.ts:109` 仍 `createFixtureWirePort()`，切换点归 core **INT-01**。P-B 升验收口径：「接口与实现已交付、生产绑定在 INT-01」，R0 直接消费 `HttpWirePort` 类型 | agreed |

## core 侧三条红线（双方遵守，已写进各 dispatch 简报）

1. core 不定义业务语义（S-06 只做"有 authority 就过、没有就拒"）。
2. core 不实现插件 port 的业务部分（S-05 只出字节通道与摘要校验）。
3. core 不动业务标识（S-09 撤回；会话标识变更只能由会话域出方案+迁移记录+用户确认）。

## plugin 侧待办回执（对 core 三问的答复，2026-09-28）

1. **S-06 顺序**：Q5 authority 与 harness `native_evidence` 均在 plugin 线，已排 **P-D（014 第二批，A/B/C 收口后开）**，同包并行两件；core 机制侧先行不阻塞。
2. **S-05 DTO**：plugin 线先冻结——P-C 增窄口任务 PC-9（`AcpAttachmentPreparePort` DTO 补 `preparedId`，仅 DTO+测试，不动实现），交付 SHA 后 core 再接 Server DTO。
3. **S-01 清单**：见上表 S-01 行（`agent-conversation` 退役以 P-C 覆盖核对确认为条件）。

## 转交记录

- 2026-09-28：S-00…S-11 首次问询经用户转 core；同日 core 逐条答复（013 现状+归属裁定+三回执问题），本表已按答复回填。core 侧如需继续回填，按 `日期 / 条目 / 结论 / SHA` 追加在下方。

（core 线回填区）
