# 实施任务 · 唯一任务清单

以下清单在设计时初始全部未执行；当前实施回执见 status.md 和 evidence/implementation-20261005/README.md。依赖为完成对应合同/代码与实际门，不是子代理自报完成。
本包按Spec Kit组织，不建立另一套运行调度账；implementation状态由获授权主执行者持有。
允许最多3子代理、深度1，接口共享面主执行者单写；Git/锁文件/账本/组合根单写，测试串行。

## JD001 · 基线盘点与上游兼容验证

职责：M01、M02、M03、M06。前置：无代码前置；实施与安装授权先确认。
写权：本包实施回执、目标源码映射、独立venv/构建临时目录、依赖采用记录；不改用户环境。

- [x] JD001-01 确认用户授权的实施树/精确SHA/安装范围，保存status与写者清单，复核AGENTS/基线/known issues。
- [x] JD001-02 核实真实pydantic-graph发布包和SDK0.7.2与研究SHA的API/依赖对应，锁wheel哈希和闭包；未匹配则具名阻塞。
- [x] JD001-03 在授权临时环境用真实库跑极小回环/取消/未知路由；真实SDK配fake transport核每次HTTP数。
- [x] JD001-04 冻结Python>=3.10/目标3.12、模型ID候选、数值协议容差和依赖升级门；不发真实网络模型请求。

### 可判定场景
WHEN 本单代码完成并运行定向验证，THEN 缺GraphBuilder或SDK重试未关闭时验证失败，不改自建循环填绿。
验收ID：T03、T30、T33、T37、T63、T64；精确场景与缺席行为见 [acceptance](acceptance.md)。

| Gate | 断言 | 反例 | 缺席/未知行为 |
| --- | --- | --- | --- |
| JD001-G1 | 本单验收ID逐项有证据 | 人为制造上述反例必须被门抓住 | 缺资源/收集错误→失败或PARTIAL，不跳过填绿 |
| JD001-G2 | 写权和依赖不越界 | 植入反向import或mutation调用必失败 | 来源/owner不明→先核查，不修改共享面 |

DoD：实现、定向正反例、真实候选库/SDK或核心接缝证据、回归命令/计数/退出码、预算与清理、状态分账。缺项JD001_PARTIAL；未授权真实调用为NOT_RUN，不报DONE。
每阶段仅在获准实施树提交检查点，保留用户dirty；不push/merge。子代理报告由主执行者复跑后才能勾选。

## JD002 · 公共契约与摘要域冻结

职责：M01。前置：JD001 已验证。
写权：decision/contracts、schema/向量、public精选接口，以及原核心拟增只读DTO合同（设计冻结，不顺手实现）。

- [x] JD002-01 实现不可变DTO/finite JSON/大小/重复键/规范编码，支持空目标任务审查与动态小数。
- [x] JD002-02 固定request/proposal/result/descriptor/runmanifest摘要域、PolicyRef集合、术语和null规则，生成正反向编码向量。
- [x] JD002-03 冻结ports、单次ModelCallContext与许可、ValidationObligations/CheckBatch、技术/业务联合终态。
- [x] JD002-04 冻结JD007原核心inputDigest与decision映射、版本协商、只读保证及源码导出映射；对外合同变更交主会话审阅，不让各模块自行发明。

### 可判定场景
WHEN 本单代码完成并运行定向验证，THEN 仅结构valid不能ready，缺must checker/义务必须拒绝。
验收ID：T01、T02、T07、T08、T09、T10、T17、T18、T65、T66；精确场景与缺席行为见 [acceptance](acceptance.md)。

| Gate | 断言 | 反例 | 缺席/未知行为 |
| --- | --- | --- | --- |
| JD002-G1 | 本单验收ID逐项有证据 | 人为制造上述反例必须被门抓住 | 缺资源/收集错误→失败或PARTIAL，不跳过填绿 |
| JD002-G2 | 写权和依赖不越界 | 植入反向import或mutation调用必失败 | 来源/owner不明→先核查，不修改共享面 |

DoD：实现、定向正反例、真实候选库/SDK或核心接缝证据、回归命令/计数/退出码、预算与清理、状态分账。缺项JD002_PARTIAL；未授权真实调用为NOT_RUN，不报DONE。
每阶段仅在获准实施树提交检查点，保留用户dirty；不push/merge。子代理报告由主执行者复跑后才能勾选。

