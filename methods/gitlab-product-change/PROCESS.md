# GitLab Product Development Flow — process specification

本文件是完整外部流程的设计规格。它把 GitLab Handbook 中的阶段与状态整理成供 Ordessa 用户记录、协商和复盘的报告契约；它不表示当前方法引擎能驱动该生命周期。本目录没有承载完整流程的可编译 manifest；`projection/` 中只有一个明确标记为 smoke 的单步报告 Artifact 登记投影，不能视为完整流程方法。详见 [COVERAGE.md](COVERAGE.md) 和 [GAPS.md](GAPS.md)。Git、CI、MR、审批、部署、观测和外部 issue 状态均由相应 GitLab 实例、团队及授权执行者负责。Ordessa 不读取目标仓库代码自行验收，也不替外部身份系统做审批。

## 1. 目标、边界与原则

本流程把问题、方案、计划、实现与测试/评审、部署验证、结果评估串成可追溯的产品变更记录。每个阶段都留下 DRI、决策、时间及来源引用；未开展、跳过、阻塞、返工、延期、拒绝、取消都要明示。`merge request merged` 仅表示相应代码合入；它不是部署、生产可见或用户结果的证明。

GitLab Product Development Flow 把 Validation 与持续推进的 Build 视为相互独立的两条轨道，可重叠或并行；工作类型、既有置信度和风险可决定缩短或跳过某一阶段。每次跳过都应由负责的 DRI 记录理由、证据与审批/对齐依据。不要把阶段图理解成强制瀑布或把两轨合并成单一顺序状态。[来源与页面观察记录见 SOURCES.md](SOURCES.md)。

本方法不嵌入 Ordessa DID、Jev、Spec Kit 或仓库内的特定实现方式。项目只有在其外部治理明确要求时才使用这些机制，并由对应所有者提供记录。

## 2. 输入、前置依赖与参与角色

启动外部 issue 前，应确认：

- GitLab 项目路径、issue/epic、当前状态模型和准确状态值、工作类型、主 DRI、目标用户/客户与业务目标。
- 已知问题证据、未决假设、依赖与风险；若需要验证，至少写清要验证的假设和可观察指标。
- 设计/方案、无障碍、安全、隐私、法律或合规评估的适用性及 owner；不适用时记录工作类型理由。
- MVC/最小可交付变更、验收条件、实现依赖、目标 milestone/发布、测试计划与 review owner。
- 部署目标（GitLab.com、Self-Managed、两者、其他或尚未选定）、发布/版本 owner、回滚或缓解安排、上线后反馈来源及测量窗口。
- 所有外部系统身份、访问权限和批准路径。Ordessa 的记录或 Actor attribution 本身不是这些权限。

按阶段指定实际责任人。常见参与者有 Product Manager、Product Designer、UX Researcher、Development/Engineering、Engineering Manager、Security、Legal/Privacy、MR reviewer/maintainer、release/deployment owner、Support、Analytics 与客户/用户代表。团队应按 GitLab 当前角色规范及自身控制要求指派；规格不把职位名称等同于授权，也不代替指定审批人。阶段决定至少记录决定人、时间、结论、理由和外部批准/讨论引用。

## 3. 外部阶段和进入/退出记录

### 3.1 问题验证（Validation track）

1. **Validation backlog**：输入是新 issue、反馈或发现。PM DRI 整理描述、需求来源、背景、优先级和关联 item。退出记录是已排序且足以让跨职能成员理解的单一事实来源；否则保留在 backlog 并记录待补信息。
2. **Problem validation**：确认用户问题是否真实、重要且有证据支持。记录用户/客户信号、研究/产品数据、目标人群、业务目标、假设和不确定性。置信度不足时继续验证，或明确拒绝/延期；不得把方案偏好写成问题证据。
3. **Ready for design / Design**：若需要设计，记录用户旅程、交互方案、原型、无障碍与相关风险审查。若工作不需设计，记录由谁判定及原因。
4. **Solution validation**：对拟议方案进行研究、实验或用户测试，记录与问题/业务目标关联的结果、预期指标、MVC 及后续迭代。进入 Build 前，PM/设计/工程 DRI 需记录方案置信度和优先级决定；置信度不足时可继续验证。

### 3.2 计划、开发与测试（Build track）

