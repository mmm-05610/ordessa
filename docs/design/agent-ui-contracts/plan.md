# Implementation Plan: 通用组件机制与 Agent UI 契约

## Research / 现状依据

只读核对 C 工作树的 extension-api、extension-host/runtime、extension-loader、Workbench API、tooling 构建和 C4/C6 文档，沿用 React 19、Lumino、npm workspaces。

- 现有 `Contributions<T>` 已有稳定快照/订阅/撤销，可复用其思想；UI 注册需额外实现产品选择、原子批次与实例代次，不能假定现有类已经覆盖。
- 现有 `PluginContext.resources` 负责自动清理，可沿用 forScope 绑定方式。插件自己的副作用仍由现有激活失败回收机制处理。
- Lumino 当前服务卸载会处理依赖者（包括已连接的 optional）；因此 Chat 不应 requires 某个具体组件提供者，而应 requires 中性 UiComponentsToken 并持有可缺席的 UI binding。
- 当前 loader 一个 manifest 对应一个插件；默认 Agent UI 用一个插件注册多个组件即可，无需为此改成 multi-plugin entry。
- C4 正在将领域 API 从平台迁走。`plugins/agent-ui/api` 是新组件契约，不能复活原来 `contracts/agent-ui` 的 Agent 服务聚合包。既有服务契约路径和 ID 按 C 线迁移方案保持。
- ZCode 复用候选与许可记录见上层 multi-harness-source-research.md。本补充只冻结接口，不授权复制未经审计的组件依赖。

## 目录与修改归属

```text
packages/desktop-platform/ui-components/
├── api/                 # key、UiComponentsToken、binding/选择类型
├── src/                 # 实例注册表、作用域、装配入口
├── react/               # Outlet、订阅与动作 guard
└── tests/               # 全部通用夹具，没有 Agent 字段

plugins/agent-ui/
├── api/                 # 12 个组件接口，按五个家族组织，含 props 与类型反例
├── src/                 # 后续默认实现及激活入口
└── tests/               # 领域行为与显示验收

products/desktop/
└── …                    # 通用 UI 选择表、装配及跨扩展真实构建测试
```

可复用现有服务注入/资源清理模块；不把 registry 再放进 Workbench。Workbench、普通测试 React 根及将来的其他界面都可消费它。包 `api` 子路径不依赖 `react-dom` 或实现入口；React 类型 import 允许。

### C 线范围

1. 增 ui-components 通用包、真实构建共享 API 映射、受控 provider/consumer 示例。
2. 产品装配传入 UiSelection，并将工厂返回的普通服务 plugin 加入现有 runtime 接受的插件数组。优先保持 runtime 签名不变；需要调整产品构建接线时，选择表与创建动作仍归产品装配。空宿主不加入这项服务，默认仍为空。禁止在 renderer 写 Agent key 或默认 providerId，也不能让提供者自己决定 selection。
3. UI 服务完成激活后的必需 binding 诊断加入现有宿主 diagnostics；面向用户输出组件不可用提示，不让 loader 假报所有扩展就绪。通用生命周期代码不得按 Agent ID 分支。
4. 当前产品业务不强制改用新组件；只需受控组合证明机制。现有 UI 保持原链，后续插件阶段逐个消费新契约。

### 后续 Agent UI / 业务线范围

1. 按完整组件总览冻结 `plugins/agent-ui/api` 的 12 项正式类型与 key；逐一审上游组件依赖并按优先级落默认实现。
2. Chat 用轻量 API 和 UI service；Profile/model-provider 用配置状态接口，业务注册入口保持各自所有权。
3. 默认产品选择当前已实现且被消费的接口。迁移前核对旧 Agent UI 使用者，保留业务/视觉/键盘行为测试；不按目录名删除现有实现。

## 最小生命周期

产品冻结选择 → 平台 UI 服务可用 → 任意顺序加载提供者/消费者 → 作用域登记/绑定 → ready 渲染 → 激活完成汇总 required 缺项。

提供者卸载：撤销该 scope 的注册 → generation 立即失效 → binding 发布 missing → Outlet 卸载实现 → 其旧动作拒绝。消费者卸载：先清自己的 bindings/订阅/渲染贡献，不撤销提供者。重新激活产生新 generation；旧 handle 或动作永不恢复。

## 风险和完成范围

- 不以 `ComponentType<any>` 对外换取简便；key/props/注册工厂的类型反例是交付项。
- API singleton、React singleton、按真实构建加载测试与 C4 现有机制一致；单跑 Vitest alias 不算证明。
- React 提交有调度窗口，旧 DOM 不一定同步消失；需要同步失效的动作 guard，不能只测最终 DOM。
- 上游组件引入的状态库、全局样式或 RPC 依赖由 Agent UI 线处理；不让 C 线为了组件移植承担业务工作。
- 通用契约的示意签名须在 C 实施时形成可编译的公开类型；对外语义不允许执行者自行放宽。12 项领域契约由后续插件批次落地，不算 C 完成条件；接口字段最终冻结前须把旧四项草图与完整总览统一。

## Constitution Check

符合当前 010 constitution 的领域归属、契约先行、作用域所有权、空宿主和真实构建要求；没有新增全局业务 service locator。UI service 只能解析注册的组件接口，不能索取任意业务服务。当前阶段只有设计文档，未操作运行服务、模型、凭据或远端。
