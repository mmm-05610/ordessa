# 现状盘点（只读）

## 证据口径与快照

M = 主树 `/home/maoqh/projects/ordessa`，HEAD `b4bf7cd90951d0fa9bcf3a3de2e66b7db6a62aa0`。
P = 产品树 `worktree/021-ordessa-product-closeout`，HEAD `7951bf06a258d2dc41402556eb61319b8bab5cbe`，包含未提交改动。
开始状态及纳入盘点文件的 SHA256 见 `evidence/source-snapshot.json`。P 的行号描述的是该文件摘要对应工作内容，不能仅用 HEAD 复现。

以下「源码路径」表示存在生产装配/调用链，**不是本轮运行证明**；「测试」表示已读取测试或文档指针，**本轮未运行产品测试**；「历史报告」只引用原报告结论。
本轮没有访问真实数据根、凭证、资产或服务；不把声明的支持等同可运行。

## 按职责和消费者列账

所有路径除 P 行明确标注外均为 M，行号为开始快照。

| 机制 | 源码证据（路径:行） | 实际消费者与粒度 | 判定 |
| --- | --- | --- | --- |
| 新 Core 运行权威 | `packages/pacthold/src/pacthold/core/runtime.py:54,128,174,194,211` | `apps/server/src/ordessa_server/core_binding.py:125,157,217` 由 public facade 消费；注册/资源获取/启动/停止/核对 | 存在可复用的中性事实模型，不能直接当完整开放环境 |
| 新 Core 持久化 | `core/store.py:32,56`、`core/dispatch.py:92,111,500,920`（同上 pacthold 前缀） | 每 Runtime 独立 Store；core_execution/core_operation；submit 总是有持久活动路径 | 值得复用意图、幂等和 unknown；需要轻量查询/对象/代际语义；Store 跨线程事务序列化须另验 |
| Core 注册表 | `core/registration.py:108,147,223,251` | 批次注册 contracts/resource_providers/execution_providers | 原子进程内可见性可复用；插件安装、实例、能力并不等价于 provider |
| public 面 | `packages/pacthold/src/pacthold/public.py:1` | Server 只导入 public；文档明确不 re-export work_core 以免拉入领域依赖 | 保留单一公共面，改模型必须显式升级协议 |
| 旧 work_core | `packages/pacthold/src/pacthold/work_core/services.py:78,98,123`、`repository.py:126,139`、`db.py:151,165` | sidecar_backend:201–203 仍无参数构造 CoreRepository/WorkService/ExecutionService，dispatch 调旧 ExtensionRegistry；Repository 已支持注入连接或 callable | 并非死代码；复用已有实例注入，不能依据旧文档声称类不支持 Store；生产无参路径仍全局 |
| 旧资源/执行注册 | `work_core/registry.py:134,214,239,247` | Harness GenericExecutionProvider 导入旧 receipt/ref，runtime-compat bootstrap 注入共享领域合同 | 与新 Core provider 注册有覆盖；adapter 要迁移，不能通过反向 re-export 维持双权威 |
| 旧中性执行跟踪 | `packages/pacthold/src/pacthold/execution/lifecycle.py:33,58,77`、`contracts.py:22,32,50` | NeutralRunTracker 内存 run/cancel_receipt，调用 TurnExecutionPort | cancel 与 delivery/evidence 分轴有价值；注释称投影，不应成为第二 durable ledger |
| 旧 extensions | `packages/pacthold/src/pacthold/extensions/api.py:36,94,107`、`catalog.py:101,165,249` | descriptor/context/registration，selector/finalization/host-control；Harness plugin facade:6–15 | 核心通用加载与领域 SDK 混在同包；概念复用，业务 contribution 移 owner，避免一刀删除 |
| Server 插件宿主 | `apps/server/src/ordessa_server/plugin_host/host.py:315,456,538,691,720,874,897,909` | methods/stream/http 注册，依赖拓扑，整轮贡献 stage/commit/rollback，hold+退役锁 | 最成熟的通用激活机制之一；将其生命周期收敛到中性环境，Server 仅注册 transport 扩展点 |
| Server hold 注册 | `apps/server/src/ordessa_server/plugin_host/contribution_points.py:183,190` | use_contribution 取得 hold，owner_busy 按 hold 判断；host.py:835,855 | 短期贡献借用与资源 Lease 是不同粒度；统一依赖账而非合并成同一个 Lease 状态机 |
| CoreBinding 桥 | `apps/server/src/ordessa_server/core_binding.py:27,99,125,180,217` | bootstrap 将 pacthold.contributions 的 handler 绑定到 CoreBinding | 是真实接缝；当前有两级 batch/退役，目标由同一环境事务发布，网络 host 不能拥有第二 runtime |
| bootstrap/旧库桥 | `apps/server/src/ordessa_server/bootstrap/runtime.py:113,143,295,298,627,631,669,701` | 新 core.sqlite 独立，LegacyCoreBinding 配置旧全局 db；start/stop 调两链 | 两文件不等于两权威，但全局旧 db 仍有隔离风险；不提前合库 |
| Server API | `packages/server-plugin-api/src/server_plugin_api/contract.py:24,59,97,125` | descriptor requires、严格方法参数、stream resolver、HTTP auth 声明 | wire/HTTP 类型保留在网络边界，中性扩展合同分离；原生 payload 不能经严格字段白名单剥落 |
| Wire/transport | `apps/server/src/ordessa_server/wire/handlers.py:180,237`、`wire/discovery.py:55,153`、`acp_admission.py:305,327` | hello facets、错误族聚合、ACP submission admission 与路由结果联动 | 运输/鉴权可保留；acp_admission 的品牌协议知识归适配插件，授权端口仍可中性承载 |
| 产品装配 | `products/server/src/ordessa_server_product/composition.py:99,126,173,215,223` | 显式选兼容、workspace、Harness ACP，注册 Harness 扩展点，permissions 未注入时 ready=False | 空环境必须另一显式空清单；不从默认产品反推内核必需 Profile/Harness |
| server-compat 业务 | `plugins/server-compat/src/ordessa_server_compat/plugin.py:155,164,169,181,225,339,348,412` | Profile/Session/Skills/MCP records/services，native profile bootstrap | 业务保留到 owner；移除 Harness 不应等于移除所有资源；当前融合装配需要拆接缝 |
| Harness 旧 provider | `plugins/harness/src/ordessa_harness/generic/execution_provider.py:3,8,13,16`、`plugin.py:6,10` | start 的 runtime composition、Profile 解析、native handle 属 Harness | 核心不能重建 adapter 的推理/工具/workflow；保持原生入口，旧 run handler 仅成投影/适配 |
| Harness 原生通道 | `plugins/harness/src/ordessa_harness/server_acp/registry.py:59,214,234,290`、`runs.py:26,55,69`、`plugin.py:154,189,323,353` | (harness,workspace) 通道共享，一 channel 对应旧 Session+Turn；launch 后写记录；release 接证明 | 通道对象、创建调用、会话/轮次目前混用 execution 名称；需拆关联，保留原生 session 权威 |
| 原生入口与进程证据 | `plugins/harness/src/ordessa_harness/server_acp/access_entry.py:61,113` | 启动受 Harness 管理，发送 connect；协议适配不应上移 Core | 真实进程完整性不能由内核抽象自动保证，插件必须声明边界和证据 |
| P 原生历史/配置变更 | `plugins/harness/src/ordessa_harness/server_acp/history.py:13,17,53`；P `registry.py` 的 native operation state 路径 | P 未提交新增历史、配置核对，Profile 集成与 connector 有变化 | 不能基于 M 单独设计迁移；必须先钉住 P 合并或排除基线 |
| 现场 Profile 插件 | `plugins/profile/src/ordessa_profile/plugin.py:16,21,64,79,91,114,127`；`storage.py:172,218`；`application_journal.py:33,48,128` | 当前树实际存在旧扩展入口及 ProfileResourceProvider，lazy profile-store.sqlite，facet与配置操作/receipt journal | 与AGENTS/architecture关于Profile只在仓外的历史描述不一致；仅登记现场，不擅自改归属。不能把领域配置journal与环境投递账合成一个主状态 |
| Harness Profile 存储链 | `plugins/harness/src/ordessa_harness/generic/factory.py:13,22,26`、`profile_manager.py:1` | Harness自身profile-store、selector与manager；server-compat另有ProfileRecords；Profile插件另私有store | 三种来源不等价，必须显式context/source ref，不能以同名Profile自动替换 |
| 资源安装不等于原生装载 | `plugins/server-compat/src/ordessa_server_compat/assets/skills.py:110,119,168`、`assets/mcp.py:128,137,165` | 资产revision install/read/verify，与agent原生加载/运行服务不同 | 技能/MCP生命周期分资源对象与参与者实例；不因catalog存在说已完整接入 |
| 默认产品治理接缝 | `products/server/src/ordessa_server_product/composition.py:146,152,154,156,219` | 实际装配model-provider、permissions、sandbox插件，permissions.authorizer@1供ACP admission | 源码装配存在不等于唯一审批权威闭环验证；目标沿用policy port，不由环境自建审批业务 |