## JD003 · 原版图薄运行器

职责：M02。前置：JD002 已验证。
写权：runtime及其定向tests，不能改contracts/providers/产品/上游私有代码。

- [x] JD003-01 公开async入口/new_state/显式flow绑定与可信图接纳；保留上游结构校验，不引入while执行器。
- [x] JD003-02 实现节点入口预算、统一模型gateway、并发slot、单次run+摘要绑定许可；SDK不暴露给节点。
- [x] JD003-03 绑定durable evidence端口、完成取消顺序点与有界shield；真实Evidence实现等JD008，先fake故障端口。
- [x] JD003-04 验证两个run隔离、只读并行汇合、异常/超时/未知不报成功；清理不关闭共享provider。

### 可判定场景
WHEN 本单代码完成并运行定向验证，THEN 剩一attempt两协程不能都发网；完成后取消不能写第二终态。
验收ID：T04、T05、T06、T11、T12、T13、T14、T15、T16、T19、T20、T23、T24、T25、T28、T29、T30；精确场景与缺席行为见 [acceptance](acceptance.md)。

| Gate | 断言 | 反例 | 缺席/未知行为 |
| --- | --- | --- | --- |
| JD003-G1 | 本单验收ID逐项有证据 | 人为制造上述反例必须被门抓住 | 缺资源/收集错误→失败或PARTIAL，不跳过填绿 |
| JD003-G2 | 写权和依赖不越界 | 植入反向import或mutation调用必失败 | 来源/owner不明→先核查，不修改共享面 |

DoD：实现、定向正反例、真实候选库/SDK或核心接缝证据、回归命令/计数/退出码、预算与清理、状态分账。缺项JD003_PARTIAL；未授权真实调用为NOT_RUN，不报DONE。
每阶段仅在获准实施树提交检查点，保留用户dirty；不push/merge。子代理报告由主执行者复跑后才能勾选。

## JD004 · 官方Jev SDK接入

职责：M03。前置：JD002 已验证。
写权：providers/jev和真实SDK假transport测试；独立于JD003文件，接口只读。

- [x] JD004-01 独立provider拥有官方async client，固定端点/模型settings，retries=0，任务不能覆写请求体/URL。
- [x] JD004-02 Choice/Score/Noul映射与精确回答集合/数值/模型校验；未知SDK类型丢失仍失败。
- [x] JD004-03 许可/deadline发前验证、每次网络尝试统计，费用缺失unknown，取消向上传播。
- [x] JD004-04 落实secret resolver、body日志禁用、安全异常，66选项含拒绝槽；锁依赖升级测试。

### 可判定场景
WHEN 本单代码完成并运行定向验证，THEN SDK429只准一次HTTP，Noul不生成confidence或表示无候选。
验收ID：T33、T34、T35、T36、T37、T38、T39、T40、T41、T42、T68；精确场景与缺席行为见 [acceptance](acceptance.md)。

| Gate | 断言 | 反例 | 缺席/未知行为 |
| --- | --- | --- | --- |
| JD004-G1 | 本单验收ID逐项有证据 | 人为制造上述反例必须被门抓住 | 缺资源/收集错误→失败或PARTIAL，不跳过填绿 |
| JD004-G2 | 写权和依赖不越界 | 植入反向import或mutation调用必失败 | 来源/owner不明→先核查，不修改共享面 |

DoD：实现、定向正反例、真实候选库/SDK或核心接缝证据、回归命令/计数/退出码、预算与清理、状态分账。缺项JD004_PARTIAL；未授权真实调用为NOT_RUN，不报DONE。
每阶段仅在获准实施树提交检查点，保留用户dirty；不push/merge。子代理报告由主执行者复跑后才能勾选。

## JD005 · 外部rubric任务准入

职责：M04。前置：JD003、JD004 已验证。
写权：flows/agent_assignment/task_gate、版本化默认policy资源及tests；build由主执行者整合。

- [x] JD005-01 实现纯规则缺字段/风险边界检查，合法不足任务零模型可输出澄清。
- [x] JD005-02 外部六维rubric编译有限Choice/Score问题及代码/证据模板，不自由生成解释。
- [x] JD005-03 确定性聚合技术故障/fatalBusinessBlock/clarify/revise/pass；无授权事实不得通过。
- [x] JD005-04 实现run内/可信旧证据的无新增相关信息检测，不建全局缓存，不自动拆分派工。

