# Ordessa 平台核心收敛方案

状态：DRAFT，待用户审核；不是实施、合并、服务启停或真实模型调用授权。

盘点日期：2026-09-27。依据：本地主工作树 main（盘点 HEAD `cd7d31f3cf`），不把其他 worktree 的实现算作 main 已有能力。本轮只添加设计文档，未运行产品测试。本文采用 Spec Kit 的需求、研究、技术方案、契约、验证分离思路；未安装或运行 Spec Kit，任务拆分须在方案获批后冻结。

## 1. 本轮目标与明确不做的事

目标不是让核心目录永远不变，而是使新增 Harness、配置面、资产类别或业务 UI 通常只需修改所属插件及产品启用清单。核心只因新的通用能力或自身缺陷而修改。

本轮必须完成：

- Pacthold 成为可独立实例化、管理执行与资源生命周期的中性内核。
- Server 成为协议与插件宿主，不保留业务字段、业务分派、业务启动/停机分支。
- Workbench 提升为平台包；Desktop 与扩展宿主继续不拥有布局和业务。
- 各平台包公开 API、生命周期所有者、测试归属与安装边界明确。
- 旧业务适配全部位于插件；核心不得保留业务 shim、转发门面或旧链兜底。

本轮不做：完整 Profile/Provider/Assets 改版、清空全部 server-compat、工作流引擎、Skill 调度策略、自动恢复策略、强制 sandbox、跨进程插件隔离、全量 UI 美化。业务债务可以留在插件，但必须有准确所有者，不能借插件之名回调核心私有实现。

## 2. 当前代码说明了什么

| 现场 | 现状与问题 | 本轮处置 |
| --- | --- | --- |
| Pacthold `extensions/api.py` | 通用 provider 注册混有 ProfileEnvelope、harness_managers、credential_materializers 等专属面 | 通用执行/资源 SDK 留内核；领域契约及管理器移到业务所有者 |
| Pacthold `work_core/db.py` | 模块全局连接与 configure_database；一个实例的配置/关闭会影响同进程其他实例 | 注入实例级 Store，不通过全局开关切数据库 |
| Pacthold `extensions/runtime_composition` | 具体 runtime-host/sandbox/terminal 组合与补偿逻辑 | 提炼通用依赖/租约生命周期；具体三件套组合移插件，不把 sandbox 设为必需品 |
| Server `bootstrap/runtime.py` | 业务门面表、native_profile_id、ACP stop_all 等仍在宿主 | 插件端口通过声明依赖获得；启动/停机只运行通用生命周期协议 |
| Server `wire/handlers.py` | hello 仍懂 harness/nativeExecution；留有模型等业务辅助函数 | 方法、发现字段的语义归插件；宿主只校验与投影注册贡献 |
| Desktop `renderer/app.tsx` | 只是 Shell 包装，现有方向正确 | 保留，不重建 UI 宿主 |
| Desktop renderer / electron/main.ts | 业务测试与 agent DOM 冒烟嵌在应用入口 | 测试迁所属插件/产品；应用只提供通用测试启动接口 |
| desktop-platform contracts | 框架契约与 Agent 等业务契约混装 | 平台契约归平台所有者，业务公共契约随领域插件；禁止重复 Token |
| `plugins/workbench` | 已是通用布局和贡献点实现 | 迁 `packages/workbench`，仍经扩展宿主加载 |

“无业务 import”只是必要条件。验收还必须检查业务字段、专用分支、默认值、打包依赖和测试是否依赖业务存在。

## 3. 整个平台的职责与依赖

```text
apps/desktop                           apps/server
 Electron 启动、安全边界                 HTTP/WS、鉴权、启动/停机
         │                                      │
 desktop-platform                       server-plugin-api + 插件宿主
 loader → extension-host                       │
         │                                  pacthold
 packages/workbench                    执行、资源租约、幂等、证据
 布局/导航/浮层/设置贡献点
         ▲                                      ▲
         └──────── plugins/<业务域> ──────────────┘
                    前端/后端/公共领域契约

products/*：选择平台组件、插件与部署绑定；不是另一个业务协调器
```

