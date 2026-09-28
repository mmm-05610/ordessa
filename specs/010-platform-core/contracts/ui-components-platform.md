# C7 — 可替换 UI 的通用组件机制

Date: 2026-09-27 | Owner: C frontend | Status: APPROVED_FOR_IMPLEMENTATION
追加起点：`865a6f57fa`，分支 `codex/010-platform-frontend`，追加前工作树干净。

用户已确认 platform-frontend 原 goal 结束，并授权追加本项。原 C 交付记录保留；本项单独形成检查点，不扩大 A/B 范围。

## 权威输入与范围

- 通用契约：[component-platform.md](../amendments/ui-components/contracts/component-platform.md)，全文均属本次实施范围。
- 行为要求：[spec.md](../amendments/ui-components/spec.md) UI-01–UI-14；UI-15/16 的领域内容由受控接口验证通用机制，不实现 Agent DTO。
- 包归属：[plan.md](../amendments/ui-components/plan.md)。通用机制在 `packages/desktop-platform/ui-components`。
- 反例：[验收 U01–U16](../amendments/ui-components/tasks.md)。本 feature 的 T030–T036 是唯一实施勾选表。
- [12 组件总览](../amendments/ui-components/component-catalog.md) 和 [领域 API 草图](../amendments/ui-components/contracts/agent-ui.md) 仅为下一批背景；不创建 `plugins/agent-ui`，不移植 ZCode，不修改 Chat/Profile/model-provider 的业务。
  2026-09-27 C8 裁决更新：该“下一批”已撤销统一实施——领域组件契约与 key 由各业务插件自行定义，
  通用基础件另见 [ui-foundations.md](ui-foundations.md)；本文件的 C7 通用语义与 U01–U16 门禁不变。

快照中的“未分派/设计待审”是设计阶段原文。对通用机制，本文件的已授权状态优先；对领域组件仍保持设计状态。

## 已定实现边界

1. 复用 Lumino 服务 DI、宿主 ResourceScope 和当前 C 线真实共享 API 构建机制。当前资源作用域若已有宿主身份验证/撤销保护，必须继续使用，不能复制一个外观相同的新 scope 绕过它。
2. 服务 Token、key、UiBinding、批次注册、选择冻结、Outlet 和动作 guard 都是通用类型；领域名只出现在受控测试夹具或产品配置，不能写进核心实现。
3. 产品选择由装配提供，provider 不可抢占默认。UI 服务为普通插件，可被产品显式启用；空清单不得被偷偷补上默认插件。产品未使用这项能力时保持原启动行为。
4. API 无实现激活副作用。只读 binding 不暴露可绕开撤销的原始组件；旧 callback/handle 不能影响重激活的新代次。
5. `createUiComponentsPlugin(selection)` 返回 plugin 与 inspectRequirements；通过产品通用装配接入既有 runtime 插件数组。具体文件落点按当前 C 代码确定，不改公开语义，不硬编码领域配置到 apps/desktop。
6. 原子批次先校验再发布；清理异常不阻止其他安全清理，不以新异常覆盖注册/激活主因。注册表不承担插件调度或外部资源生命周期。
7. `UiSelection` 不提供在线修改接口。U02 的拒绝含义为没有此 API，且修改输入对象不会改变已冻结选择；不要另造一个未使用的在线管理服务。
8. 错误/缺席/可选隐藏与旧动作 guard 按契约执行。UI 卸载不得隐式关闭连接或停止后端执行。

## 允许修改

新通用包及包内测试；必要的 extension-api/host/loader 公开接线；产品装配及测试；现有 tooling 共享 API 映射；根 npm workspace/lock/typecheck/测试聚合；受控 examples；本线 C7 报告和任务勾选。

已有 Workbench/Connections 修改仅限确有必要的公共接线，不能顺便重写。Python、Go、真实业务组件、其他工作树及根 main 不在范围。没有修改到的包不为凑数复跑专门测试；最终根聚合仍须完整执行一次。

## 完成标准

T030–T036 实际完成，U01–U16 全有证据；API 类型反例、真实独立构建与临时 Electron 冒烟通过；原测试 ID 无未解释退化；报告记录新增/原有用例与命令退出码，不能把 mock 结果写成真实 Harness 联调。

无 main 合并、push、用户服务启停或真实模型调用授权。完成后停在 C7_IMPLEMENTATION_REVIEW_READY。