### 可判定场景
WHEN 本单代码完成并运行定向验证，THEN 多步骤单交付可通过，多个独立目标不自动变成执行队列。
验收ID：T43、T44、T45、T46、T47、T48；精确场景与缺席行为见 [acceptance](acceptance.md)。

| Gate | 断言 | 反例 | 缺席/未知行为 |
| --- | --- | --- | --- |
| JD005-G1 | 本单验收ID逐项有证据 | 人为制造上述反例必须被门抓住 | 缺资源/收集错误→失败或PARTIAL，不跳过填绿 |
| JD005-G2 | 写权和依赖不越界 | 植入反向import或mutation调用必失败 | 来源/owner不明→先核查，不修改共享面 |

DoD：实现、定向正反例、真实候选库/SDK或核心接缝证据、回归命令/计数/退出码、预算与清理、状态分账。缺项JD005_PARTIAL；未授权真实调用为NOT_RUN，不报DONE。
每阶段仅在获准实施树提交检查点，保留用户dirty；不push/merge。子代理报告由主执行者复跑后才能勾选。

## JD006 · 工作单元选择与可替换组合器

职责：M05。前置：JD003、JD004 已验证。
写权：selection/proposals/composition及tests；不改M04/build/核心/品牌适配。

- [x] JD006-01 实现七动作数据要求、硬约束过滤和可版本化默认排序，模型只选合法ID。
- [x] JD006-02 定义并接入ProposalSource；参考确定性组合器依据外部模板/处理器/有限选项，有界剪枝，不猜字段语义。
- [x] JD006-03 保留目录分页/完整性与拒绝槽，限制64业务候选/66总选项及修正轮次。
- [x] JD006-04 实现义务覆盖的外部校验与新反馈回环；未知/过期/无进展停止，ready非已应用。

### 可判定场景
WHEN 本单代码完成并运行定向验证，THEN 新kind+0.7不改引擎，空不完整候选不能触发create。
验收ID：T49、T50、T51、T52、T53、T54、T58、T67；精确场景与缺席行为见 [acceptance](acceptance.md)。

| Gate | 断言 | 反例 | 缺席/未知行为 |
| --- | --- | --- | --- |
| JD006-G1 | 本单验收ID逐项有证据 | 人为制造上述反例必须被门抓住 | 缺资源/收集错误→失败或PARTIAL，不跳过填绿 |
| JD006-G2 | 写权和依赖不越界 | 植入反向import或mutation调用必失败 | 来源/owner不明→先核查，不修改共享面 |

DoD：实现、定向正反例、真实候选库/SDK或核心接缝证据、回归命令/计数/退出码、预算与清理、状态分账。缺项JD006_PARTIAL；未授权真实调用为NOT_RUN，不报DONE。
每阶段仅在获准实施树提交检查点，保留用户dirty；不push/merge。子代理报告由主执行者复跑后才能勾选。

## JD007 · 原Agent公共只读接缝补齐

职责：M06。前置：JD002 已验证。
写权：原Agent公开只读合同/owner转发与核心测试；必须协调当前核心写者；不导入decision/Jev。

- [x] JD007-01 按固定当前SHA核查describe offers/assessment是否已存在；已存在就映射和验证，不重复造。
- [x] JD007-02 新增版本化可选纯读能力和公开DTO，只路由已有registry/owner，旧provider unsupported。
- [x] JD007-03 pure-read assessment覆盖schema/动作/版本/材料/组合义务；有作用才能核实项unverifiable。
- [x] JD007-04 fake owner证明授权/换代/退役/版本拒绝及mutation/file/process零调用；真实家族支持逐家登记。

### 可判定场景
WHEN 本单代码完成并运行定向验证，THEN 不能调用preview假通过、reserve/prepare试探、私有admitted.provider填接缝。
验收ID：T55、T56、T57、T61、T62、T65；精确场景与缺席行为见 [acceptance](acceptance.md)。

