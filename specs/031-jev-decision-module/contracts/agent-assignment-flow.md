# 默认业务流程 · agent.assignment/1

## 与通用运行器的关系
这是首版参考业务流程，不是runtime固化规则。调用方显式选择flow和policy；
替换判断顺序/模块不修改通用引擎。节点使用M02入口包装，业务图原生构建，不自写调度loop。

## 节点及路由
| 节点 | 输入/职责 | 下一步 |
| --- | --- | --- |
| CheckPolicy | flow/policy/settings/limits匹配与有效性 | invalid→技术failed；有效→HardTaskGate |
| HardTaskGate | 结构允许不完整任务，判断确定缺字段/冲突 | 缺口→FinishBusiness；不能确定→AssessTask |
| AssessTask | 按policy六维问题调用受控gateway | 有效答案→ReduceTaskGate；协议故障→技术failed |
| ReduceTaskGate | 确定性归并缺陷/解释模板 | gate_pass→DelegationGate；其他→FinishBusiness |
| DelegationGate | 是否需要外部工作单元 | 明确不需→NoDelegationProposal；需/未知→ReadFacts |
| ReadFacts | 当前上下文/节点/描述/Profile/可用性安全观测 | 端口失败→failed；事实缺口→clarify；完整→ReadCandidates |
| ReadCandidates | 有界候选分页/完整性；外部目录与提案来源 | 候选与依据→HardFilter |
| HardFilter | identity/version/硬约束/必需义务检查 | 无可行→具名缺口/blocked；单可行→ComposeProposal；多可行→Rank |
| Rank | 在允许动作域内选择候选，保留拒绝槽 | 合法ID→ComposeProposal；拒绝→clarify/blocked |
| ComposeProposal | 从候选映射或注入ProposalSource取完整payload | 有方案→ValidateProposal；无知识→clarify/blocked |
| ValidateProposal | requiredValidationObligations逐项只读核查 | valid且覆盖→FinishReady；可修正invalid→Repair；未知→clarify |
| Repair | 将具名反馈给组合器，比较新依据/方案/反馈摘要 | 有进展且限额内→HardFilter；无进展→clarify/blocked |
| FinishReady | 形成完整提案/RunManifest/回执/前置并提交单终态 | 返回completed/ready |
| FinishBusiness | 形成revise/clarify/blocked并提交单终态 | 无实例/配置/输入效果 |

表中的业务分支不吞异常/预算/取消；它们归runtime技术终态。
NoDelegationProposal仍进行提案结构/义务覆盖校验，不需要外部核心能力；
可在本地纯规则validator通过noDelegation义务，不伪造owner检查。

## 默认任务策略
版本化维度：goal_specificity、scope_consistency、acceptance_observability、
deliverable_cohesion、delegation_form、risk_boundary。
每维有限Choice答案pass/fail/unknown，分别有政策描述，不是只发“pass还是fail”：
- goal：是否有明确单一主要结果，不补用户意图。
- scope：目标对象/排除项/禁止项是否相容；风险事实必须由来源支持。
- acceptance：现有验收是否可观察，不要求模型编造新指标。
- cohesion：多步骤是否服务共同结果，还是多个独立交付。
- delegation_form：是否能形成有限工作约定，或应先由主Agent澄清/回答。
- risk：所需效果边界是否已明确，不把模型评估当用户授权。

HardTaskGate能确定的缺项零调用。默认必需维度pass才gate_pass；
unknown按事实所有者返回clarify；fail按已明确意图/约束区分revise与fatalBusinessBlock。
默认Score/Noul不作为必需门，仅在另版policy定义量表/含义后启用；
不靠confidence阈值把缺事实转pass。M03仍完整支持三种问题，以便替代业务流程使用。
问题instructions由可信模板生成，任务与第三方描述放state，规则与数据分离；
模型选择不能删must、改变策略或加授权。

## 默认选择策略
先检查任务明确要求必须委派或保持同原生上下文；否则可返回noDelegation。
每个动作先检查M05硬条件。默认动作优先级：
continue > reuse > restore > wait > reconfigure > create，
但wait必须有可验证等待期限；已知不满足用户时延要求则排除。
同优先级多个候选让Jev按任务适配/上下文保留/有依据的代价判断；
费用未知不当0，是否允许选不确定估计由policy明确。
默认不宣称全局最优。要求系统性证明没有可用实例才create时，
完整目录/可比较约束是must；不完整目录只给不完整证据，不默选择create。
等概率/none_suitable/insufficient_evidence按具名policy分支返回缺口，不能默认第一项。
noDelegation和wait也是建议，不自动继续执行主Agent任务或安排自动唤醒。

## 配置组合和变化
参考composition不理解任意schema的全部语义；调用外部注册模板/选项处理器。
配置kind、schema版本、资源ref和合法payload来自提供者；能验证候选即可纳入。
同一完整方案的digest变化才成为新方案；改变排序/显示名不是新语义。
变化任一task/policy/descriptor/profile/resource/node/config版本都必须重建对应依据，
不能只换字符串版本后复用旧回执。
叶子处理器可能懂某家Harness，这是合法业务知识；runtime/gateway不懂品牌。

## 可直接验收的两条踪迹
A：明确只读审查任务→已有节点只读/空闲/同上下文证据→continue候选→验证
→ready提案；所有prepare/apply/输入调用为0。
B：任务完整→两个方案不适合→外部组合器给新kind且小数payload→Jev选择ID
→owner校验义务覆盖→ready create提案；真实准备仍未发生。
若B缺owner纯读评估则返回具名缺口，不启动实例填证据。

## 关键区别
多轮判断不等于多次执行任务；流程节点不等于Agent实例；
配置候选不等于已保存Profile；判断完成不等于外部工作完成。

