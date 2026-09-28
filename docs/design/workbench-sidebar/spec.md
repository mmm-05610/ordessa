# Feature Specification：应用式导航外框架

状态：Draft。范围：Workbench 包内部呈现与布局，保留既有公开契约。

## User Scenarios & Testing

### US1（P1）：进入应用即可找到模块与当前内容

- Given 已注册模块/导航命令，When 启动，Then 同一个侧栏呈现全局入口与当前 left 内容；不先展示一个独立 Sessions 面板管理框。
- Given 模块没有 sidebarViewId，When 切换，Then 旧模块侧栏按现有规则清除，而全局导航仍可见；普通非模块视图的既有保留语义不变。
- Given 没有任何 left view，Then 已注册全局入口不能因 left 区域尺寸为零而消失。

### US2（P1）：长列表不挤掉全局控制

- 顶部身份/折叠控制、导航区、底部设置/工具区与模块内容有清晰分工；中部模块视图保持可滚动。
- 导航项过多或窗口较矮时，导航自身允许受限滚动，不固定 40%/60% 分配，不让中部完全失去可操作空间。
- footer 贡献增长时允许换行/自身有限滚动，不能静默裁掉按钮或让它覆盖主内容。

### US3（P1）：日常简洁，仍可管理复杂布局

- 单视图不显示标签条；常驻“移动…”选择框不作为默认视觉焦点，移入明确可键盘到达的布局操作区。
- 多视图仍可选择、关闭和移动；main/right/bottom/top 的现有能力保留，不裁剪布局引擎。
- 侧栏折叠后主区仍有恢复按钮；无 hover 也能操作设置、布局、导航。

## Functional Requirements

- W01：统一侧栏 Header / Navigation / Content / Footer 四段；平台不识别项目/会话数据。
- W02：模块、命令、视图、settings、statusbar、overlay 的现有注册调用/ID/排序/作用域不变。
- W03：不要求消费者改 component props、服务依赖或 private CSS。不得用 `.agent-*`、Chat 插件 ID、DOM 查询规则重排插件内部内容。
- W04：全局导航可见性不能仅由 `left` view 数量决定；关闭/移动内容视图不是卸载全局导航。
- W05：左区域仍保持 `Region='left'` 与 sidebarViewId 的现有含义；不在移动后擅自搬回或另建第二 left。
- W06：整合底部入口不复制挂载贡献。现有 command/component statusbar 和 utility 导航各渲染一次，设置仍调用既有 Workbench settings overlay。
- W07：无新业务与宿主行为；不伪造搜索、通知、账号、新会话命令。没有对应贡献就没有那个按钮。
- W08：提供者卸载、模态焦点、popover 锚点失效、错误层级、布局拖动等既有门禁不得因美化退化。

## Success Criteria

1. Workbench production/API 以外源码零修改，外部注册 fixture 使用原样调用通过；若发现必须改公开契约，停止该点并报告，不暗改其他包。
2. 空 left/无 sidebar 模块/普通 left 视图/多 left 视图/全部模块卸载均有反例，导航、焦点和状态行为诚实。
3. 1280×800 与 900×600 的实浏览器截图：顶底不随模块内容滚走、无整体横向溢出；折叠与键盘恢复正常。200% 缩放下所有动作仍可访问，不靠隐藏条目通过。
4. 原 Workbench 测试按 ID/断言迁移而非删改隐藏回归；实际桌面构建/临时 smoke 通过。未运行浏览器不得声称视觉完成。

## 非目标

项目树/置顶/最近会话/更多加载的实现；把新会话表单从侧栏搬主区；原生标题栏/系统菜单修改；移动端 drawer；全局搜索服务；改为新的布局库；在线拖动模块排序；重做所有主题。