图中箭头表示使用关系，不要求所有插件都依赖 Workbench 或 Pacthold。纯后端查询插件无需 ExecutionProvider，纯前端服务插件无需 UI 贡献。

| 包 | 应有职责 | 禁止承担 |
| --- | --- | --- |
| packages/pacthold | Work/Execution、资源契约、执行计划校验、租约、操作幂等、执行证据、状态查询 | HTTP、UI、品牌、Profile、模型、技能格式、具体 sandbox 策略 |
| packages/server-plugin-api | 描述符、服务引用、贡献、插件生命周期、路由声明、宿主类型化错误 | 业务服务实现；依赖 FastAPI 或 Pacthold 实现 |
| apps/server | 宿主实现、鉴权、通用协议封装、插件组合事务、通用持久化/日志入口、Pacthold 接入 | 业务门面表、provider/model 投影规则、ACP 专用收尾 |
| extension-api | Token、插件/作用域/贡献的基本协议 | 布局、Chat、Agent、连接业务 |
| extension-loader | manifest 校验、启用集与模块加载 | 再造依赖图、激活调度和服务容器 |
| extension-host | 沿用 Lumino 的依赖/激活、贡献归属、卸载、唯一 root | 布局、业务状态、后端 Execution 生命周期 |
| native-bridge | 受信窗口校验、manifest 授权的 native transport、IPC 实例与句柄释放 | Harness 品牌、协议业务、模型配置 |
| packages/workbench | 区域、视图、模块导航、标签页、浮层、设置容器及其贡献点 | 会话、项目、Profile 表单的业务规则 |
| apps/desktop | Electron 窗口/生命周期、preload 安全边界、挂载 Host | Chat DOM 操作、插件测试、后端业务流程 |
| products/server、products/desktop | 显式启用清单、配置与版本绑定、产品级集成测试 | 私藏服务逻辑、重做资源编排 |

前后端统一的是设计原则，不是运行时框架。Python Server 不使用 Lumino；前端不移植后端租约数据库；Pacthold 不成为全应用 service locator。

## 4. Pacthold：让执行插件不再管理其他插件

### 4.1 保留既有模型，补足使用机制

保留 Work 与 Execution 的核心意义。一次终结的 Execution 永不恢复；恢复一个外部 Session 时新建 Execution，并记录关联的历史引用。重新连接仍在运行的 Execution 是 reattach，不是恢复终结执行。

补充五个实例级接口（以下名称为设计草案，签名待契约阶段冻结）：

| 接口 | 责任 |
| --- | --- |
| CoreRuntime / CoreStore | 单实例注册表、存储与操作入口，不依赖全局数据库 |
| ResourceContract / ResourceProvider | 注册领域自有资源类型；声明输入、依赖及值/租约语义 |
| ExecutionProvider | 声明所需资源；消费已准备的绑定；启动、观察、停止自身执行 |
| ExecutionPlan | 一次执行的不可变选择与绑定；不是 Workflow DAG |
| Operation / Lease ledger | 记录外部操作意图、幂等键、结果与资源清理证据 |

资源分两类：不可变配置/引用值，以及有获取/释放义务的租约。资源是领域插件定义的类型，不由内核增加 PROFILE、MODEL、CHANNEL 枚举分支。

资源依赖声明允许内核按拓扑顺序获取、逆序释放；依赖图只描述本次运行准备，不允许借此设计分支/循环业务流程。执行 provider 只见声明的绑定，不获得所有 provider 注册表。

### 4.2 一次启动的确定链路

1. 业务 UI 与插件形成选择草稿。领域插件负责选项和约束；这一步不创建 Execution、不 spawn。
2. 执行请求带明确 provider、资源引用/修订和幂等键提交。Pacthold 校验完整性、类型、依赖环、版本和能力缺席。
3. 写入计划与操作意图后，才获取有副作用的资源。每步使用稳定操作键；失败逆序补偿已成功获取的本轮租约。
4. ExecutionProvider 接收已准备绑定并启动自身工作。执行产生的资源可以作为输出登记，不强迫所有资源预先存在。
5. 后端事实确定执行终态；终态不可变。资源释放另行记录，执行成功不等于清理成功。

配置草稿不是核心业务对象；核心只认最终提交的资源契约。以后换一个选择 UI，不需要改 Pacthold。

