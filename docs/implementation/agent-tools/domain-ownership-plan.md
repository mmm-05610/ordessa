# 后续职责与目录划分（阶段020之后）

用户要求先完成当前阶段，再按领域划分，不能只分核心/插件。本表基于现存目录，不移动源码、不新建第二核心、不将有目录等同能力已接线。根目录为本实施树；跨领域通过公开DTO/port交接，各文件只有一名作者。具体下一工单需另列文件白名单及反例，下面不是任意跨目录写权限。

| 领域 | 实际目录 | 负责与边界 |
| --- | --- | --- |
| 平台身份、授权与准入 | packages/backend/environment-api/；packages/backend/pacthold/src/pacthold/core/；pacthold/environment.py | 身份/Policy/Operation-Store端口、唯一Environment/Registry/activation。发布公共合同，不知道Harness品牌，不推进Agent业务。environment.py由此领域独占，其他领域请求它补公开接缝。 |
| Agent控制与装配 | packages/backend/pacthold/src/pacthold/agents/ | Profile、配置选择与依赖决策、Node生命周期、原Operation/Step/Usage、授权调用/查询/停止释放协调；包括material_operations协调。不得实现领域codec、持材料正文或第二actual配置账。优先补精确效果intent与原分阶段装配。 |
| 持久化与崩溃恢复 | packages/backend/persistence-sqlite/ | 原Store事务、CAS、claim唯一性、phase封存与恢复完整性；不决定业务授权，不新建另一执行账，不修用户数据库。只临时数据库迁移验证。 |
| Skill资源与配置 | plugins/skills/src/ordessa_skills/ | Skill目录/版本/配置schema、引用覆盖、领域编译与验证、同owner材料受权读取/lease。与产品配套使用说明Skill区分；不负责Agent流程。 |
| Prompt资源与配置 | plugins/prompts/src/ordessa_prompts/ | Prompt版本/内容与配置解释、精确引用覆盖和材料交接；不将Prompt语义塞入Harness或核心。 |
| MCP定义与连接 | plugins/mcp/backend/ | server定义/连接配置、managed/borrowed归属、引用与连接寿命；副作用必须具名授权。Agent不偷偷启MCP进程或复制连接账。MCP作为Agent Tools入口仍属后续阶段。 |
| 模型供应配置 | plugins/model-provider/profile-contribution/；packages/backend/platform-services/ | 前者负责模型供应领域配置贡献；后者平台秘密设施由平台owner维护，两者单独文件写权。秘密只最终受权解析，客户端与核心不维护第二模型真值。不存在的外部provider能力保持缺席，不写占位实现。 |
| Harness原生控制与证据 | plugins/harness/api/；plugins/harness/codex/；plugins/harness/pi/；plugins/harness/claude-code/；plugins/harness/src/；plugins/harness/runtime/；plugins/harness/adapters/；packages/backend/harness-transport/ | 公共原生控制端口、品牌驱动/codec、实际配置owner、输入/会话/恢复证据。核心决定调用范围与时机；驱动只执行受权动作并重核目标，不换清单/推进整个Agent流程。共享API与transport各单一作者，品牌可分文件并行。 |
| Server组合与公开网络面 | apps/server/src/ordessa_server/；products/server/src/ordessa_server_product/；products/agent-tools/deployment/ | apps/server提供通用host/wire；products/server组合唯一Environment/原Store/固定issuer、secret与领域owner，发布薄wire绑定。deployment只产品可选现Server组合，不复制后端/daemon；CLI不通过插件注册来使用。共享装配文件root协调串行写。 |
| 独立CLI、配套Skill与发行 | products/agent-tools/src/ordessa_agent_tools/；products/agent-tools/skills/；products/agent-tools/packaging/ | 公共API客户端、init发现/诊断、Profile/Node/任务结果命令、三Skill说明、安装包。Skill不是CLI前提，客户端不导入Server/Harness私有模块，不代签权限。 |
| 跨领域验收 | products/agent-tools/tests/；products/agent-tools/acceptance/；products/server/tests/；docs/implementation/agent-tools/evidence/ | 独立正反例、隔离安装使用与真实服务证据。领域本包tests归各owner；跨域测试作者独占，runner由root串行。分单元/契约/进程/模型证据，缺资源NOT_RUN/PARTIAL，不把资料校验当产品可用。 |

## 分派顺序

先平台合同/Agent控制/持久化接缝，配置贡献与材料交接必须同原Registry。Skill、Prompt、MCP、模型域可分别实现自己的贡献；选择Codex/Pi/Claude验证相同核心路径，不按品牌改核心。之后Server网络组合，再CLI/Skill/隔离发行。先完成精确效果intent和材料消费接缝，不提前让发行或旧路径清理掩盖核心缺口。

核心agents与core两个目录有意同属Pacthold，不另拆核心；配置域与材料owner有意同属原领域模块，不另建中央材料库。公共DTO新增由平台合同领域唯一作者；各消费方不复制schema。此划分可进一步变为有依赖/写权/验收的工单，但本轮只准备，等待用户下一轮工作指示。
