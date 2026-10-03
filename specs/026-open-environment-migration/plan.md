# L2 迁移阶段

## 层级与顺序

L0目标→L1权威/合同→L2批次→L3工单→L4任务→L5证据。级别是依赖深度，不是允许“低优先级不做”。完整迁移要收口001–012。

| 阶段 | 工单 | 结果 | 前置 |
| --- | --- | --- | --- |
| S0 来源与基线 | 001 | 经批准、可复现、包含已验产品修复的源快照 | 无 |
| S1 契约冻结 | 002 | E1/F1/C1/C2/E2/E3/E4/E5/A1可编译+兼容矩阵 | 001 |
| S2 可独立环境 | 003/004/005 | 空环境、统一激活、durable证据 | 003依002；004依003；005依003+004 |
| S3 后端切换 | 006/007 | Server转同环境、Harness/资源/历史接入 | 004+005；007依006 |
| S4 前端运行底座 | 008/009 | frontend归组、Workbench、桥/surface | 002；009依008+007 |
| S5 领域与提交 | 010/011 | 唯一配置/草稿/目标+前后端集成 | 007+009；011依010 |
| S6 整体交付 | 012 | 清旧实现、完整构建/打包/验收/文档 | 003–011 codeReady-SI；完整DONE另需全部U/P |

推荐一个牵头Agent顺序001→002→003→004→005→006→007→008→009→010→011→012。008有条件可提前纯机械迁移，但不得用它代替后端保证或在共享清单/lock上并写。

R4补充同队列：002冻结E4/F4/E5/A1与plugin-architecture；004关系门，005数据/秘密/持久引用证据，006平台适配与薄Server，007资源领域归组/品牌移Harness，008前端归组/命令/装配目录，009宿主交互/诊断，010Agent公开owner，012独立入口及产物闭包。新增任务显式登记，不再以只有补充散文代表全部编码动作；依赖仍同树codeReady-SI。

## 分级依赖：可推进不等于已完成

每单产生两个独立结论：codeReady与fullDone。codeReady须该单要求的源码实现、S/I验收、定向反例、逐ID回归、合同和必要前置通过，有固定SHA、caseIDs和缺口；不能只完成移动路径。fullDone还需本单U/P与获批真实操作验收，任一缺失整单PARTIAL/BLOCKED。

后序depends_on明确仅消费codeReady-SI。例如008的A26/真实IME未跑，不阻009的受控桥实现；011真实三品牌A43/A44待授权，不阻012构建、退役守卫和解包controlled验收。012最终fullDone必须全部必需U/P通过，绝不把上游codeReady统计为DONE。某个S/I gate本身缺席仍阻依赖，无权限不能“豁免”换绿。

codeReady receipt字段：orderId、implementationSHA、baselineSHA、contractHashes、requiredSiCaseIds、每项evidence/exit、counterexample结果、deferredUpCaseIds、unresolvedDefects、effectiveGuarantees。001额外有source approval/manifest，002额外有合同冻结和支持矩阵。实施树下一单核验receipt所需保证，PARTIAL中不存在所需证据则拒。

005同步CoreBinding与product的具体Store构造消费者，仅改变注入不切双权威；006随后统一生命周期。避免005删public CoreStore而006前Server红的依赖死锁。必要范围已在工单写权显式列出。

## 检查点

每单结构、定向、反例与受控回归通过后，本实施分支提交并记录SHA；用户可见单007/009/011/012给可试入口。检查点继续下一ready单，不等待用户来点确认；权限/语义硬闸门除外。不按“最后阶段”口头汇报，status精确列task完成/待测/blocked。

## 最少循环

每阶段：读授权/源变动→选依赖已证ready单→实现→反例→受控集成→回归逐ID比较→更新证据和账→提交检查点→下一单。缺资源或设计矛盾记录阻塞；有独立ready单就继续。没有ready单才交回用户，不后台无限轮询。

禁止先全仓移动再修几十个红：后端权威先在现路径收口，再归backend；前端机械移动必须同步exports/构建保持可测。002映射清楚之后，内部模块迭代可分多提交，不一次重写已有核心。