### 4.3 必须冻结的故障语义

- 获取/启动超时但结果不明：记录 unknown，不自动重新调用，不伪装“失败且无副作用”。仍可能被使用的资源不得释放。
- release 失败：保留释放失败/未确认记录及提供者引用；不能标为 released。
- 外部操作与 SQLite 不可能天然原子。先记意图、传幂等键、再记结果；提供者须声明能否查询/对账，不支持时进入人工处置，不承诺 exactly-once。
- 借用既有资源只释放本次租约，不能销毁外部对象；共享/独占策略由资源契约明确，默认不隐式共享。
- 活跃或结果不明的租约阻止所属 provider 卸载。正常关闭进入 draining；超时如实报告，不以 dispose 成功冒充进程已停止。
- 主异常与清理异常分开保存；继续清理所有可安全清理项，不能用清理错误覆盖主因。
- 进程重启只恢复账本与可验证句柄；不复活已终结 Execution，不自动选择替代 Agent。

ACP ChannelRef 是资源引用，不是因为“能打开通道”就成为 ExecutionProvider。实际运行 provider 可以启动进程并发布 ChannelRef 输出。进程的终止责任只能属于一个运行所有者，通道 transport 的关闭不自动等价于终止进程。

### 4.4 插件作者最终只需要做什么

- 普通服务：声明提供/消费的接口，注册处理器；无需接入执行内核。
- 资源插件：定义自己的资源契约，实现获取、释放和可选对账，声明依赖。
- 执行插件：声明输入资源，实现自身 start/observe/stop；不创建 Workspace、读取 Profile 表、不枚举其他插件。
- UI 插件：注册自身界面和命令，调用业务服务；不直接编排租约。

## 5. Server：一个插件宿主，一条 Pacthold 接缝

Server 管插件的激活与卸载；Pacthold 管执行与租约。二者不能各自加载、构建和 dispose 同一个插件。

采用“宿主激活事务 + 有所有者的扩展贡献”：

- server-plugin-api 定义通用 contribution carrier（扩展点 ID、版本、所有者、payload）；不导入领域或 Pacthold 类型。
- Pacthold 公共 SDK 定义 CoreContributionSet。Server 内置的中性 Pacthold 接入器接受该类型并 stage 注册。
- 插件的一组 wire/HTTP/服务/Core 贡献先统一验证，随后提交；任一步失败撤销本轮所有贡献并处置一次。
- 必需扩展点缺失拒绝激活；可选贡献必须显式声明缺席行为。不通过任意事件总线隐式发现依赖。
- 独立使用 Pacthold 时直接显式注册 CoreContributionSet，不启动 Server；旧的业务发现 loader 不作为第二个宿主保留。

ServerRuntime 删除业务门面属性及 `_RUNTIME_PORT_FACADES`；消费方只通过已声明依赖获得服务。插件的业务关停移到插件自身生命周期；Server 只按依赖顺序执行通用 drain/stop/dispose。正在运行的操作和资源必须先停止接纳、处理占用，再允许卸载提供者。

hello 的固定基础字段由宿主负责；harnesses/nativeExecution 等既有字段通过插件贡献的、版本化发现投影保留线上形状。字段归属独占、基础字段不可覆盖、重复贡献启动拒绝；宿主不验证品牌或 Profile 业务含义。未来新增领域优先使用命名空间字段。

HTTP 延续已审定的路由冻结方案，不顺便改热插拔协议：挂载形状与鉴权不兼容时类型化拒绝，卸载后同 App 不服务旧 endpoint，重激活只使用新实例。不是所有插件类型都必须支持运行中新增路由。

业务 helpers、错误码和记录仓库移插件。宿主留下通用协议错误/鉴权/存储接口；插件不得从 `wire.handlers` 等私有模块拿工具函数。不是把所有工具复制进一个新的“公共大杂烩包”。

## 6. 前端：提升 Workbench，保留已有效的宿主

### 6.1 Workbench 的平台地位

迁至 `packages/workbench`，保留当前区域、模块、浮层、设置、贡献作用域及现有测试。它仍可作为平台内置扩展被 Lumino 激活；“平台包”不等于 Electron 硬编码，空启用集仍能启动空宿主。

