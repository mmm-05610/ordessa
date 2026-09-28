# Feature Specification: 平台核心收敛

Feature Branch: codex/010-platform-plan；实施分支见 plan.md
Created: 2026-09-27
Status: Ready for scoped implementation；集成待审
Input: 稳定 Pacthold、Server、前端平台，领域债务外移插件，多个 Qoder 并行实施。

## User Scenarios & Testing

### User Story 1 — 作者仅实现自身资源与运行 (Priority: P1)

价值：执行插件不再管理其他资源插件。
Independent Test: 仅核心、两个受控资源和一个执行 provider，无 Server/Harness/网络。

1. Given A 获取成功、B 拒绝，When 启动，Then 不运行、仅回收本轮自有 A，不销毁借用对象。
2. Given 外部已启动但回执丢失，When 同键重发，Then 不二次启动、不释放可能仍在使用的资源，unknown 可查询。
3. Given 终结执行对应可恢复 Session，When resume，Then 新 Execution ID，原记录不改。

### User Story 2 — 后端插件注册即可接入 (Priority: P1)

价值：新增领域无需 Server 新业务分支。
Independent Test: 裸 Server 加受控插件，注册、请求、卸载、重激活，无业务发行版。

1. Given Core/wire 贡献冲突，When 激活，Then 两边零泄漏，欠账 disposal 恰一次。
2. Given 同一个 App 卸载插件，When 请求旧路由，Then 404；重激活用新实例，鉴权/签名变化被拒。
3. Given 活跃/unknown 租约，When 卸载 provider，Then busy，既有运行不被销毁。

### User Story 3 — 界面平台独立于业务 (Priority: P1)

价值：稳定前端平台，不重写宿主。
Independent Test: 空 Desktop、仅 Workbench、Workbench+受控贡献者三个组合。

1. Given 无 Chat，When 加载 Workbench，Then 布局有效，无 Agent 必需依赖。
2. Given 独立构建的两个扩展，When 提供/消费同一 Token，Then 可连接；复制 Token 的变异构建被捕获。
3. Given 视图/模态/设置贡献，When 卸载，Then 全撤销，焦点与 handle 如实。

### User Story 4 — 既有产品继续工作 (Priority: P1)

价值：防止只交付空壳。
Independent Test: 临时旧数据夹具、默认产品和受控 peer 回环，不碰用户目录。

1. Given 相同输入，When 对比基线和新树，Then 持久标识与业务结果一致，差异逐项说明。
2. Given 业务解析器未安装，When 读历史，Then 保留中性记录、明确缺提供者，不偷偷导入业务。
3. Given 测试搬家，When 验证，Then 原测试有去向且每套件实际运行。

### Edge Cases

两个数据根、旧运行句柄、借用/共享、取消未确认、卸载竞态、启动/清理双异常、预挂载和 lifespan 间变化、空清单、旧迁移记录、构建重复 Token。

## Requirements

### Functional Requirements

- FR-001: 核心 MUST 实例化，两个 Store 启停不互扰。
- FR-002: 资源 MUST 声明类型/依赖/值或租约/自有或借用；运行只消费声明输入。
- FR-003: 副作用 MUST 有持久意图、稳定幂等键与可查询结果。
- FR-004: unknown MUST 禁止自动重试和不安全释放；Execution 终态不可改写。
- FR-005: Core/wire/route/service 贡献 MUST 整批验证发布，失败全撤销。
- FR-006: Server MUST 无业务门面/专用停机/领域发现规则，原协议由插件贡献保持。
- FR-007: 活跃资源 MUST 阻止卸载；清理保留主异常及所有安全清理结果。
- FR-008: Workbench MUST 成为平台包，仍经现有宿主加载；空宿主有效。
- FR-009: 公共契约 MUST 归所有者，不启动实现；Token 单实例。
- FR-010: 业务代码/单测 MUST 不留 apps/platform；跨包集成可留产品。
- FR-011: 持久 ID/协议 MUST 保持；历史 SQL 原字节保全，不操作真实用户数据。
- FR-012: 验证 MUST 含缺席/失败/恢复/反例，继承红逐 ID/原因比对。
- FR-013: 本轮 MUST 不改其他树，不增加模型/服务/发布权限。
- FR-014: UI 卸载、通道关闭、执行停止 MUST 不隐式互推。
- FR-015: 通用 Connections MUST 属于前端平台且独立于 Agent/Workbench；协议 Connector、领域重连策略和连接 UI 留插件。迁移必须保持原运行/审批保护和远端释放可见性。

### C7 approved amendment — UI component consumption

- FR-016: 前端平台 MUST 提供领域无关的可替换 UI 机制，覆盖显式产品选择、作用域批量注册、只读消费绑定、卸载/重激活、逐位置错误边界和旧动作失效；契约为 contracts/ui-components-platform.md。不得内置 Agent 组件或扩大 A/B 改动。
- 本轮增量验收为 U01–U16 和 T030–T036；12 个领域组件只作为后续使用场景，未列为本次实现。

### Key Entities

CoreRuntime、Work、Execution、ExecutionPlan、ResourceRequirement、Lease、Operation、ContributionBatch、ServiceRef、UI Contribution，详见 data-model.md。

## Success Criteria

- SC-001: 新受控资源/执行插件接入时核心源码修改数为 0。
- SC-002: 新受控服务插件接入时 Server 源码修改数为 0。
- SC-003: 新受控 UI 插件接入时 Desktop/Host/Workbench 源码修改数为 0。
- SC-004: 规定故障场景中重复启动、越权销毁、遗留可调用贡献均为 0。
- SC-005: 未解释新增失败 ID 为 0，测试去向完整，门禁实际执行。
- SC-006: 默认产品受控链可用，真实用户数据/服务变更数为 0。

## Assumptions / Non-goals

沿用 Python/TS/Electron/Lumino，不引入分布式调度、不承诺外部 exactly-once。不实施完整 Profile/Provider/Assets 改版、不合旧工作树、不自动退役分支、不声称真实模型通过。