| Gate | 断言 | 反例 | 缺席/未知行为 |
| --- | --- | --- | --- |
| JD007-G1 | 本单验收ID逐项有证据 | 人为制造上述反例必须被门抓住 | 缺资源/收集错误→失败或PARTIAL，不跳过填绿 |
| JD007-G2 | 写权和依赖不越界 | 植入反向import或mutation调用必失败 | 来源/owner不明→先核查，不修改共享面 |

DoD：实现、定向正反例、真实候选库/SDK或核心接缝证据、回归命令/计数/退出码、预算与清理、状态分账。缺项JD007_PARTIAL；未授权真实调用为NOT_RUN，不报DONE。
每阶段仅在获准实施树提交检查点，保留用户dirty；不push/merge。子代理报告由主执行者复跑后才能勾选。

## JD008 · 只读适配、持久证据与交接

职责：M06。前置：JD003、JD007 已验证。
写权：integrations/ordessa、evidence及tests；public/shared由主执行者协调。

- [x] JD008-01 只读facade映射公开Profile/Node/Provider/配置观察，完整性/sourceVersion/unknown保持，图看不到写面。
- [x] JD008-02 实现独立文件证据writer锁、append_durable ACK、fsync、终态原子幂等与ACK未知查询。
- [x] JD008-03 实现call.intent五个crash窗和started无terminal宿主/锁核实；unknown/interrupted只查询不续跑。
- [x] JD008-04 实现安全日志/路径/权限/取消shield与提案交接，原生mutation次数0；原RequestKey不被runId替换。

### 可判定场景
WHEN 本单代码完成并运行定向验证，THEN 活writer无terminal不是interrupted；terminal磁盘满不能报ready。
验收ID：T21、T22、T24、T25、T26、T27、T28、T31、T32、T55、T56、T58、T62；精确场景与缺席行为见 [acceptance](acceptance.md)。

| Gate | 断言 | 反例 | 缺席/未知行为 |
| --- | --- | --- | --- |
| JD008-G1 | 本单验收ID逐项有证据 | 人为制造上述反例必须被门抓住 | 缺资源/收集错误→失败或PARTIAL，不跳过填绿 |
| JD008-G2 | 写权和依赖不越界 | 植入反向import或mutation调用必失败 | 来源/owner不明→先核查，不修改共享面 |

DoD：实现、定向正反例、真实候选库/SDK或核心接缝证据、回归命令/计数/退出码、预算与清理、状态分账。缺项JD008_PARTIAL；未授权真实调用为NOT_RUN，不报DONE。
每阶段仅在获准实施树提交检查点，保留用户dirty；不push/merge。子代理报告由主执行者复跑后才能勾选。

## JD009 · 整合、独立发行与产品级只读验收

职责：M01、M02、M03、M04、M05、M06。前置：JD005、JD006、JD008 已验证。
写权：组合根/build/public/pyproject/locks/examples、可选独立CLI及tests/文档；不改默认启动链。

- [x] JD009-01 主执行者整合可信flow及完整服务注入，flowDigest绑定实际代码/policy；无rawSDK/完整AgentServices流入节点。
- [x] JD009-02 独立wheel/可选extra，offline_assignment+alternate_flow，可选propose CLI默认offline无apply/任意module。
- [x] JD009-03 真实临时核心+真实库+fake模型纵向验证，所有效果计数0，缺家族能力诚实PARTIAL。
- [x] JD009-04 串行逐场景复跑T01–T59/T61–T68，按ID比对回归继承红，记录counts/exits/证据/清理与可试入口；更新readiness账。

### 可判定场景
WHEN 本单代码完成并运行定向验证，THEN 套件绿不覆盖没跑的真实核心、Jev质量或原生应用。
验收ID：T01、T02、T03、T04、T05、T06、T07、T08、T09、T10、T11、T12、T13、T14、T15、T16、T17、T18、T19、T20、T21、T22、T23、T24、T25、T26、T27、T28、T29、T30、T31、T32、T33、T34、T35、T36、T37、T38、T39、T40、T41、T42、T43、T44、T45、T46、T47、T48、T49、T50、T51、T52、T53、T54、T55、T56、T57、T58、T59、T61、T62、T63、T64、T65、T66、T67、T68；精确场景与缺席行为见 [acceptance](acceptance.md)。

