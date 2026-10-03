# 跨侧提交合同 C1：Q01–Q12联合收口

请求跨模式身份、跨库持久握手、附件冻结、效果fence与key墓碑强制补充见 recovery.md，不得省略。

本合同用能力检测表达保证，不要求所有原生Harness提供同级原子性。

| Q | 联合最低合同 | 反例与缺席处理 |
| --- | --- | --- |
| Q01 | logical target/native binding/owner instance+generation/realm可信映射 | 同nativeId不同owner不合并；未证实旧关系只读 |
| Q02 | known/unset/unknown字段、来源mask、可比较revision或明确不可比较 | 缺完整基底不伪current；只lastObserved |
| Q03 | present/unset补丁、模型原子字段组解析由领域公开接口 | 解析缺席操作unsupported，不通过Profileglue兜底 |
| Q04 | capture+提交关联、condition/version或原生可验证边界 | 无原子保证保raw能力，拒请求“可靠配置+输入” |
| Q05 | configApply与inputAcceptance分开，partial逐字段 | 已应用model+发送拒不谎称整体回滚 |
| Q06 | stable request/creationAttempt查询，重复ID一致性检查 | accept后断线unknown→查询，不自动create/apply/prompt |
| Q07 | native自主变化来源/版本事件或可核对快照 | gap/stale/conflict阻可靠capture；重复原观察不解锁 |
| Q08 | 首次creation意图/新native证据/输入关联 | 有明确create-with-config能力才可靠首次发送，否则raw按原生合同 |
| Q09 | 原生命令/未知事件通道与预算 | 不Core命令白名单，不将未知payload当审批 |
| Q10 | control来源/version/回答资格/单消费slot | 假approvalId只可显示未验证，不能回答 |
| Q11 | cursor/gap/credit/完整快照 | 溢出明确gap，不能尾部假完整 |
| Q12 | owner退出预检、unknown恢复继续者、合法closure | UI可撤，未知责任owner不可无证销毁 |

## 两条明确路径

raw-native：用户显式使用普通原生交互，稳定requestId关联本次发送，不自动retry；只报告可观测回执。无durable/fingerprint时标明不可承诺重启一致核对，不宣称配置事务或外部exactly-once。不能拿raw路径偷发可靠请求。

reliable-submission：冻结draft revision/text/attachments/config opIds/base/source revision/target/binding/保证等级；持久标记与指纹校验先于投递；具备Harness声明的必要关联/条件能力才调用。实际应用、输入接纳、运行结果三个事实分开。无原生支持可typed unsupported，不上层轮询/重复apply伪造原子性。

选择操作在点击时定序；异步目录/解析回调按原seq归位；同Profile重选新opId；输出过程中只修改意图。发送成功仅消费捕获draft revision，晚编辑不清。已reserved操作归旧binding，不因selected切换重路由。可恢复unknown有可靠持久关联；无能力明确不支持，不假造核对结果。