1. **Planning breakdown / scheduling / refinement**：明确 MVC、issue 拆分、权重/依赖、里程碑、工作类型、验收标准与 review/test 安排。是否排入 milestone 由相应 DRI 决定；`Planning breakdown` 不自动等于已承诺开发。
2. **Ready for development**：记录开发可开始的依据、milestone 和必要工作类型/交付标签（这些标签随项目政策而异）。任何安全、法务或设计前置条件要有 owner 和状态。
3. **In dev**：GitLab issue 关联实现工作、提交/MR 与变更范围。开发者/团队报告来源 revision/commit、完成项、未完成项和 blockers。Ordessa 只接收报告，不扫描代码或运行命令核实。
4. **测试与 MR review**：为适用的自动/人工检查报告精确运行来源、版本、目标环境、结果和证据链接；review 记录 reviewer、意见、解决或未决项、pipeline 与批准引用。检查失败、证据不足或 review 请求变更时，记录返工并由 GitLab/团队完成后续工作。
5. **合并与验证**：MR 合并后可进入 GitLab issue `Verification`；合并只绑定合入 revision。随后按已选部署路径，对确切版本/commit 在 staging、canary、production 或 Self-Managed 安装进行验证。只有该目标环境的证据支持时，才记录相应环境的已部署/已验证结论。

### 3.3 部署与版本绑定

在报告中显式选择部署模型。两个路径的 event 列表独立记录，不推断一边完成就意味着另一边可用。

- **GitLab.com**：按适用的 GitLab 内部路径记录 deployer pipeline、staging/canary、blocking smoke/E2E、production canary、promotion/production checks、最终 live version 与任何 post-deployment migration。Handbook 中的实例名和次序是 GitLab.com 内部流程示例，团队须以实际运行策略为准。
- **Self-Managed**：记录 stable branch/tag、release/package build 和发布、安装方实际安装/升级的版本、patch release、目标实例验证及 post-deployment migration。上游 stable release/package 流程完成和包可供安装是 Self-Managed 的发布结果；它不声称任一特定客户实例已安装。目标实例安装/升级和版本核验是另一个可选环境事实，分别记录证据。
- **Other / not selected**：说明目标或尚未选择原因，并保留 owner 与下一次决策时间。

对每次部署或发布 event，记录目标环境、准确版本/tag/commit、结果、时间、负责确认者和外部证据。Self-Managed 的 release/package publication 和各目标 instance 的 installed/live version 分别记录：前者可支持上游发布完成，后者只描述被核验的指定实例。必须区分 `merged_commit`、发布/包版本、已安装版本和已观察的 live version。未在目标环境核验时把结果记为 `unknown`/`not_run`/`deferred`，不能借 MR 状态或发布记录推导上线成功。

### 3.4 结果评估、反馈与后续决定

交付之后由 PM/产品 owner 与 Analytics、Support、工程和用户反馈来源共同评估。事先登记 metric 定义、baseline、目标、观测值、测量窗口、来源与 owner；同时记录用户体验、功能/技术表现和客户影响。Ordessa 报告契约的数值字段接受整数、`null` 或精确十进制字符串（例如 `"0.70"`），不接受 JSON 浮点数；这属于 Ordessa 对规范化 JSON 报告的适配约束，不是 GitLab 上游流程要求。决定可为继续、迭代、回滚、放弃、重启问题验证、延长测量或未知。目标未达成时，记录纠偏/回滚/重启验证的决定以及负责人、后续 issue/ref 和时间；不能把功能上线本身视为产品成功。结尾需写关闭、延期、取消、duplicate、won't do 或仍开放的理由及反馈回路。

## 4. 双轨连接、跳过、重叠与外部等待

Validation 和 Build 有各自的阶段状态、owner 与证据链。报告以链接记录 `overlap`、`feeds`、`blocks`、`unblocks`、`handoff` 或 `skip_decision`，保留重叠的起止时间与共同决定。对 bug、已知问题、设计微调、技术债等可能不需要完整验证的工作，负责 DRI 应结合具体工作类型与置信度决定哪些阶段可缩短；不要仅根据标签自动跳过。若先做工程技术评估、而 PM/UX 仍在验证，记录两个阶段并行及各自产出。