Workbench 与 Pacthold 是同一层级的两个不同内核：一个管理界面组合，一个管理受治理执行；它们没有直接调用关系。

不在此轮合并 Commands 插件或引入新 UI 框架。现有命令接口先明确所有者、保留注入；若查实它纯属平台通用实现，可作为 Workbench 同包内置扩展迁入，不能成为实施者自由发挥的隐性任务。

### 6.2 契约与 Token

- 每个服务/扩展点的公共契约由所有者导出（api 子路径或必要时独立轻量 API 子包），不得要求导入其运行实现。
- Workbench 契约归 Workbench；Chat、ACP 会话、Profile 契约归各领域，而非永远堆进 platform/contracts。
- 既有持久 extension ID、Token 身份与产品清单语义保持。框架 Token 必须是共享模块单实例；同名 `new Token()` 不是同一个服务。
- 迁移调用点与打包映射同批完成；不保留平台向业务插件反向 re-export 的兼容入口。
- Native IPC 当前 `agent-native:*` 名称不因外观不泛化而强行修改；保留线上名字、明确中性帧传输语义。只按名称重命名不是解耦证据。

### 6.3 清理 Desktop 的边界

应用入口只含窗口、preload、安全检查、宿主挂载。业务 smoke 移产品集成测试，业务单测移插件；通用 loader/host/bridge 测试移各平台包。应用保留启动/退出、IPC 边界、空扩展清单测试。

关闭 Chat 视图、卸载前端贡献、关闭 native bridge 句柄、停止后端 Execution 是四种不同操作，不能互相默认推导。任何“关闭即停止”的产品策略必须显式调用业务 API。

## 7. 建议最终目录（职责图，不要求机械重命名内部模块）

```text
apps/
  server/                     # 传输、鉴权、宿主与中性 Core 接入器
  desktop/                    # Electron 启动、安全桥、Host 挂载
packages/
  pacthold/                   # 执行和资源内核及公共 SDK
  server-plugin-api/          # 后端插件宿主契约，零业务依赖
  workbench/                  # 通用界面工作台及公开贡献协议
  desktop-platform/
    extension-api/
    extension-loader/
    extension-host/
    native-bridge/
    contracts/                # 仅实际跨平台共享、无领域所有者的协议
plugins/
  <domain>/                   # 领域契约、frontend/backend 与适配
  server-compat/              # 旧业务承接；不依赖核心私有实现
products/
  server/                     # 显式产品装配
  desktop/                    # 显式产品装配
tests/integration/            # 确实跨包的产品/平台组合测试
tooling/                      # 通用构建/包发现；不 hardcode 插件 ID
docs/design/                  # 需求、决策、契约、验收说明
```

不为对称而新增 universal-kernel、backend-platform 等包。前后端契约不能为了放一起而变成一个跨语言依赖大包；跨语言只共享需要的协议 schema/样例与一致性测试。

## 8. 存储与兼容：清核心不能靠丢数据

当前 Pacthold 历史 SQL 包含 profiles/sessions。不可直接删表或改写已应用迁移编号。

建议增加通用迁移目录注册：数据库迁移器属于基础设施，领域提供自己的迁移集；产品组合明确所有者和顺序。历史 001–009 作为封存的兼容迁移集原样由兼容插件携带（manifest 校验摘要/序号），新的内核迁移另有命名空间。旧数据库 `schema_versions` 的解释由显式升级适配器保留；新裸内核不创建旧业务表。

该步骤必须先用现存旧数据库的脱敏夹具证明升级、历史执行查询与重复启动一致，再迁文件。若涉及用户数据格式变更，必须先取得单独确认；此设计不授权直接迁用户数据库。不能以“临时 shim”搁置，但可以停在此确认门，不谎报全部完成。

记录历史 Ref/contract ID 不强制改字符串；对应类型的解析器归插件，核心遇到缺失解析器可展示中性历史记录，不动态导入卸载的业务包。

## 9. 实施次序与边界

先冻结接缝再并行实现，不让几方同时猜契约。本轮实施文档按 Spec Kit 补齐 spec / research / data-model / contracts / plan / tasks；当前本文是综合设计候选，不是已经无歧义的无人值守任务清单。

