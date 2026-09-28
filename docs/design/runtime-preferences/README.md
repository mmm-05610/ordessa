# 运行偏好域（runtime-preferences）设计草稿

状态：**裁定完成（2026-09-28 用户确认 §4 全部四条；实施包见 `specs/015-runtime-preferences-memory/`）**。数据来源：`docs/design/harness-configuration/harnesses.md`（2026-09-27 官网/固定源码盘点，证据等级=文档级，未实测）、mem0 官方仓库（2026-09-28 逐仓库核实，见 §3）。实施前仍须逐键完成 sources-and-gaps 的完成标准（版本条件/作用域/合并规则/两隔离反例/失败语义）。

## 1. 覆盖什么（四组参数）

| 组 | 典型键（八家盘点摘录） | Profile 存什么 | 不混入什么 |
| --- | --- | --- | --- |
| 压缩/上下文 | Claude autoCompact、Pi compaction/branchSummary、Hermes compression 策略+auxiliary 模型、OpenCode compaction/tool_output、dsh compaction-basic/tool-result-pruner/spill、Qwen autoCompact/fileFiltering、Kilo compaction、Codex compaction/tool-output budgets | 阈值策略、摘要模型引用、预算 | 压缩产物/会话全文/snapshot（运行状态） |
| 记忆策略 | Codex memory 辅助模型、Claude autoMemory、Hermes persistent memory+memory provider、OpenCode memory loader | 开关、后端引用、预算 | 自动生成的记忆正文；Qwen 的"memory"=静态指令陷阱 |
| shell/执行环境 | Hermes terminal backend/SSH/容器/持久 shell、dsh shell-env/persistent bash、Pi/Claude/Codex shell 与 env 策略 | 允许的执行参数、环境引用 | 全量复制 HOME/PATH；部署凭据 |
| 重试/传输 | Pi HTTP/WS transport/proxy、dsh llm retry、Codex retry/stream timeout | 策略参数 | 请求级 provider 参数（见 §4 边界裁定） |

机制定位：**F（运行偏好）× A（类型化参数）**——不是内容资源（不走 slot/文件投影），走 model-provider 域已打通的 C2 `harness.configuration-adapters` 类型化参数路线。

## 2. 关键事实

1. **压缩：八家全有原生配置** → 纯投影即可，无补缺压力。
2. **记忆：只有四家有原生**（Codex/Claude/Hermes/OpenCode）；其余四家的"记忆"要么是静态指令陷阱（Qwen）要么无。**补缺=要不要自建记忆能力**是本域最大裁定项。
3. **shell/重试：约半数家有**，且多与权限/隔离纠缠（Codex shell env 在权限行、Claude 环境/运维含管理员项）——管理员约束项不可作为普通预设写。
4. `harnesses.toml` 的 slots 词汇（provider/permission/instruction/mcp/skill/hooks）**不含这四组**——印证它们不是内容资源，走 C2 参数而非新 slot。

## 3. 复用研究（内外两库，粒度到"复用什么、怎么接"）

### 内部复用（已在本仓，直接可仿）

| 复用对象 | 具体复用点 | 怎么复用 |
| --- | --- | --- |
| `plugins/assets/model-provider/adapters/`（pi/codex/claude 的 assess/compile/verify + `common.py` 字节稳定渲染 + `registration_manifest()`） | 本域四组参数的**品牌 adapter 骨架**：同样三方法、同样 golden 转录 conformance（`adapters/tests/test_adapters_conformance.py:80-103` 的门形：重叠注册拒、版本区间不相交拒） | 新域建 `plugins/assets/runtime-preferences/adapters/{brand}.py`，逐家把四组参数编译进 C2 typed intents；注册进同一 `CONFIGURATION_POINT`（不同 facet_id，不与 model-provider 撞） |
| profile facet 形状（prompts 域三 item 模式） | facet item 的"默认值+整项覆盖"语义、`ProfileContributions.forScope().addEditor()` 编辑组件注册 | 本域 facet `assets.runtime-preferences`：四组各一 item（compaction/memory/shell/retry），值=参数对象+后端/模型引用 |
| C4 应用链（ConfigurationApplicationService + permit） | 应用/回读/重启计划 | 四组里 compaction/memory 多为"下次会话生效或显式 reload"，shell/传输多为"重启进程"——生效方式逐键按 sources-and-gaps R3 核实后填，不猜热更 |

### 外部项目（mem0 已裁定启用，独立立项；compaction 参考仅对照）

**上游事实修正（2026-09-28 逐仓库核实）**：OpenMemory（`mem0ai/openmemory`）已转型为"跨 harness 迁移编码会话的 CLI/TUI"（TypeScript，MIT），不再提供记忆服务；原记忆 MCP server 仓库 `mem0ai/mem0-mcp` 已归档（Public archive）。可落地的记忆引擎是 **mem0 本体自托管 server**。

| 项目 | 事实（来源：mem0ai/mem0 官方仓库 main，2026-09-28） | 复用点与接法 | 边界 |
| --- | --- | --- | --- |
| **mem0 自托管 server**（`mem0ai/mem0` `server/`，Apache-2.0） | 官方部署仅 docker compose 一条路：FastAPI server（:8888）+ `pgvector/pg17` Postgres（:8432，记忆/认证/向量一体，无替代后端）+ Next.js dashboard（:3000）。REST + OpenAPI（`/docs`），程序访问 `X-API-Key`。LLM 仅 bundled openai/anthropic/gemini（embedder 仅 openai/gemini），server 层无自定义 base_url 官方入口（`POST /configure` 收任意 Dict 是否生效未实测）；默认开匿名遥测（`MEM0_TELEMETRY`） | **记忆补缺独立立项为 `plugins/assets/memory` 叶子插件**（用户选定引擎）：置备 compose 子栈（不起 dashboard，产品内经 REST 管理）；.env 由产品生成（随机密钥、遥测关、端口走产品分配、数据目录在产品 data-root 仓外）；抽取 LLM 从 model-provider 解析 bundled 同名 provider；注入走 instruction 槽命名 facet `ordessa.memory` | 云平台不用（数据出境）；记忆正文不进 Profile；抽取与 embedding 均真实模型调用**须单独授权**（默认关）；Docker 为系统前置，缺失=诚实 unsupported；`POST /configure` 自定义端点仅作 E2 受控实测项，结果如实登记 |
| OpenCode / dsh 的 compaction 实现（参考点，非代码复用） | OpenCode autoCompact 阈值语义；dsh 分类型裁剪（tool-result-pruner）+spill | 仅作品牌 adapter 编译语义的**对照参考**（各家原生键语义以官方文档/源码为准） | 不搬代码；不把一家语义套到另一家 |

## 4. 裁定结果（2026-09-28 用户确认）

1. **本域=纯配置域**：只做四组参数的 facet+adapter 投影，八家逐格判可用/不支持/未知。~~记忆补缺后续另行立项~~ → 同日改判**立即排期**，独立为本批 P-B（见下）。
2. **一个域一个 facet 四 item**（compaction/memory/shell/retry）；实施中若 adapter 语义冲突再拆。
3. **与 model-provider 边界**：请求级参数（reasoning effort、service tier、请求 retry/stream timeout）归 model-provider 域；本域只收会话/运行级策略。
4. **记忆补缺**：独立叶子插件 `plugins/assets/memory`（将来分支 `codex/plugin-memory`），引擎 **mem0 自托管 server**（用户选定；OpenMemory 因上游转型不可用）；产品内标注"记忆引擎 mem0（Apache-2.0）· 本地自托管"；方案包 `specs/015-runtime-preferences-memory/`（P-A=本域、P-B=memory）。