等待客户输入、依赖解除、安全发布周期、审批、pipeline 或测量窗口时，外部 issue 应保留阻塞原因、责任方、最近行动、预计时间（未知也要明说）、下一次检查时间及恢复条件。根据团队规则复查并升级；解除后返回受影响的原阶段并记录解决引用。评审要求变更或测试失败时，使用新的 revision/issue/MR 记录返工，重新跑受影响的必要检查，再核验相应部署与结果。延迟/取消则记决策人、理由、状态、未完成项的 owner 和恢复/关闭条件。

`projection/` 中的 smoke workflow 没有 wait node。以上等待、恢复、返工和延迟均由外部系统与人完成并作为报告提交；不得把这些文字误读为 Ordessa 会等待或推进 issue。

## 5. 状态来源与差异记录

GitLab Product Development Flow 页面当前正文使用 issue statuses，并附有 scoped `workflow::*` labels 到 statuses 的迁移表；该表写明旧 labels 预计在 2026-02-27 后 unsupported。页面指出阶段可按情境跳过，Validation 和 Build 可以重叠/并行。另一个名为 Application Lifecycle 的团队工作流页，页脚显示 2026-08-21 修改，仍展示旧 workflow labels、Kanban 与本团队跳过阶段的策略。它是某团队工作流，不代表 Product Development Flow 的通用现行状态规范。两个公开页面同时存在并体现不同团队/迁移视角；本方法记录观察到的模型、值、页面日期，不裁决某个实例实际已部署哪套状态字段。报告中应抄录外部 issue 当前真实模型和值。

Product Development Flow 的映射还列有 `Duplicate` 与 `Won't do`，没有旧 workflow-label 对应项。迁移表与后续团队标签示例不要自动合并；报告保留精确来源和观察时间。

## 6. 报告契约与操作责任

完整报告契约的 machine schema 在 `projection/documents/product-change-report.schema.json`，人读模板在同目录 Markdown。schema 规定报告结构，不表示完整生命周期 manifest 存在。它要求所有主阶段、每条轨道适用性/skip rationale、两轨关系、roles/decision owners、blocker/rework、MR、两类 deployment path、版本绑定、结果 metric 和 closure/feedback 区块都出现。尚未发生的事件应明确标记，而非删掉字段。

要登记报告，外部提交者应先用已发布的精确方法快照构造 `MethodPayload`，将 `value` 设为完整报告对象，设置准确 `schema_ref`、resource digest/path/id 和对应 `schema_id`；同一个 `MethodRef` 放入 `method_refs`。传给 `engineering.artifacts.create` 的初始 slots 为：

- `artifact_kind`: `other`（此命令当前把 kind 作为输入槽，method graph 不支持常量或 value schema 校验）。
- `initial_payload`: method-bound payload，包含以上报告 value。
- `method_refs`: 至少包含该 payload 引用的准确 released `MethodRef`。

注册 operation 的输入 schema 接受 `kind`、`initial`、`method_refs` 字段；方法图只把这些 slots 映射到实际 operation 入参。artifact owner 会对 method-bound payload 做 schema/resource/method-ref 解析和验证。节点所有已注册 workflow outcome 必须保留：`completed` 只表示报告 Artifact 事务完成；`rejected` 表示记录请求被拒。两者都不是外部流程状态、审核通过、部署成功、来源真实性或产品接受结论。未知 outcome 不会被本图处理成安全的自动重试。

## 7. 流程映射和表达边界

| 外部产品流程 | 本方法完整规格 | `projection/` 中的 smoke 投影 |
| --- | --- | --- |
| 问题验证 | 输入信号、问题证据、假设/metric、验证决策 | 报告 schema/template 可承载；图不执行验证 |
| Design / solution validation | 设计、实验/研究结果和跳过决定 | 报告 schema/template 可承载；无真实评估或审批 operation |
| Plan / develop / test / review | 计划、版本/MR/test/review 引用和返工 | 报告 schema/template 可承载；图不跑 Git/CI/review |
| Deploy verification | GitLab.com 与 Self-Managed 分开的路径、版本/环境/证据；区分上游发布与指定实例安装 | 报告 schema/template 可承载；无 deploy/wait/current-source descriptor |
| Improve / outcome | metrics、客户反馈、迭代/rollback/abandon/重启验证 | 报告 schema/template 可承载；图不观察结果或启动下一轮 |
| Block / wait / resume / cancel | 阻塞 owner/恢复条件和新 report/revision | 仅报告；当前无 registered wait descriptor，不能在图内恢复或循环 |

另见 [GAPS.md](GAPS.md)。
