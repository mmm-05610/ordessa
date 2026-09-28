# Research and reuse decisions

## 已核查事实

- 当前 main Harness 仍集中列品牌 native materializer，且存在旧 profile-store 与治理注册词汇；不是这次目标机制已落地。
- `server_acp/plugin.py` 目前依赖 workspace、server-compat，并引用宿主内部 errors/wire helpers；平台 B 正迁中性词汇，实施必须基于其交付更新，不重复改 Server。
- 官方 Claude adapter 的仓内探针已固定 `0.81.2`，测试目标为 session-scoped env/settings 改变导致 A 重建/恢复、B 不受影响。文档明确**不是 Ordessa 全链通过**，本包不能继承为全链验收。
- Model-provider 实现分支存在真实 records/protocol/next_turn 与测试，也有 stub-chat-contract；Skills 实现分支当前为较宽的 `plugins/assets/src/ordessa_assets`。两者不得整包无审查搬入新架构。
- 平台 carrier 承载 opaque payload 是正确的核心边界，但 Harness 点内 payload 必须强校验；不因核心不懂 payload 就让领域也接受任意 JSON。

## 逐模块复用裁定

| 目标 | 固定来源/位置 | 方式 | 必须剥离/补齐 |
| --- | --- | --- | --- |
| ACP 通道管理 | main `cd7d31f3cf`，Harness `server_acp/`、`runtime/access-entry.mjs`、`access-transport.mjs` | 保留改接线 | 去 host internals/旧 Profile 权威，补受限控制及 generation；不重写 relay |
| Claude 运行适配 | main 同上，`packaging/claude/` 与 PROVIDER-SESSION-PROBE.md | 保留锁定依赖和探针 | session-scoped routing 接入真实 Server 路径；禁全局 providers/set；不恢复 Go Claude |
| Codex/Pi 桥与打包 | main 同上，`adapters/acp-adapter/`、`packaging/` | 保留受控上游代码 | 只改必要控制接缝，保持 pin/构建配方；有 nested AGENTS 必先读 |
| 原生供应商转换 | main `native_materialization.py`、各品牌 native.py；业务分支 `9305563719` 的 protocols.py/ports.py/tests/test_brand_adapters.py | 迁移/合并唯一实现 | 协议转换与验证保真；删重复品牌表，不从两边保留同名第二实现 |
| Provider 存储/CRUD | `9305563719`，plugins/model-provider/src/ordessa_model_provider/records.py、catalog.py | 复用现有领域 | 不改成 Harness store，不引入其 stub Chat 依赖 |
| Skill 格式/内容安全 | `752f148b1b`，plugins/assets/src/ordessa_assets/formats/agent_skills、server/store.py、harness_delivery/ | 按符号迁移 | 拆出 Skills 真正业务，不搬统管所有 assets 的总服务；运行写入改 intent |
| Profile 解析/覆盖 | `b77f9f23cb` 的 plugins/profile，按 Profile v2 reuse-map | 消费既有服务并接 application receipt | 不在 Harness 再实现覆盖/CRUD |
| 核心资源与贡献事务 | 平台最终验收 SHA（当前观察值见 README） | 直接依赖公开 API | 禁复制到 Harness，正式 SHA 未定不称已集成 |
| 原生 codec | 现有锁定解析库优先 | 依赖、薄包装 | 不写正则解析 TOML/YAML；确需新依赖先核定版本/许可 |
| 应用 journal/冲突合并/下一次提交协议 | 本包 contracts/data-model | Ordessa 自有薄实现 | 不能冒称上游已有；不引入独立工作流引擎 |

本表未授权新增第三方源码复制。现有 vendored 版权与 NOTICE 保留；新增依赖必须记录 SPDX/版本/来源/许可证，未核定不可复制。第三方项目可用于证据，不为“复用率”搬整套配置系统。

## 上游配置事实与实施支持矩阵

继续使用 [官方调研及缺口表](../harness-configuration/sources-and-gaps.md)，本包不把最新官网覆盖为已安装 runtime 的能力。每格必填：native version、adapter version、文档/源码固定依据、入口、作用域、应用、reset、隔离、确认/恢复、受控测试 ID。

首轮强制 Pi/Codex/Claude 的 provider/model + Skills 六格；其余已有品牌保留已验证启动行为，对本批新增配置能力不做未验证宣告。版本变更若破坏原行为，必须处理而非标“不支持”糊过去。

官方文档已说明的配置机制不等于 ACP 入口可用。Claude 的已有 loopback probe 是可直接复用的受控路线；Pi/Codex 要复用各自 fake 下游、版本 parser 与协议 tests，不能通过调用真实模型验证切换。

## Spec Kit 方法来源

结构参考 GitHub 官方 [spec template](https://github.com/github/spec-kit/blob/main/templates/spec-template.md)、[plan template](https://github.com/github/spec-kit/blob/main/templates/plan-template.md)、[tasks template](https://github.com/github/spec-kit/blob/main/templates/tasks-template.md)。本包使用可独立验收用户故事、可追踪需求、研究决策、契约、任务依赖与清单；文案/领域架构为 Ordessa 本次设计，没有把模板当作技术方案。
