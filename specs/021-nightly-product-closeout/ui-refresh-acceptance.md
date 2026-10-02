# Desktop UI 收口验收（2026-10-02）

用户授权：以本轮 Codex Desktop 两张截图为标准整体优化 UI，允许布局调整与子代理并行。不是新增业务、改变配置应用语义或掩盖真实发送阻塞。

## 方向与边界

- 浅灰侧栏、白色主区、13–14px 工具文字、克制细边框、圆角选中行。
- 主区正文最大约 760px、消息独立滚动、输入卡固定 Chat 底部；不是固定整个应用窗口。
- 输入文字占完整一行，工具栏在下一行；Profile/模型触发器紧凑，菜单展开不撑高输入区。
- 设置独立导航，右侧居中表单与分组卡；保留隐藏分区的草稿实例。
- 不出现假的账户、协作、变更统计、审批状态、MCP 状态；现有未知/拒绝继续诚实显示。
- 不改后端、共享契约、配置顺序、凭据或用户数据库，不提交/合并/push，不自动重启用户窗口。
- 来源：用户提供 Codex 截图（视觉参考）；既有 docs/design/workbench-sidebar/plan.md 和 plugins/chat/upstream-manifest.json 的固定 ZCode 来源。仅设计借鉴不标为源码移植。

## 并行所有权

| 单元 | 写权 | 不依赖其它单元即可自验 |
| --- | --- | --- |
| 外框与设置容器 | packages/workbench/** | 模型/服务语义保持原样，包内组件测试 |
| Chat 与会话侧栏 | plugins/chat/frontend/**；agent/sessions 的 view/styles | 使用现有贡献槽；不写模型/Profile 控件 |
| 模型/Profile 控件与表单 | model-provider 的 selector/展示样式/表单；Profile frontend/picker | 不写 wire、应用 glue、客户端状态机 |
| 主会话集成验收 | 本文、进度账、产品 UI 探针、host 通用样式如必要 | 测试串行；唯一构建/报告作者 |

本轮采用既有脏工作树内子代理分文件并行：用户明确要求快速 UI 改版，不新建工作树、不把继承改动提交或搬运。子代理不做 git 写操作，不再派子代理；既有账本沿用，免建第二调度系统。

## 逐项门禁

- [x] A01：启动真实默认产品，三品牌入口可见，页面无错误与文档溢出。
- [x] A02：侧栏底部固定，菜单可见且实际命中，折叠/760x640 可操作。
- [x] A03：设置左导航仅显示一个分区；切换不丢表单输入；关闭/Esc 恢复主区。
- [x] A04：设置打开时原生最小化/最大化/还原/关闭可点击，不被遮罩覆盖。
- [x] A05：Chat 正文限宽居中、输入区不跟消息滚动；长消息/长路径不横向溢出。
- [ ] A06：Profile/模型弹层不改变 composer 高度；滚动长列表、Esc/外部关闭、焦点恢复。
- [x] A07：未知/不可选真实禁用；旧 unknown 在显式重新打开后刷新，迟到结果不串会话。
- [x] A08：选择器使用用户可读配置名，不显示 provider UUID；草稿无原生会话时不是永远“正在核实”。
- [x] A09：模型/Profile 设置字段可辨、保存取消仍可用；不改密码保存/认证操作。
- [x] A10：受控聊天夹具覆盖有消息/工具/思考/错误，不调用真实模型，不冒称发送阻塞修好。
- [x] A11：相关单测、typecheck、产品 build、diff-check；测试失败逐项处理或登记。
- [x] A12：1200px 与 760px 截图目视审查；条件允许检查暗色主题。

门禁资源缺席、探针打不开或找不到目标元素视为未通过，不得以空壳/空列表报成功。用户存活会话不用于破坏性 UI 冒烟；探针只使用临时隔离数据。

## 当前状态

主体改版及已覆盖的真实窗口交互验收完成，交叉复审未发现新增阻塞。A06 的真实会话模型/Profile 联合菜单仍待用户窗口重载后验收；组件定位/焦点/关闭与真实加号菜单均通过。真实 Pi 后续发送前配置应用 unknown / needs_recovery 为独立阻塞，不在本轮以改文案或 CSS 消除。A12 勾选表示宽/窄截图已核查，暗色能力缺席明确登记，不表示暗色端到端通过。

## 本轮证据

- 串行包测试：Workbench 61 Vitest + 7 Node；Chat 68；sessions 45；model-provider Chat 93；model-provider desktop 37；Profile frontend 21；Profile Chat 68；Desktop host 139。合计 539 通过。
- `npm run typecheck`、`npm run build` 通过；默认产品 18 个扩展构建成功。未新增外部依赖。
- 真实默认产品隔离探针：三品牌入口、Pi 连接但不创建会话、项目弹窗、菜单命中/关闭、设置分区/关闭、原生最小化/最大化/还原/关闭通过；文档溢出 0，footer 高 42px。
- `.cleanup-evidence/ui-refresh-startup-provider-form.png`：真实 Provider 添加表单，字段宽度与视口约束通过；未保存配置、未输入凭据。
- `.cleanup-evidence/ui-refresh-preview/result.json`、`02-history.png`、`03-tool-expanded.png`、`06-narrow.png`：受控消息/思考/工具/审批/停止/滚动与 760px 窄窗。输入卡圆角实测 22px，横向溢出 0。受控 fixture 不是实际模型发送证明。
- 新加号菜单实际窗口门禁先发现 Escape 关闭后未恢复输入焦点，已修复并补跨会话保护。重跑结果 bounded / hitTestable / heightStable / closed / focusReturned 全为 true；菜单不撑高输入卡。
- 真实设置新增门禁：切到 Profile 再切回 Provider，未保存名称草稿仍为 `UI probe draft`；760px 宽时 Provider 列表/详情与表单均按内容区宽度变单列，无横向溢出。对应 `ui-refresh-startup-profile.png`、`ui-refresh-startup-provider-narrow.png`。
- 模型浮层的定位、内容尺寸变化、滚出视口关闭、焦点、迟到查询取消由组件门禁覆盖；尚未在用户真实活跃会话上重载并验收新模型浮层或真实切换。这不等同于该会话切换成功。
- 暗色检查：强制系统深色后产品公开主题仍为中性浅色（surface=#ffffff）。当前产品未装配可切换主题服务，因此不报告暗色截图通过；样式已消费公开主题变量，深色端到端待主题能力装配。
- 所有修改留在既有 021 工作树；根工作树分支不切换，未提交、合并、push，未操作用户数据库或重启用户窗口。