| 阶段 | 范围 | 完成条件 |
| --- | --- | --- |
| 0 现场与契约冻结 | 读取实施起点；列所有公开调用点/持久 ID；冻结资源状态、贡献事务、停机语义 | 每个迁移项有 source→owner 和反例；迁移数据风险已裁定 |
| A 执行核心 | Pacthold 的实例化、通用资源机制、旧领域外移 | 独立安装、无业务包测试、两个实例互不干扰、unknown/清理故障门禁 |
| B Server 宿主 | 通用服务/贡献、业务投影和门面外移、中性 Pacthold 接入 | 零业务字段/分支，空组合、旧产品协议对照与生命周期门禁 |
| C 前端平台 | Workbench 迁包、契约与 Token、Desktop 测试归属 | 空 Host/空 Workbench、贡献卸载、singleton、产品受控交互 |
| D 产品适配与集成 | 启用清单、旧插件适配器、脚本与文档 | 干净安装，逐 ID 红账本，跨包运行反例与可复现报告 |

A/B 在阶段 0 之后可并行，但 Core 接入器归 B；C 可独立推进。公共契约包及产品装配每份文件只能有一个写入所有者。插件适配按目录预分所有权，不能两线都修改 server-compat。跨包改动是迁移需要，不据此把所有包合并。

根工作树保持 main；批准后从核实过的当前 main 建隔离工作树。仓内关于古老固定基线的规则须先修订/获明确裁定，不能忽略。主树不切到开发分支、不打断其他 worktree。只在集成门通过后申请合并，远端发布另按授权。

## 10. 验收：证明真正解耦，而非又一次漂亮搬家

每条门禁必须包含缺席、正例和能抓住旧缺陷的反例。禁止只比总数、扫描只看 import 或异常吞掉算成功。

1. Pacthold 独立 wheel 安装：没有 Server/插件，能用虚拟 provider 完成一次执行；同进程两个 Store 互不污染。
2. 资源 A 获取成功、B 失败：仅回收本轮 A；借用资源不销毁；清理失败不盖主因。
3. start 响应丢失：幂等请求不二次 spawn；unknown 时不释放活进程的依赖；查询无证据不得自造终态。
4. 原 Execution 终结后恢复同一 Session：新 Execution ID，原记录不改变。
5. Core+wire 联合注册冲突：任一失败都零可见贡献泄漏，build 后欠账 disposal 恰一次。
6. provider 有活跃/unknown 租约时卸载被拒；停止后晚到帧不得写入新轮。
7. 裸 Server 无业务发行版：仅基础发现/健康/鉴权可用；新增虚拟资源与执行插件不用改宿主源码。
8. 同一个 App 的卸载、重激活、鉴权/签名变化、启动失败+清理失败继续覆盖，不用新建 App 绕过。
9. 空 Desktop 正常；单独 Workbench 无 Chat 正常；只装示例贡献插件即可展示视图/浮层/设置，卸载彻底撤销。
10. 两个真实构建插件消费同一公开 Token 成功；刻意重复 Token/错误共享映射必须失败，不能只测源文件类型检查。
11. 干净克隆测试命令真正聚合各包：收集错误/退出码失败即失败；预期红逐 ID、失败原因与来源记录，不要求以删除断言实现全绿。
12. 旧数据夹具升级前后历史 IDs/内容一致；新裸内核没有 Profile/Session 业务表；真实用户数据未触碰。

最终报告区分：实现通过、受控集成通过、真实模型未测、用户数据未迁。不得从虚拟 provider 通过推出全部 Harness 已可用。

## 11. 研究依据与采用边界

见 [开源架构研究](platform-core-research.md)。本方案不是照搬某一个框架：采用成熟的服务/贡献区分、作用域与运行句柄思想，保留 Ordessa 已有技术栈与协议。

## 12. 用户审核重点

建议先确认三项架构决定：Pacthold 补通用租约而非全应用服务容器；Server 单一激活事务接入 Pacthold；Workbench 迁平台包但仍通过扩展宿主加载。确认后补精确契约和任务文档，再派实施，不从这份草案直接启动无人值守大改。
