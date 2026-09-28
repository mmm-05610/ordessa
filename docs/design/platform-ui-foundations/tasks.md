# Tasks / Evidence：C7 保留，C8 增补

本文件为 C7 后续增量，不能替换原 T030–T036/U01–U16。没有授权实施那 12 项领域组件。任务 ID 使用 UIB 前缀避免与活动树并发编号冲突。

## Phase 1 — 对齐与契约

- [ ] UIB001 冻结接收追加时的 HEAD/脏树和 C7 进度；将本设计快照复制到本线 `specs/010-platform-core/amendments/ui-foundations/`，更新权威链及 tasks；历史领域设计标为撤销统一实施、取材留档，不删 C7 通用反例。
- [ ] UIB002 在 `packages/desktop-platform/ui` 建显式 exports 与公开最小类型，明确 Card/Panel/Field 组合、原生 ref/事件；先加类型正反例，不加任何业务模式。

## Phase 2 — US1 / US3 基础件

- [ ] UIB003 `containers/layout` 实现 Card/Panel/Stack/Inline/Toolbar/ScrollArea/Separator；独立 React 根、无服务也可用；先钉键盘与嵌套滚动反例。
- [ ] UIB004 `controls/field/feedback` 实现 plan 最小清单；验证 label/error ID、禁用/busy、受控输入、默认 button type、0/空文本，零保存/网络副作用。
- [ ] UIB005 显式 scoped CSS/主题/build 接线；深浅、窄屏、裸根与 Workbench 宽样式共存；真实构建 React/Context 共享测试。锁由 npm 更新，不手工拼写。

## Phase 3 — US2 组合与开放性

- [ ] UIB006 用现有 C7 provider/consumer fixture 新增一种受控领域 key；独立 API 归测试领域载体，非平台 carrier。消费者在 Card 中放真实 ComponentOutlet，provider 不依赖 Card；验证普通内部组件不注册也可用。不引入真实 Git/Chat 插件。

## Phase 4 — 验收与收口

- [ ] UIB007 串行执行 C7 U01–U16、C8 V01–V08、根聚合/typecheck/build/现有临时 Electron 门禁；按原 ID 比对回归，几何用实际浏览器。未运行项不得填通过。
- [ ] UIB008 主代理逐项复核 diff/依赖/导出/样式，记录 source→reuse（React/原生/已有平台）、任务→测试→日志；提交增量检查点与报告，停 `C7_C8_IMPLEMENTATION_REVIEW_READY`，不合并/push。

## C8 验收矩阵

| ID | 正向证据 | 必须有的反例 |
| --- | --- | --- |
| V01 | 普通 React 根组合全部基础件 | 不加载 registry/runtime 仍能渲染；JS 导入不创建 DOM/注册服务 |
| V02 | label/description/error 正确指向控件；受控输入 | 双 Field 不重 ID；disabled/busy 不触发；表单内普通按钮不意外 submit |
| V03 | Panel 头尾固定、body滚动；360/768px | 长行只在指定区滚动、不撑破页面；不因使用 Card 自动劫持滚动 |
| V04 | 深浅主题/焦点/reduced-motion | 插件外原生元素 computed style 前后不变；真实 `.wb` 环境控件样式不被覆盖 |
| V05 | 自定义 key经真实构建在 Card 内渲染 | 新类型只改测试领域/API/provider/consumer；平台实现零新增领域分支 |
| V06 | scope撤销、替换/重激活正常 | 旧动作仍拒绝，Card不取消业务；未选/缺席与渲染出错按 C7 不混淆 |
| V07 | API/React/Field context真实共享 | 跨独立 bundle Root/Control 仍关联；不以开发alias冒充生产构建证据 |
| V08 | 不启用 UI service 的空宿主仍有效 | 不偷偷添加默认 provider、Agent key 或运行时基础件插件 |

## 执行与报告

给 `ui` 提供真实 `test` 脚本，新增类型文件加入既有 typecheck；UI 组合测试加入 C7/产品受控 gates。实际命令依据 C7 最新树，不臆造现有脚本名。每门记录命令、退出码、测试 ID 与证据路径；浏览器截图记录 viewport/theme/container。主代理亲验；报告不是子代理摘要拼接。

小问题自行修复继续；阶段提交不等于停工。阻塞仅暂停受影响任务；需要变更冻结契约/安全边界时一次汇总证据请求裁决。禁止 skip、吞异常或放宽原断言换绿。
