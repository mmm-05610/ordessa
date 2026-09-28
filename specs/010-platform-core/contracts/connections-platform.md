# C6 — Connections 平台迁移补充契约

Date: 2026-09-27 | Owner: C 前端线 | Supersedes: C4 中“Connections 契约归 connections”的旧领域归属解释

本修订经用户要求形成，只改 C 线；不改变 A/B 契约。不要求停掉当前 Workbench 阶段，先安全检查点，再接本补充。不要把现有 AgentConnections 整包复制到平台。

## 1. 现场与 source→owner

基于 main cd7d31f3cf；前端线检查时已提交 T003，Workbench API 正在修改。

| 当前代码 | 目标 | 保留/删除的语义 |
| --- | --- | --- |
| plugins/connections/service/shared/registry.ts | 复用 extension-api Contributions；connections 内仅必要包装 | 不再建第二通用注册容器 |
| service/src/entry.tsx 中通用注册/查找 | packages/desktop-platform/connections | 注册、类型匹配、连接实例、状态、关闭与作用域 |
| entry 中 AgentConnectionsToken/AgentClient 适配 | plugins/agent/connections | 旧 Agent 公开契约与领域兼容，不在平台反向 re-export |
| service/src/workspace.ts | plugins/agent/connections | selectedConnectionId、AgentSnapshot、run/approval 重连守卫、pendingReleases 与显式重试 |
| service/src/status.tsx | plugins/agent/connections | Agents UI/选择/重连/后端释放提示，仍向 Workbench 注册 |
| connectors/ordessa、connectors/acp | 原位 | 协议、鉴权、原生连接、错误解释；消费平台服务，不搬平台 |
| Agent connections 测试 | plugins/agent/connections 测试 | 领域正反例不改；通用连接测试另迁平台包 |

目标 packages/desktop-platform/connections 是前端平台包 @ordessa/connections。公共接口 @ordessa/connections/api 无副作用；实现通过内置扩展 ordessa.connections 提供 ConnectionsToken，不硬编码进 Electron，空宿主仍有效。

旧 ordessa.agent-connections ID 保持，移到 plugins/agent/connections 承接 Agent 领域 facade/UI；它不是第二套连接管理器。底层实例生命周期委托平台，领域对象/审批/后端释放只由本域维护。旧 plugins/connections/service 删除，不能留 alias。

该 Agent 兼容插件是明确的现有业务，不是新增通用层；未来新版 Chat/ACP 服务取代旧 facade 时可独立退役，本轮不提前并旧工作树。

## 2. 平台负责什么

- Connector 注册的 owner/scope、稳定 ID、展示标题、类型引用。
- 按 ID 和类型引用请求连接；每次 open 创建独立实例，不默认池化或自动选连接。
- 连接句柄状态/订阅、取消尚未完成的打开、显式关闭、所属 scope 收尾。
- 注册缺失/类型不符/作用域关闭/重复 ID 的明确拒绝。
- late resolve、打开失败、关闭失败的资源与通知处理。

平台不依赖 React、Workbench、AgentClient、ACP、Server、Harness、Profile、Pacthold。不得出现 run/approval/session/model/provider/release-remote 的分支。

不做：地址持久化、令牌读取、默认连接、自动重连、连接选择 UI、按 Agent 活跃状态拒绝重连。上述策略留领域/连接器。

## 3. 公共接口与类型边界

固定能力入口：createConnections(lifetime)、ConnectionsToken。建议类型如下；具体错误类/内部字段可按已有平台风格，但不得弱化语义：

```ts
interface Connector<T> {
  id: string;
  title: string;
  kind: ConnectionKind<T>;
  open(signal: AbortSignal): Promise<ConnectionEndpoint<T>>;
}
interface ConnectionEndpoint<T> {
  value: T;
  closeLocal(): Promise<void>;
}
interface Connections {
  forScope(owner: ResourceScope): ScopedConnectorRegistration;
  open<T>(scope: ResourceScope, id: string,
          kind: ConnectionKind<T>): Promise<ConnectionHandle<T>>;
  getSnapshot(): ConnectionsSnapshot;
  subscribe(listener: () => void): () => void;
}
```

ConnectionKind 是由公开 API 导出的单实例类型引用，运行时比身份；不可只用泛型 cast 骗过类型不符。通用 Token/kind 工具可以复用 extension-api；具体 ACP/Ordessa kind 归对应插件 API，平台不内置协议枚举。禁止把这些字段设计成整个业务 service locator。

