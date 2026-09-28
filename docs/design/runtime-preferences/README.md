# 运行偏好域（runtime-preferences）设计草稿

状态：**Draft（待用户审，2026-09-28）**。数据来源：`docs/design/harness-configuration/harnesses.md`（2026-09-27 官网/固定源码盘点，证据等级=文档级，未实测）、mem0 官方仓库与论文（2026-09-28 检索）。本稿只定边界、切法与复用点，实施前仍须逐键完成 sources-and-gaps 的完成标准（版本条件/作用域/合并规则/两隔离反例/失败语义）。

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

### 外部项目（已调研，v1 不依赖；"记忆补缺"裁定若通过则启用）

| 项目 | 事实 | 复用点与接法 | 边界 |
| --- | --- | --- | --- |
| **mem0**（`mem0ai/mem0`，Apache-2.0，约 60k stars） | 两阶段 extraction+update 管线（LLM 抽取事实→去重/合并/冲突解决）；向量存储默认、可选 graph；按 user/agent/session 作用域；Python `mem0ai` / TS `mem0ai` SDK；另有自托管 **OpenMemory**（MCP server） | 若做记忆补缺：**优先经 OpenMemory 以 MCP 服务绑定接入**（服务绑定机制，走 mcp 域的受管连接与双门授权），不嵌入进程；四家无原生记忆的品牌以 MCP memory server 形式获得能力，会话级开关与预算由本域 facet 控制 | 云平台不用（数据出境）；记忆正文不进 Profile（classification 红线）；LLM 抽取消耗真实模型调用——**须单独授权**，未授权前该格 unsupported |
| OpenCode / dsh 的 compaction 实现（参考点，非代码复用） | OpenCode autoCompact 阈值语义；dsh 分类型裁剪（tool-result-pruner）+spill | 仅作品牌 adapter 编译语义的**对照参考**（各家原生键语义以官方文档/源码为准） | 不搬代码；不把一家语义套到另一家 |

## 4. 待用户裁定（讨论点）

1. **v1 范围：纯配置域（推荐）**——只做四组参数的 facet+adapter 投影，八家逐格判可用/不支持/未知；记忆补缺（mem0/OpenMemory）作为后续"服务绑定"能力另行立项。理由：八家压缩全原生、补缺涉及真实模型调用授权与数据边界，混进来会拖死纯配置部分。
2. **一个域还是两个**：推荐**一个域**（`plugins/assets/runtime-preferences`）+ 单 facet 四 item；"上下文与记忆"和"执行环境"若实施中发现 adapter 语义冲突再拆（拆的代价小：四组 item 本就独立）。
3. **与 model-provider 的边界**：请求级参数（reasoning effort、service tier、provider 请求 retry/stream timeout——Codex"推理与请求"行整行）已裁归 model-provider 域；本域只收**会话/运行级**策略（compaction/memory/shell/传输层 retry）。确认这条划法。
4. **记忆补缺的立项时机**：若你现在就想排，我按 OpenMemory 接入做独立设计（涉及 MCP 授权链与模型调用授权两道门）；不排则登记为后续。