## 重叠状态、身份和存储

| 事实/身份 | 现有位置 | 必要区分 | 应收敛的重复 |
| --- | --- | --- | --- |
| 安装/插件激活 | extensions descriptor/catalog；Server active/order；Core active_owners | 安装资产≠激活贡献≠运行实例 | 两宿主的插件选择、依赖与退役不能继续平行 |
| 请求/执行 | 新 request_key/execution_id/operation_key；旧 exec/dispatch；server_turns；NeutralRunTracker | 调用、原生会话、通道对象、业务 Turn 不同 | 同一副作用不能由多个 ledger 独立裁定终态/重发 |
| 对象与使用 | Core Lease own/borrowed；Server contribution hold；ACP _by_pair/_by_id 与 subscribers | 所有权、使用许可、订阅、native process identity 不同 | 退役应查询同一依赖事实，而非一处 idle 另一处 active |
| 注册贡献 | CoreRegistry；ExtensionRegistry；Server contribution_points；HarnessContributionRegistry | 不同领域合同与 transport 扩展点可存在不同索引 | 可见性发布与 owner 卸载必须单一事务/代际，索引不能独立激活 |
| 历史/存储 | state/core.sqlite；legacy database schema；work_core/db 全局连接；插件资产目录；P 原生历史 | 独立领域库/文件合理，原生 history 可插件所有 | 不能同副作用双写两套主状态；不必合物理库才能统一权威 |