| Gate | 断言 | 反例 | 缺席/未知行为 |
| --- | --- | --- | --- |
| JD009-G1 | 本单验收ID逐项有证据 | 人为制造上述反例必须被门抓住 | 缺资源/收集错误→失败或PARTIAL，不跳过填绿 |
| JD009-G2 | 写权和依赖不越界 | 植入反向import或mutation调用必失败 | 来源/owner不明→先核查，不修改共享面 |

DoD：实现、定向正反例、真实候选库/SDK或核心接缝证据、回归命令/计数/退出码、预算与清理、状态分账。缺项JD009_PARTIAL；未授权真实调用为NOT_RUN，不报DONE。
每阶段仅在获准实施树提交检查点，保留用户dirty；不push/merge。子代理报告由主执行者复跑后才能勾选。

## JD010 · 真实Jev领域评测（另行授权）

职责：M03、M04、M05。前置：JD009 已验证。
写权：授权受控模型评测、领域样本/报告；不启真实Harness或修改用户配置。

- [x] JD010-01 固定脱敏标签样本、模型ID/rubric/阈值与输入规模，向用户取得maxattempt/成本/隐私范围授权。
- [x] JD010-02 运行中文任务边界/颗粒度、候选顺序、未知配置与攻击文本评测，记录真实usage/unknown费用。
- [x] JD010-03 区分协议机制成功与判断质量不足；未达标准不自动改阈值或宣称成熟。
- [x] JD010-04 输出liveJevValidated或PARTIAL/NOT_RUN及失败样本、费用、清理，不自动推广为产品默认或实际应用。

### 可判定场景
WHEN 本单代码完成并运行定向验证，THEN 没授权或key时NOT_RUN，不使用其他模型/账号fallback。
验收ID：T60；精确场景与缺席行为见 [acceptance](acceptance.md)。

| Gate | 断言 | 反例 | 缺席/未知行为 |
| --- | --- | --- | --- |
| JD010-G1 | 本单验收ID逐项有证据 | 人为制造上述反例必须被门抓住 | 缺资源/收集错误→失败或PARTIAL，不跳过填绿 |
| JD010-G2 | 写权和依赖不越界 | 植入反向import或mutation调用必失败 | 来源/owner不明→先核查，不修改共享面 |

DoD：实现、定向正反例、真实候选库/SDK或核心接缝证据、回归命令/计数/退出码、预算与清理、状态分账。缺项JD010_PARTIAL；未授权真实调用为NOT_RUN，不报DONE。
每阶段仅在获准实施树提交检查点，保留用户dirty；不push/merge。子代理报告由主执行者复跑后才能勾选。

## 并行单元与串行接缝
JD003 runtime 与 JD004 provider目录独立可并行；JD005 task_gate 与 JD006 selection/proposals/composition独立可并行。
JD007核心接缝与JD008消费者接口强耦合，先JD007冻结/验证；JD008证据文件实现可先独立进行，但不能提前声称adapter完成。
JD009组合根、pyproject、lockfiles、public、状态和Git仅主执行者写。JD010实际调用必须单独授权。
局部阻塞把原因/解除条件记账，继续明确不依赖任务；整队确实阻塞才交接。检查点不代表停止。

## 建议验证命令（仅实施后在授权环境执行）
python -m pytest packages/backend/decision/tests/contracts -q
python -m pytest packages/backend/decision/tests/runtime -q
python -m pytest packages/backend/decision/tests/providers -q
python -m pytest packages/backend/decision/tests/flows -q
python -m pytest packages/backend/decision/tests/integration -q
python -m pytest packages/backend/decision/tests/acceptance -q
python packages/backend/decision/examples/offline_assignment.py
python packages/backend/decision/examples/alternate_flow.py
上述目标路径未实现时命令应失败，不把‘没有测试’视为成功。真实Jev命令不在这里提供自动可运行入口。


## 当前实施状态
JD001–JD008 在记录的离线/临时核心范围验证；JD009 已实现并逐场景复验，但真实家族能力缺席，状态 PARTIAL；JD010 已授权并运行真实 Jev 合成评测，质量与容量协议门 PARTIAL；最新详见 evidence/jev-domain-v2-20261005/README.md，历史超时保留。勾选表示本项授权实施和离线验证完成，不表示真实 Jev 或原生效果完成。

实施交付审计见 [completion-audit](completion-audit.md)。40个JD子项已交付；JD009/JD010要求的缺席/未达标PARTIAL结果仍保留，未提升产品就绪层级。
