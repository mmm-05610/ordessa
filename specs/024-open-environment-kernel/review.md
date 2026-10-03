# 交审结论

日期：2026-10-03（Asia/Shanghai）。**交付：V3附条件候选模型与重构方案；尚未冻结，不是生产重构完成。**

## 主验收补充：A-01/A-02

独立验收另发现两处：A-01/high为Ref缺owner实例ID，允许I1/g1/S与I2/g1/S碰撞；A-02/medium为历史重放read-or-invoke措辞与独立history-read要求冲突。用户要求直接修后，主会话修正V3正式定义及重放分支，新增X13/X14。原攻击、F1和原32项证据不覆盖、不删除。

修后34项参考检查退出0；恢复两个旧行为的内存变异均被新增反例拒绝，记录于evidence/acceptance-repair-checks.json。两项状态为**closed-in-document-and-finite-reference**，不是生产实现通过，也不把主会话复跑冒称新一轮独立审查。D4/D5/D6及跨侧合同仍需收口。

## 一屏结论

模型是开放工作环境：安装单元、插件激活、参与者实例、原生交互入口、活动、长寿命对象与使用关系分开；一个后端运行权威，不逐项复制原生Agent能力。普通只读查询可无Store/Lease，效果性入口投递需要明确保障。
原生新能力在已承载入口可达，无需Core新增功能API；新协议/未承载原生UI仍有适配缺口。组件正常移除会关闭新业务并按退出合同交代已有责任，历史与unknown不被抹掉；静态资源可保留内容后移除本方关系。

已完成现状盘点、边界与V1→V2→V3修订、两轮各3个并行攻击与独立候选复查。40项攻击完整保留原严重度（7 blocker / 29 high / 4 medium），另有1项独立复查文档编号缺陷F1。没有生产代码/服务/真实模型/资产/凭证/Git写操作。

请先读 [V3模型](models/v3.md) 与 [重构实施方案](refactor-plan.md)。证据入口：[盘点](inventory.md)、[边界/用户裁决](boundary.md)、[两轮攻击](attacks/round-1.md)、[第二轮/勘误](attacks/round-2.md)、[场景与验证层次](scenarios.md)、[状态](status.md)。

## 三项政策仍待答

前两项用户已选：D1入口授权/原生审批；D2正常移除先等已有工作结束。以下不将建议当批准，异步问题仍待答；条件候选已供审查，不重复问相同问题。

| 项 | 建议分支 / 代价 | 若不选或未答 |
| --- | --- | --- |
| D4 收尾链 | 允许已有工作必须经过的新确认、晚对象清理、显式恢复原角色、既存依赖查询；受根责任/cut/原权限/预算约束，不开新任务 | 8项中的收尾问题不能冻结；若禁止新交互，已有工作可能无法结束，需另拟退出合同 |
| D5 未枚举owned范围 | 已知会话关闭不等全部工作结束；owned partial/opaque要求充分退出范围停止证明，无证据保持移除待完成 | 不能将“只提示未发现工作”冒充用户D2；若允许立即移除需明确授权与残留事实方案 |
| D6 未知输入指纹 | 命令无关protected fingerprint比较完整输入，安全意图不存密码；缺能力发前明确拒绝，不裁剪、不重发、不降memory | 未知输入开放性与安全去重分支不能冻结；若无port也允许发送，需单独降级合同和重新核对 |

D3仍为未来持久数据迁移/标识兼容待决，仅实施前需批准；允许收尾不授予数据迁移权。曾有临时编号冲突，F1发现后已在boundary/round2保留勘误，正式政策为D4/D5/D6。

## 独立复查证据

复查者 `/root/attack_c` 未参与任何模型编写，也未写账本；读取完整V3/边界/两轮攻击/场景/实施方案，仅纸面审核。其结论：候选分支内没有新增同类技术still-open；第二轮9项closed-in-design、8项conditional-on-ruling。这不是证明实现无缺陷。

