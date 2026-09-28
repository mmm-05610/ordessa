# Application：保存不等于生效，整套配置要有证明

## 1. 一条链路，明确所有权

```text
用户编辑 Profile → Profile 校验并保存新 revision
用户在会话选 Profile → Profile 记录 pending（本轮不变）

下一轮提交（消息尚未发出）
  会话所有者取得配置/发送的同一互斥准入门
    → Profile 解析候选快照（最新 revision + 逐项覆盖）
    → 提供者校验/编译全部差异，包括移除项 reset
    → Harness 预检真实运行能力、授权和隔离
    → Harness 执行并确认完整配置
    → Profile 持久化 receipt 与新绑定，成功切换则清旧覆盖
    → 原会话服务发送本轮消息
```

会话调度与原生进程管理仍各归其原所有者。Profile 不调用任意 provider 的“执行配置”再自行拼事务，不另建 agent-runtime 万能协调层；一个 Harness 适配面应拥有这一会话完整 native 配置的应用边界。

pending 是内部术语，不是 UI 标签。选择器立即呈现所选名称；选择时和输出结束时均不自动应用，只有下一次用户提交输入触发上述链路。不改变、不终止当前输出；正常成功不增加状态提示，实际失败才在发送处解释。

## 2. Harness 公开配置端口语义

```text
inspect(target) → current generation/capabilities/evidence
plan(target, desired, resetIntents, operationKey) →
  live-update | restart-resume | blocked (per-item reason)
apply(plan, fence) → confirmed receipt | rejected-unchanged | unknown
reconcile(operationKey, target) → confirmed-current | rejected-unchanged | unknown
```

这不是本轮宣称已有 API；落地需复用现存 Harness 生命周期/配置公共契约，不按此示意重造已有端口。计划包含目标会话/进程 generation、原配置指纹、操作 key、字段来源、权限判定与 reset 能力，服务端重新验证，客户端不能提供可信 fence。

原生 API 回执可作为证据的一部分，进程启动参数/配置清单可作另一部分；必须按 adapter 实际语义定义证据级别。仅请求已发送、退出码 0、DB readback 或 UI 选项改变不足以证明整套生效。未知能力不提升成 live-update。

## 3. 不假装跨进程数据库事务

外部配置操作不能与 SQLite 作真正原子事务。本方案保证的是：**没有被证明完整应用的配置，不会启动新一轮，也不会显示成功。**

- 所有项先 plan/validate，任何 unsupported 都零原生写入。
- 能原子更新则使用原生原子接口；需多步时记录操作 journal，锁住发送。
- 某步失败：适配器能证明已回完整旧配置，则 rejected-unchanged；不能证明则 unknown/needsRecovery。不得只因尝试了补偿就报回滚成功。
- 外部 confirmed、本地提交失败：仍 unknown，凭 operationKey 查证后补落确认，不重复应用/重复发消息。
- 成功配置应用但随后消息被拒：配置可已生效，草稿仍保留。UI 分开报告“配置已应用 / 消息未接受”，不把两者包装成一个虚假事务。
- 配置待应用但恢复前用户关闭页面：操作状态不归 UI lifetime，不能丢 journal；只清页面订阅。

## 4. A 的残留和目标默认

B 未设置的字段必须明确回到目标默认，而非残留 A：提供者针对移除字段产生 reset intent，Harness 用可核实的目标默认或原生恢复默认接口执行。baseline 是该目标的原生默认配置事实及版本，不是事后读取一个可能已污染的进程值。

如果不能知道如何 reset，拒绝该切换并指出字段；不能通过“B 空值就不写”假装完成。配置恢复默认与会话覆盖恢复跟随是不同操作：前者 native 目标，后者 Profile 当前值。

## 5. 多会话、原生配置与恢复

- 不全局覆盖用户配置目录。优先原生 session 参数；必要时使用 Harness 原生支持的进程专属 env/配置路径/参数，具体能力由 adapter 验证。
- 若一个 runtime/process 共享多个会话且配置作用于整个进程，必须先证明不会影响旁边会话；无隔离手段时该切换 blocked。不能臆定“一进程一定一会话”或“配置只在启动读一次”。
- restart-resume 恢复同一个用户会话/历史，但新的 runtime generation；旧 execution 如果已终结不得复活，新 execution 由原有运行所有者建立并关联 conversation。Profile 不把 executionId 当 sessionId，不为每个消息自动造执行。
- 某些 instruction/Skill 注入无法在已有上下文撤销；UI 不能伪称旧上下文被抹去。适配器需说明 live/resume 限制，不满足本轮目标时拒绝，用户自行决定是否开新会话，不能自动另开替代。

## 6. Policy 和安全

允许工具暴露给模型、允许该工具执行、是否需审批、操作系统隔离、Profile 编辑权限是五个不同事实。UI 分别表达，不做一个“全权限”假开关。

Profile 权限声明只能在平台授权上限之内；实际执行仍由 Harness/运行审批层裁决，选 Profile 不提供新的授权。减少权限的配置不会强行中断已经在执行的工具；紧急撤权走已有停止/安全能力，不由“下轮配置”冒充。

Provider 卸载/禁用若有未结束应用必须遵守宿主 busy/deferred 清理：不在运行中途移除正在用的实现；下一轮重验 generation。缺所需 provider 则阻该目标，其余 Profile 和原生无 Profile 路径正常。

## 7. 证据而非无限日志

配置事实记一次 change/operation receipt，每轮只关联实际 configReceiptId/修订，不把所有对话正文写进 Profile。Pacthold 仅按其现有 execution/resource 事件记录治理事实，Profile 不建第二执行状态库。结束的 execution 不可恢复，但配置引用和会话选择可持久存在。