Handle 含 instanceId、connectorId、value、getSnapshot/subscribe、close(): Promise<CloseOutcome>。close 只处理本地连接所有权，不能自行 session/cancel、删除后端资源或关闭执行。snapshot 只含中性状态与安全错误摘要，不公开令牌或连接 payload。

closeLocal 必须接低层连接释放，不可未经审计直接绑到旧 AgentClient.dispose（它可能触发后端释放）。领域 dispose 仍归插件：明确完成业务收尾后委托 handle.close。本地 transport 的关闭副作用若会触发后端取消，必须保留原领域操作守卫，不能声称其是无害的通用 close。

## 4. 与 native-bridge 的区别

native-bridge 继续只管 Electron 可信窗口/IPC/native transport 实例；connections 是 renderer 侧跨不同连接来源的注册与句柄服务，可处理浏览器 WebSocket、内存替身等，不强制经过 native-bridge。

同一物理连接只一个底层关闭回调所有者：connections handle 调 connector endpoint.closeLocal，由 connector 委托 native-bridge；业务 facade 不再另外持有同一 socket 的关闭权。不得复制 IPC 管理、重新实现协议握手、改 IPC 名称。

## 5. 生命周期与未知结果

1. 调用 open 前检查注册与 kind，且两种 scope 都必须活跃；拒绝发生在 connector.open 前。
2. 成功句柄由调用者 scope 持有。注册方卸载必须使其新打开失效，并释放本地连接句柄；这不等价于后端执行终态。
3. open 在 scope 关闭/注册卸载后才成功：返回值不得进入可用表，必须恰好一次关闭该 late endpoint；不通知已卸载 UI。
4. 同一 handle 重复/并发 close 合并同一个 pending 操作；成功才标 closed。失败返回 close_failed，不伪装已关闭；后续显式 close 可再尝试，不自动循环。
5. scope 的同步 dispose 只启动异步清理，不能声称完成。提供 whenSettled() 或等价可等待收尾报告，记录 late-open 与 close failure，不吞 Promise rejection；报告不含业务 pendingReleases。
6. 连接记录从 UI 清掉不是关闭成功证据。资源未确认关闭的记录须保留到明确结果或以不可再服务但清理失败的状态交宿主诊断。
7. 平台不自动重连/共享实例；现有领域按 connector ID 合并正在打开请求的行为可留 facade，不改变原业务体验。

## 6. Agent 与 UI 的兼容要求

旧 selectConnection 是视图选择，不关闭旧 client；原有 run/approval 重连拒绝和 backend release pending/retry 必须逐项保留。不得把它们删掉来满足核心边界。
状态 UI 仍在 Agent 领域插件中向 Workbench 注册；Workbench 仅提供位置。缺 UI 插件时平台连接服务正常。仅平台+受控非 Agent connector 可连接、订阅、关闭。
新版前端工作树不属于本批，不借修订引入它的服务实现。测试迁移保留原 ID 映射与断言；如需适配构造，报告修改理由。

## 7. 验收反例

| ID | 必须证明 | 灵敏度 |
| --- | --- | --- |
| CN-01 | 无 Agent/Workbench 的非 Agent connector 完整生命周期 | 导入 Agent 或必须启用 Workbench 时门禁红 |
| CN-02 | missing/wrong kind/closed scope 时零 open 调用 | 移除校验反例红 |
| CN-03 | open 晚到卸载后，endpoint 恰好关闭一次、不可见 | 移除 late cleanup 红 |
| CN-04 | 两个 scope 的独立句柄，一方关不影响另一方 | 默认 ID 全局单例的变异红 |
| CN-05 | 并发 close 不重复、拒绝不标 closed、显式重试有效 | 吞异常或乐观 closed 红 |
| CN-06 | native transport 关闭一次，零隐式远端 cancel/release | spy 检测重复关闭和额外远端帧 |
| CN-07 | 选择切换不停止旧运行；重连仍保留 run/approval 守卫 | 原领域测试逐 ID 保留 |
| CN-08 | Token/kind 单实例真实构建、实现未启用 API 仍可导入 | 复制 kind/Token 变异红 |

全部受控对端，不需要后端 A/B、新模型调用或真服务。未执行/资源缺席算未验证，不算通过。
