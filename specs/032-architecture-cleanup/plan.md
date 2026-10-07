# 迁移计划

## 0. 执行规则

开始条件是 `baseline.md` 的整合门通过。一个执行者串行推进；每阶段显式列出写入、删除、迁移和未完成项，只提交本阶段文件。禁止整树 stash/reset、自动 push、改用户服务、调用真实模型、删除真实数据。

“搬入核心”必须先辨别是否已有同一能力。已有就迁移消费者、删除重复实现，不再抄一套。缺少的是必要公共机制才移入核心；品牌知识留叶子。测试随职责迁移并保留原断言；过时业务模型的测试可以改写为新语义测试，但必须说明替代断言，不能删除失败项换绿。

## 1. 固定起点与退役清单

建立每文件/模块映射：`旧路径 → 职责 → 新路径或删除 → 消费者 → 数据影响 → 替代测试`。覆盖源码、注册、装配、构建、锁文件、入口脚本。发现新的残留先分流入清单，不创建兜底兼容包。

需明确退出的 import/发行包：`ordessa_agent`、`ordessa_profile`、根 `ordessa_harness`。同时检查 `plugins/runtime-compat` 和 `plugins/server-compat` 的实际内容：通用机制移回相应公共包，产品绑定移回产品，旧链转换器删除。不得只因名字叫 compat 就丢掉仍必需的治理规则；也不得改名继续保留旧权威。详细分流见 [退役接收表](retirement-map.md)，这是执行清单而非可选建议。

验收：整合提交固定；脏树保护记录完成；每个退役入口有清单项和目标。

## 2. Agent/Profile 单一权威

| 旧模块 | 目标处理 |
| --- | --- |
| `plugins/agent/backend/*owners*`、配置存储/观察 | 对照 `pacthold.agents` 已有配置权威，迁入缺失的通用规则，删除重复 owner |
| capture、submission journal/service | 通用命令/输入记录及拒绝规则进入 agents 相应模块；品牌输入/协议解码留品牌插件 |
| `plugins/profile` 清单、版本、引用解析、策略 | 对照 core profiles/configuration，保留一个实现与一个写入入口 |
| Profile SQLite 与 application journal | 核心定义领域端口；SQLite 实现按现有持久化边界接线，不保留 Profile 插件独立权威 |
| Profile facets/materialization | 公共贡献契约归核心；具体模型、Skill/MCP/提示词字段及转换归贡献插件/品牌插件 |
| `AgentDomainPlugin`、`ProfileServerPlugin` | 产品改用核心公开绑定，不提供旧类名的转发壳 |

整理 agents 子目录，公共导出统一更新。保持“Profile 配置输入”和“生命周期操作”分离；不能将未完成组装链伪装为完整节点。

验收：核心 import 不含插件/应用/产品；重复 Profile 存储/Agent owner 不可达；修改命令只到一个权威；缺端口时明确拒绝，禁止本地缓存充当权威。

## 3. Harness 拆成品牌组

1. Codex、Pi、Claude Code 独立 provider 作为各自唯一入口。旧品牌目录与新品牌包逐项合并，不能保留“两套 provider 任选其一”。
2. opencode/hermes/kilo/dsh/gemini_cli/copilot/goose/kimi/qoder/qwen/vibe 等已有实现归对应独立品牌目录。保留已有知识，不为完成清理新写生产适配。未完成品牌显式未装配或拒绝，不调用原总包。
3. 根 `registry/resources/application/configuration/materialization` 中的通用 Agent 规则归核心；品牌规则归品牌；仅产品绑定归产品。没有消费者的旧模型删除。
4. 根 `server_acp` 拆清：中立通道实现归 harness-transport 或现有连接契约；品牌协议/会话操作归品牌；上层只能使用公开入口，不拼桥二进制路径。
5. Go ACP 桥按 retirement-map.md 的品牌/协议分流拆解。现有 `internal/acp/server.go` 直接依赖 Codex，Pi 又复用它，不能整块丢到中性 transport。拆出共享 codec/传输和品牌包装；无法隔离的旧桥能力先显式不装配，不允许 Pi 导入 Codex 插件。维护唯一资产来源、构建清单及原断言，不提交二进制。
6. `plugins/harness/api` 的核心接入契约迁入 Pacthold 公共入口；品牌契约放品牌，不保留新的 Harness API 超级插件。`model_compilation.py` 的 Pi retry 形状不能进入核心：中性 TargetHandle/AdapterContext 对照核心、Provider/Model 字段归资源 API、Pi 原生字段归 Pi。`records` 的通用节点/操作/配置记录归核心端口及持久化；原生会话记录归品牌。
7. runtime/packaging 清单逐品牌拆出。删除根 pyproject、根 src、根 entrypoints 和超级包依赖。

