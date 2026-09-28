# Data model and state transitions

## 实体与所有权

| 实体 | 所有者 | 内容与约束 |
| --- | --- | --- |
| Profile / SessionOverride | Profile | 业务 fragment 与来源修订；不存运行进程 |
| Provider/Skill/content | 对应业务插件 | 内容、供应商和认证引用；Harness 不复制成第二业务库 |
| RuntimeAdapterDescriptor | Harness registry | 品牌、版本、目标/action schema、贡献 owner/generation |
| ConfigurationAdapterDescriptor | Harness registry | facet×品牌×版本映射、claims、纯编译/验证 |
| RuntimeInstance | Harness | 唯一实例 ID、native 会话映射、generation、受管配置根、租约引用 |
| ApplicationPlan | Harness | desired 摘要、before 修订、effects、校验依据、有效期；无秘密明文 |
| ApplicationOperation | Harness | 幂等键摘要、阶段、确认/未知事实、补偿/恢复记录 |
| ConfigSnapshot | Harness | 不可变配置产物 manifest、内容摘要、来源 owner，秘密只存引用 |
| Execution/Lease | Pacthold | 原有权威 ID、资源与生命周期；其他表只引用不复制权威状态 |
| SubmissionRecord | 既有会话服务 | submission_id、配置 operation、输入摘要、发送/结果状态 |

RuntimeInstance 不等于进程也不等于可恢复会话。支持多会话的原生进程必须声明共享影响范围；没有可靠 session-local API 时不同配置要求隔离实例，不能因为 ACP sessionId 不同就认定隔离。

## 配置修订与有效值

Profile 提供 `latest profile fragments ⊕ session item overrides`；Harness 只消费解析后的结果。来源修订用于 CAS 与审计，不让 Harness 重新计算覆盖。Profile 切换成功后清除旧 override；失败/unknown 不清。新 Profile 未提供而旧配置设置过的项必须显式 reset 到已验证基线。

基线是当前实例创建时获准的配置快照或确定的原生默认，不能重新读取随时变化的用户全局文件充当默认。原生项目文件若影响生效结果，须列入输入摘要与信任策略；无法控制的覆盖冲突拒绝或报告不可确认，不假装私有根拥有全部优先级。

## 操作状态机

```text
planned -> applying -> verifying -> confirmed
    |          |           |
    v          +-----------+----> unknown -> reconcile -> confirmed/refused/unknown
 refused
```

refused 表示拒绝已确定；已经产生无法补偿的部分效果只能 unknown，或明确报告已确认回到 before 后再 refused。阶段可细记 materialized/restarted/resumed；不能凭最后进程退出码判断完整事务结果。

1. 在副作用前写 operation 和 before/desired manifests。
2. 每个外部步骤记录 operation_key、generation、资源归属和可核验结果。
3. 外部成功但回执/DB 写入失败：恢复读取日志并观测，不能重新执行“可能已成功”的动作。
4. Profile 回执入库失败：配置结果仍可查询；阻止 prompt，通过同一 operation 补齐提交状态。不谎称外部配置回滚。
5. prompt 发送失败/unknown 与 config confirmed 分开；重试配置不意味着重试消息。

跨 Profile DB、Harness journal、原生进程没有 ACID 事务。本设计用持久化操作、幂等、确认和补偿处理，不声称双库原子提交。

## execution 与资源

新通道的资源 acquisition 沿 Pacthold 的受管执行图进行，借用资源不由 Harness 释放。ACP ChannelRef 是资源引用，不为“会说 ACP”另造 ExecutionProvider。

配置热切换不产生新 execution。原生进程更换是否终结 execution 取决于现有 execution 的实际边界：若旧 execution 已终态，必须新建 execution 并关联同一可恢复 conversation；终态 execution ID 不可复活。业务会话身份与 execution ID 不互相充当主键。

## 持久化与保密

新增日志放插件自有版本化存储，路径经产品的数据根服务提供；不改已有 Server 数据根标识或 core.sqlite schema。schema 升级有备份/校验/故障注入，用户数据迁移按 migration.md 审批。

secret_ref 解析在后端最后一刻发生，日志、plan hash 输入、异常、前端通知不含秘密值；hash 也不以低熵秘密明文作为可枚举摘要。原生必须用秘密文件时限制权限和寿命，退出清理失败保留事实，不记录内容。关闭日志时不得丢弃未解决操作。