| 第二轮ID | 独立判定 | 核对规则 |
| --- | --- | --- |
| A2-1 | closed-in-design | V3-1 创建结果/对象/义务同事务 |
| A2-2 | conditional-on-ruling D6 | V3-2 未知输入完整受保护指纹/缺席拒绝 |
| A2-3 | closed-in-design | V3-3 历史BindingSnapshot及principal/key lookup |
| A2-4 | closed-in-design | V3-4 三序号域/核对专属规则 |
| A2-5 | closed-in-design | V3-5 spent Hold旧请求只读重放 |
| B2-1 | closed-in-design | V3-5 Q slot跨key一次消费 |
| B2-2 | conditional-on-ruling D4 | V3-6 既存责任的新控制收尾 |
| B2-3 | closed-in-design | V3-7 未分类role不完整义务 |
| B2-4 | conditional-on-ruling D5 | V3-8 owned移除安全scope证据门 |
| B2-5 | conditional-on-ruling D6 | V3-2 指纹前提与原生可达性限制 |
| B2-6 | closed-in-design | V3-9 async仍登记实际等待边 |
| C2-1 | conditional-on-ruling D4 | V3-6 accepted活动晚对象有收尾资格 |
| C2-2 | conditional-on-ruling D4 | V3-6 原生停止交互/显式角色恢复 |
| C2-3 | conditional-on-ruling D4 | V3-6 既存跨插件依赖缩限query |
| C2-4 | closed-in-design | V3-10 静态保内容关系退役 |
| C2-5 | conditional-on-ruling D5 | V3-8 scope未知直接阻正常退出 |
| C2-6 | closed-in-design | V3-11 decoder兼容/短pin/同环境 |

第一轮延续A1-4由V3-9 closed-in-design；A1-5/B1-6依D4，C1-1依D5，C1-4依D6。其余第一轮18项已有第二轮逐项复查明确禁止原反例。合计40项目前28设计闭合、12政策条件；没有改低严重度过门。

**F1 / medium / 文档合同冲突：** 独立报告原指D3数据迁移与收尾共用编号，可能误引批准。主会话已保持D3原意，新增D4/D5/D6，所有正式文档同步并留历史勘误；同一独立复查者已重读修订段确认F1 closed-in-document；9项设计闭合/8项政策条件及正式编号映射仍成立。原报告使用旧临时编号，以上表按当前正式编号映射，不改变原判定。

## 交审核条件逐项状态

| README §9 条件 | 状态 / 证据 |
| --- | --- |
| 1 边界/所有权/两轮实质攻击 | 已交付；inventory/boundary，V1/V2/V3，两轮23＋17项 |
| 2 无未解决阻塞矛盾、严重问题可核对处置 | 候选规则有处置/复查；12项待用户政策，**不能称冻结通过**；无实现验证 |
| 3 样例完整接入、无品牌特判/平行宿主 | 六类纸面生命周期/方案覆盖；实际I/R接入未做，原生UI缺席明示 |
| 4 原生新增能力/移除保证限制 | 明确规则与前提；D4/D5/D6待选，不无条件承诺零适配与全停 |
| 5 候选独立复查/未跑测试标明 | 独立复查及F1修正复核完成；O有限检查不当I/R |
| 6 一屏结论/指针、非绝对证明 | 本文及聊天交回；未生产实现/数据迁移/模型调用 |

## 离线核查与材料限制

- `checks/contract_checks.py` 初版21、扩版32个有限规范例exit0；当前原件 `evidence/offline-checks.json`。覆盖20项最小关系/反例＋X01–X12。没有产品import、真实SQLite/线程/杀进程、原生peer、模型或网络。
- 一些检查仅确认有限关系（S04多轮关联、S05输入bytes保留、S20共用参考请求表），不能当完整native/三入口实现验证；五崩溃切点不是实测崩溃。每条future I/R条件保留在scenarios/plan。
- 本次审计主树338＋补充29份、产品树411＋补充30份被盘点源码摘要均未变；主树tracked diff为空，见 `evidence/scope-audit.json`。覆盖被读文件，不能对未知其他写者行为作全局证明；产品树原脏改保留。
- 现有known-issues/architecture部分描述旧（如CoreRepository已经支持注入、Profile目录已现场存在）；库存以源码证据为准，规则/其他spec只读，没有自行改文档历史或复活legacy链。
- 原始受控测试/历史报告仅引用，没有沿用其计数标当前测试成功。

## 仍需以后证明或另授权

单writer/事务锁/真实崩溃窗口、native因果与scope证据、异步等待登记遵循、受保护key保护和轮换、真实卸载后历史读取、真实原生新增能力、六类实际完整接入和GUI。下轮先钉M/P合成基线、具体数据schema/旧ID映射及回滚方案，再取得实施范围；真实服务/模型/发布权限分别需要明确授权。
trusted进程内插件不等恶意代码sandbox；内部原生workflow不受Core接管；副作用不承诺外部exactly-once。无核对证据保unknown，缺保障拒绝所需请求，不能为验收改成猜测恢复。
