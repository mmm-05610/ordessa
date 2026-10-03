# E2/F2 生命周期、证据与领域别名（强制补充）

002冻结合同；003/004/005/007/008/009/010实现，验收对应A55–A61。这些规则不是重新管理native业务。

## 未知交付角色与scope义务

envelope将deliveryRole与业务type分开。已知observation角色的未知业务type可有界raw展示；未知deliveryRole可能携带需回答/保存/释放的责任，不可只当普通文本丢弃。

Environment登记UnclassifiedDeliveryFact（完整来源/对象/序号/关联）和最小ScopeObligation。分类或可信范围证据不足，owned scope completeness=unknown，旧idle不能解除。超预算合并为scope-unknown摘要与gap，不丢义务，不自行猜审批。可信owner补分类/足够范围停止证据才能收口；borrowed只核对本方责任。

## 三种序号与RecoveryBinding

每条事实分source/nativeRevision、ingestSequence、environmentKnowledgeRevision。native/source序号只同可信源incarnation可比较；ingest只是收集顺序；knowledge是环境接受知识的版本，不把新observer数字当native因果。

RecoveryBinding明确原环境BindingSnapshot与新observer的read-evidence scope、原生authority/owner/instance/nativeGeneration、授权principal、证据类型及连续性。PID/path/version相同不足证明同native身份。新observer“not found”无完整范围证据不得覆盖旧unknown或解除Usage。原Receipt不可改，冲突保disputed，只有满足恢复合同的新证据可修知识。

## 前端停用原子门

前端runtime在preflight开始，用同admission fence冻结该owner的新dispatch、required借用和依赖batch publish；记录dependencyRevision与已commit工作集合后决定drain。跨await不允许在“已判无未决”后插入新的必需关系。新贡献批次取用该owner也参与同门。

preflight拒/超时：明确恢复准入与原贡献，不能半撤UI但仍允许新操作。通过后保既有工作继续者与settlement，随后revoke；旧gen回调不可撤新scope。A09后端cut证据不能代替此门。

## 稳定native别名

Agent域维护可信alias：native authority namespace + owner identity + nativeSessionId + nativeGeneration 至多一个可写logical authority。socketId/临时clientId不属于稳定实体身份，第二连接无法核对只读unverified。

多窗口/多连接通过stable connection configuration身份与可信native映射重新附着同owner；不同realm/用户/真正不同native实例可以不同target，不能凭换socket或schema名字绕旧unknown。serverInstance变化后旧unknown仍历史可核对，不自动取得新invoke权。

## connector剩余状态迁移表

| 旧状态 | 唯一目标 | connector可保什么 |
| --- | --- | --- |
| routes/buckets与帧缓存 | 传输适配本地关联 | route/cursor/有界frame聚合，不判业务终态 |
| sessionList/native alias | SessionOwner | 来自native的来源证据和只读projection |
| runs / finishTurn / accept结果 | Run/SubmissionOwner | 回执解码，不单独解锁发送 |
| interactions | InteractionOwner及可信control来源 | 解码事件/response映射，不输出伪审批 |
| firstSends / pendingControlledSessions | SubmissionOwner/creationAttempt | request→op关联，不独立恢复创建 |
| Agent sessions model draft请求 | Session/Draft/SubmissionOwner | UIselected只投影，命令冻结target |

恢复或重建client不能清掉domain unknown；late success只经owner校验证据。所有控件由owner读资格，不读旧client独立busy/current。007/010分别核对native关联与前端状态，不能只迁Profile/model。

## SDK真实穿透与样例

未知payload摘要必须穿native peer→Harness→Server→实际Desktop connector/SDK→surface出口，不能绕SDK直接feed新fixture。原协议解码会丢未知type时，在破坏性过滤前保通用出口，避免重复投递已知事件。

外部样例三份独立构建：第四种controlled Agent（不三品牌固定值，异协议/schema，可靠可声明unsupported）、静态资源包（不装Server/Harness/Profile）、非Chat terminal/document扩展。各有独立最小manifest、安装/构建产物、公共接入与退出记录；禁止仅写在Harness测试内部冒充外部插件。