验收：每品牌可隔离安装/导入且无根超级包；品牌间无 import；卸掉其中一家不会影响核心与其他品牌的注册；产品只明确选取品牌入口。

## 4. Assets 与前端消费者

资源插件移至 `plugins/assets/`，保留包名、extension id、存储标识；其内部管理自己的资源，通过公共贡献端口参与组装。不要将外部 Sandbox 和 Harness 内置 Sandbox 配置混为同一资源语义。

Agent/Profile 的公共类型、wire 投影移至 frontend/contracts 的领域空间；现有 sessions/connections 视图迁至 agent-ui，Profile 编辑与 chat 选择器迁至 profile-ui。控件发命令并读核心事实，不能生成本地运行配置 owner。旧本地 owner/兼容 glue 如是重复权威应删除，不移动到 UI 新名字下继续运行。

更新 npm workspace、产品启用清单、锁文件、导入和测试发现路径。保持真实用户 extension id，不为目录改名制造数据迁移。`extension-host` 等现有转发壳不能照搬保留：真实实现搬到目标独立叶子，消费者直接依赖该叶子的公开导出，删除原嵌套实现路径及 alias 转发，避免 package 名正确、实际代码还绕旧层。

验收：所有 UI 依赖新公开契约；选择器、状态投影、CLI 读到同一核心事实；未接线状态明确不可用；不增加第二个 service locator 或配置仓库。

## 5. 产品装配与全面退役

Server 产品删除 `ordessa-agent`、`ordessa-profile`、`ordessa-harness` 依赖和旧注册。Agent Tools 只保留服务客户端与 Skill，清查 pyproject、部署脚本中暗藏的本地品牌运行器/后端；新增节点准备能力不能塞进 CLI。

决策模块按 2026-10-07 用户修订整包迁入 Pacthold（`pacthold.decision`，与 agents 同级）：不拆分 Jev 提供者、现有决策流程或证据模块；现有 Ordessa 读取适配改用核心内部公开入口，仍然只读，不新增 Agent/Profile 状态权威、执行器或 apply 路径；统一 Python 命名空间为 `pacthold.decision`，删除 `packages/backend/decision`、`ordessa-decision` 发行包及旧入口，不保留转发壳或兼容链；pydantic-graph 固定版本由 Pacthold 清单声明，typesafe-sdk 保持 Jev 可选依赖，Pacthold 默认导入不加载决策框架或 Jev SDK；原独立发行测试改为 Pacthold 发行内的 Decision 模块隔离测试，保留无 Jev 依赖时的通用离线流程、纯读、预算、取消及拒绝路径保障，不删断言换绿。现有第三方安装管理等公共模块按实际基线保留，不用该轮重做它们。

删除旧包全部活跃源码、package manifests、注册、转发、fallback、editable-install 路径和启动脚本。历史文档可保留，但当前文档必须以目标为准并给出可验证的依赖。离线数据迁移脚本放 `scripts/migrations/`，不由运行时自动加载；真实数据迁移另获授权。

验收：干净环境按新清单可构建/装配；不可用能力有清楚错误；不需要安装任何退役包。代码中不留新旧分支切换开关。

## 6. 最终验证与交付

验证在整合实施树隔离环境串行执行，记录命令、退出码、模块 __file__/版本、测试结果、失败归因。先检查测试发现数量和来源，再跑核心、持久化、品牌离线适配、UI 契约、产品清单与 CLI 套件。旧环境 editable 路径可能仍指向别树，必须先排除。

必须新增的结构守卫及反例：

| 守卫 | 反例必须失败 |
| --- | --- |
| 核心不依赖品牌/宿主 | 向核心加入一个品牌或 Server import |
| Harness 根非包 | 恢复根 pyproject 或 src/ordessa_harness |
| 产品无旧依赖/注册 | 清单加回旧 Profile/Agent/Harness 包或旧工厂 |
| 无隐藏旧执行链 | 新入口缺能力时尝试委托旧接口 |
| 单一配置权威 | 控件新建可独立写的“已应用配置”副本 |
| 发现新路径测试 | 测试收集仍来自删除目录或其他树 |
| 品牌独立 | 删除一家可选品牌后其他品牌无法注册 |

守卫不能只按字面搜索；结合 import 图、清单解析和实际隔离加载验证。历史引用/外部协议名有显式例外白名单，禁止 blanket ignore。

最终交付：固定提交；旧→新映射；实际目标目录；删除与退役证据；数据未改说明；离线测试结果；功能缺口表。`STRUCTURE_CLEAN` 与 `PRODUCT_READY` 分开，此轮只判前者。任何旧权威/旧兜底仍存活，不得报告结构完成。