特别记录：`core/runtime.py:88–117` 读取持久账异常时使用内存兜底；这可能在数据不可读时报告空 unresolved。目标应拒绝/unknown，不继承该兜底作为安全保证。`core/store.py:41–64` 允许跨线程连接，`core/dispatch.py:325–327` 已有 dispatcher 局部事务锁；未来多个写者共用 Store 时需统一锁域，不把「Store 本身没有锁」误报当前 dispatcher 完全没有并发保护。这里是源码风险，不宣称已受控复现产品缺陷。

## 9 月 27 日 core 的形成原因与兼容保留

`specs/010-platform-core/spec.md:24–45,50–64` 的目标是资源获取/回收、意图先行、未知保留、裸宿主和领域外移；`plan.md:32,44,48` 明确 runtime-compat 是有限承接、旧 SQL 保字节，注册事务不承诺外部原子性。
`public.py` 文档解释新 core 不直接使用旧 work_core，以免 import 注册链拉入 resource_contracts；CoreStore 给 C1 实例级连接，旧 CoreRepository 的无参生产消费者仍调用全局 db，而注入式接口已经存在。兼容保留服务于真实消费者和旧数据，不是只因目录没整理。`docs/known-issues.md` 关于「CoreRepository takes no store」的旧记录已与源码不一致，以现场源码为准。
目标不是推翻这些保证，而是在其上补完整参与者、独立对象、原生交互和可移除环境；新 Core 本身也不能未经攻击直接冻结。

## 测试与历史报告的分级

- 已存在的受控测试指针（本轮未跑）：`packages/pacthold/tests/platform/test_us1_instance_isolation.py`、`test_public_contract.py`；`apps/server/tests/platform/test_platform_core_instance_124.py`（两实例/文件拓扑反例）；`packages/server-plugin-api/tests/test_contribution_transaction.py`；Harness native operation/history tests（P 工作内容）。
- 历史报告：P `specs/021-nightly-product-closeout/final-report.md` 明确 PARTIAL；P `acceptance-20261003.md` 描述 native ownership refusal 路径补查与受控测试、后续真实聊天，属于他轮报告，**本任务不复跑也不继承成当前通过**。
- P 报告的 Skills/MCP 缺口尤其重要：资产 records 服务存在，不证明原生加载/默认产品装配闭环；本设计分别列安装、实例化与可达性要求。
- `docs/known-issues.md` 是冻结/历史问题登记，不覆盖最新工作内容；计数不当当前绿色基线。未来实施前重新逐 ID/原因比较。
- `plugins/profile/README.md` 与 pyproject 有现场入口/依赖声明，但 `plugin.py:21` 还导入 runtime-compat；依赖闭包需受控隔离安装验证，不能只据pyproject声称独立已通过。补盘点文件摘要见 `evidence/supplemental-snapshot.json`。

## 后续实施必须补的证据

1. 选定 M/P 的明确集成快照及脏文件内容；当前只能给双树迁移映射。
2. 对每个 facade/wire/legacy consumer 做实际逐调用迁移清单和全套依赖守卫。
3. 受控真实 Store 并发/崩溃测试，以及隔离安装/空清单验证；离线规范检查不能代替这些。
4. 真实原生交互可达性/卸载/服务/模型验证属于后续另授权范围。
