# 验收矩阵

所有条目初始NOT_RUN。离线指真实候选库/SDK加假网络或受控公开服务，不代表真实Jev质量或Harness闭环。
主执行者记录每场景命令、环境、完整SHA、退出码、计数、证据路径、费用/授权和清理；套件总绿不得填未跑项。

| ID | Owner | 场景 | 断言与反例 | 缺席或未知行为 |
| --- | --- | --- | --- | --- |
| T01 | M01 | 有限JSON与深冻结 | 合法任务含空验收可编码；NaN、非字符串键、可执行对象、嵌套修改拒绝 | 源码/codec缺席→失败 |
| T02 | M01 | 身份与规范摘要 | 跨namespace同id不合并；键序规范向量一致；不拿名称为key | 来源引用不完整→拒绝 |
| T03 | M02 | 真实图多轮 | 真实pydantic-graph运行三轮反馈；不自建while；无反馈不重复 | 真实库缺席→未验证，不用fake图替代 |
| T04 | M02 | 独立业务流程 | 两套流程顺序不同，runner原封不动 | 备用流程缺席→失败 |
| T05 | M02 | 节点数预算 | 受控入口达上限结束，不计上游内部边数、不无限循环 | 预算配置缺席→发前失败 |
| T06 | M02 | 并发attempt排他 | 剩一票两协程最多一HTTP；取消/过期排队不派发 | 计数不可核对→失败 |
| T07 | M01 | 排他终态 | completed才能有业务结果；failed+ready或未验证draft拒绝 | 终态schema缺席→失败 |
| T08 | M01 | 提案与回执 | valid绑定确切proposalDigest；改payload后旧receipt拒绝 | validator缺席→unverifiable，不ready |
| T09 | M01 | 动态配置 | 陌生kind经外部描述可使用；required无validator不ready | schema/dialect未知→unverifiable |
| T10 | M01 | 读取完整性 | 权限过滤/截断空列表不证明无候选 | 完整性声明缺席→unknown |
| T11 | M02 | 协程取消 | 外部取消传播；有界shield清理；一个run取消不关闭共享client | cleanup无法确认→unknown |
| T12 | M02 | 超时非硬杀 | 协作async停止后续节点；阻塞/吞取消节点标不支持 | 没有取消证据→不承诺已停止 |
| T13 | M02 | 异常路由 | 未知边/回答、节点异常技术failed，不fallback成功 | 输出未知→失败 |
| T14 | M02 | 预算与业务分离 | 耗尽不包装blocked/clarify/ready，不返回半成品 | budget字段缺席→失败 |
| T15 | M02 | 并发run隔离 | 两个run输入/候选/计数/证据序号不同且无串用 | 隔离测试缺席→未验证 |
| T16 | M02 | 可信图边界 | 未审查代码/任务指定module拒绝；已审查节点不绕gateway | 审查记录缺席→拒绝加载 |
| T17 | M01 | 授权不来自正文 | principal/allowWrite/lease字段不授予权利 | readContext缺席→refused |
| T18 | M01 | 版本未知 | sourceRevision=null不被digest/时间冒充CAS | 不可比revision→unverifiable |
| T19 | M02 | 无私有上游API | 导入守卫抓到植入_GraphIterator/private引用，正常公开接口通过 | 扫描路径缺席→失败 |
| T20 | M02 | 同步循环边界 | 已运行loop中执行async接口，不run_sync/asyncio.run嵌套 | async场景未跑→未验证 |
| T21 | M06 | started持久ACK | started写失败零模型；memory sink real模式拒绝 | 持久保证未知→发前拒绝 |
| T22 | M06 | call.intent发前 | intent ACK失败零HTTP；ACK后HTTP前kill仅unknown，不自动重发 | 日志损坏→unknown/失败 |
| T23 | M02 | 许可单次消费 | 重复/cross-run/digest变更/过期permit零HTTP | permit无权威→发前拒绝 |
| T24 | M02 | 完成取消竞态 | 完成commit前后取消分别验证；已completed不覆盖cancelled | commit ACK未知→查询，不改终态 |
| T25 | M02 | 终态幂等 | 同digest重复finish同ACK；不同digest拒绝；丢ACK后核实 | 无法核实→unknown |
| T26 | M06 | 响应后日志故障 | HTTP已返回而response/terminal写失败，不ready、不重发 | 证据缺席→未知 |
| T27 | M06 | 真实kill中断 | 独占writer、子进程kill后查询interrupted；活writer不误判 | 失活/锁无法证明→unknown |
| T28 | M02 | 有界清理 | sink永不返回也不能无限shield；保留原取消及secondary error | 清理未确认→unknown |
| T29 | M02 | 只读并行汇合 | 分支返回immutable值；不共同改state；两run无污染 | 写共享state流程→拒绝接纳 |
| T30 | M02 | 兼容构图检查 | 真实库非法图拒绝，结构校验未关闭，显式graph名称 | API不支持→PARTIAL |
| T31 | M06 | 安全证据 | 恶意正文/secret/header/异常不入记录；路径穿越/symlink拒绝 | 脱敏策略缺席→不启真实模式 |
| T32 | M06 | 日志损坏与读取 | 截断/序号断裂拒绝成功；not_found/refused/unavailable区分 | 损坏→unknown，不读末行装成功 |
| T33 | M03 | 三种问题映射 | 真实SDK+fake transport；Choice/Score/Noul答复准确关联 | SDK未安装→未验证 |
| T34 | M03 | Score/Noul语义 | Score1.7不转整数；Noul无fake confidence；confidence非授权 | 字段含义未知→拒绝映射 |
| T35 | M03 | 答案集合 | 缺/多/未知类型、闭集外ID、错候选snapshot失败 | SDK丢答案后缺项仍失败 |
| T36 | M03 | 数值与模型 | NaN/概率键/和/期望不符拒绝；固定模型错版本拒绝 | 协议版本未知→失败 |
| T37 | M03 | 隐藏重试 | 429/5xx/连接错误各最多一次HTTP；SDK retries=0 | 请求计数不可见→未验证 |
| T38 | M03 | SDK取消与截止 | 在途取消不吞；超deadline零HTTP；费用unknown | 远端处理未知→不返还尝试 |
| T39 | M03 | 客户端归属 | 专用client只关闭一次；共享provider一个run取消不关其他run | 归属不清→构造拒绝 |
| T40 | M03 | 端点与凭据 | 任务不能指定base_url/extra_body；key不入repr/log/body采集 | secret resolver缺席→真实模式拒绝 |
| T41 | M03 | 规则/数据隔离 | 注入文本不能改硬约束/调用工具；离线不宣称模型抗攻击 | 实际模型未测→质量未验证 |
| T42 | M03 | 问题规模 | Choice0/1由代码处理；越上限发前拒绝；Score1/11级拒绝 | rubric无定义→policy_invalid |
| T43 | M04 | 任务缺口 | 无目标/验收零模型，clarify；已知用户目标被漏写revise | 事实不足→不编造 |
| T44 | M04 | 颗粒度 | 多步骤单交付通过；多个独立目标不通过且不派生执行 | 任务类型policy缺席→failed |
| T45 | M04 | 策略变更 | 更换外部rubric改变判断，runner不改；错阈值技术failed | policy缺席/不支持→技术失败 |
| T46 | M04 | 风险与权限 | 模型判低风险不能覆盖用户未确认写/费用边界 | 授权事实缺席→clarify，不授权 |
| T47 | M04 | 缺陷解释 | 代码/证据选项+可信模板；非法代码/敏感模板参数拒绝 | 模板/代码catalog缺席→failed |
| T48 | M04 | 无进展 | 相同签名不重复刷pass；相关新版本允许新判断；无全局免费缓存 | 旧证据不可信→不复用 |
| T49 | M05 | 七路径 | 每个动作可构造合法提案；noDelegation零候选/模型 | 必需前置未知→不ready |
| T50 | M05 | 硬约束压过评分 | 高分候选硬fail/unknown不能选；低成本unknown不填0 | 硬检查缺席→拒绝候选 |
| T51 | M05 | 原生上下文 | 同上下文要求不能选择别session；restore仅提案 | 连续性未知→不continue |
| T52 | M05 | wait与重配 | busy共享节点重配拒绝；wait不轮询/预约；模式明确 | 占用/模式未知→具名缺口 |
| T53 | M05 | 组合有界 | 新kind不改引擎；只读外部组合器；到上限非全局最优 | 组合目录缺失→不生成猜测JSON |
| T54 | M05 | 反馈收敛 | 新反馈产生新候选；重复摘要结束；Noul非自动none | 反馈无可修正项→不重复问 |
| T55 | M06 | 公开服务映射 | 真实AgentServices/DTO只读调用；private访问守卫反例命中 | 公开接缝缺席→PARTIAL |
| T56 | M06 | preview不足 | 实际unresolved忠实保留；providers支持声明非安装；node发布非可用 | 安装/可用未知→不能声明ready unit |
| T57 | M06 | 创建前只读接缝 | 纯读offer/assessment经原owner路由；mutation/file/process计数0 | owner不支持→unverifiable |
| T58 | M05 | 提案后漂移 | 旧descriptor/profile/node/task/config版本拒绝；checker全列 | checker未知→拒绝应用交接 |
| T59 | M06 | 产品离线交付 | 无Ordessa/Jev凭据运行offline+alternate；CLI无apply/module入口 | 缺可选依赖→只读模式显式错误 |
| T60 | M03 | 真实Jev质量 | 另授权中文rubric、顺序偏差、注入、成本/延迟评测 | 无授权/key→NOT_RUN，非成功 |
| T61 | M06 | 真实核心纵向只读 | 临时Environment+真实公开服务+fake provider贯穿；无用户服务启停 | 真实服务未跑→coreReadOnly未验证 |
| T62 | M06 | 原生效果零调用 | 全流程prepare/apply/start/recover/acquire/connect/dispatch均0 | spy无法观察→失败 |
| T63 | M06 | 包安装与边界 | wheel独立导入、optional extras隔离；Pacthold不反依赖decision | 包缺失/收集错误→失败 |
| T64 | M06 | 基线与继承红 | 回归按ID/原因比对；不删assert/skip/legacy compat填绿 | 基线未知→先记录，不报全绿 |
| T65 | M01 | 校验义务覆盖 | 结构valid但required配置unsupported不ready；缺obligation/无依据notApplicable失败 | 覆盖不明→unverifiable |
| T66 | M01 | 策略与摘要绑定 | 同flow不同policy结果可区分；跨kind/namespace摘要域不撞；旧policy回执不复用 | policy/digest域未知→失败 |
| T67 | M05 | 动态小数配置 | 新kind含0.7及schema minimum0.1经组合→选择→owner校验，不改引擎 | codec拒绝合法数→失败 |
| T68 | M03 | 拒绝选项容量 | 64业务候选+2拒绝槽均保留；选择拒绝ID不取payload | 拒绝槽被截断→失败 |

## 层级与结束条件
L0 materialsValidated：本文编号、依赖、链接和反例完整；不是产品执行。
L1 offlineVerified：T01–T54/T59/T63/T65–T68真实离线运行；缺候选库不能用fake执行器填绿。
L2 coreReadOnlyVerified：T55–T58/T61/T62/T64真实临时核心与公开接缝运行，无模型和用户服务修改。
L3 liveJevValidated：T60另获授权后真实领域质量评测；阈值/样本/成本预先记录，失败不自动降低阈值。
上述层级分别记录，部分支持动作不等于七动作全部产品可用。
真实Harness配置应用不在本轮，不能把ready提案当原生已生效。

## 真实模型评测计划（未授权）
样本至少覆盖清楚/模糊/独立多目标/单结果多步骤/授权不明/无单元/多候选/新配置描述/注入文本。
人工标签和规则版本先固定；测重复与选项顺序、中文问题、错误选择和不确定分支。
先dry-run输出请求规模及报价依据；用户明确模型ID、样本数、最大attempt与可接受费用后才执行。
如无法给可靠货币上限则解释按调用上限控制的不足，重新求授权；不默认无限使用余额。
