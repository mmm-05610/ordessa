# Research / Implementation Plan

## 1. ZCode 精确取材

固定来源：[ZCode 29628c9acdb81b703bbd4080c207a0e7ce5e276e](https://github.com/zai-org/ZCode/tree/29628c9acdb81b703bbd4080c207a0e7ce5e276e)。以下路径均相对 `packages/ui/src/`；已读取固定 SHA 的源码，不声称运行过 ZCode 的视觉基准。

| 来源 | 复用裁决 | 不带入 |
| --- | --- | --- |
| `WorkspaceSidebar.tsx`（return 中 aside 与固定操作/滚动区/footer 骨架） | 提取 `flex h-full flex-col overflow-hidden`、中间 `flex-1 min-h-0`、局部滚动和 footer 排列的 JSX/CSS 结构；内容改成已有 Workbench 贡献 | tasks/workspaces 排序、文件树切换、服务/store、远程连接、固定任务/插件商城入口 |
| `app-shell/WorkspaceShellLayout.tsx` 的 `clampWorkspaceSidebarWidth` 与宽度边界设计 | 复用有限宽度的归一化思路与纯函数结构，调整 Ordessa 上下限；仅取材纯函数 | 终端/浏览器/工作流、ZCode localStorage key/历史迁移、指针 resize 引擎；Ordessa 已有 react-resizable-panels，不造第二套 |
| `WorkspaceSidebar/WorkspaceSidebarCollapsedRail.tsx` | 只参考“收起后始终保留恢复入口”与可访问名称；本批恢复按钮放主区标题，不复制整条 logo 窄栏 | ZCode logo、品牌资源、原生拖拽区域、快捷键服务；避免又回到用户不喜欢的常驻左窄栏 |
| `WorkspaceSidebarFooter.tsx` | 只参考底部稳定工具区的组织；复用我们已有贡献 renderer | 账户、订阅、用量、主题持久化、远程控制、认证业务 |

源文件多处强依赖 ZCode 业务，不能整文件搬。移植结构/纯函数保留 Apache-2.0 许可、来源 SHA/文件/符号与修改说明；仅参考外观的条目注明“参考”，不得虚报源码复用。无需新增 ZCode/npm UI 依赖。

## 2. 目标默认布局

```text
┌──────────────────────┬────────────────────────────────┐
│ 工作区身份       收起 │ 当前视图标题 / 既有工具 / 布局 │
│ 已注册模块/全局命令   ├────────────────────────────────┤
├──────────────────────┤                                │
│                      │                                │
│ 当前 left 内容        │            主区域              │
│ （插件自行渲染）      │                                │
│                      │           右/下等按需打开       │
├──────────────────────┤                                │
│ utility/status 设置  │                                │
└──────────────────────┴────────────────────────────────┘
```

- 标题使用既有工作区/产品显示信息；缺少来源时用“工作区”，不新造账号/远端身份数据。搜索/新会话只来自已注册命令，不猜特定命令 ID。
- 导航项统一图标位置、行高约 30–32px、水平间距、圆角选中背景。保留文字，不仅靠图标；选中态沿实际 module/homeView 关系，不通过标题字符串匹配。
- 左侧初始宽度设计目标 264px；可调范围 220px 到 `min(360px, 容器宽度×40%)`。极窄容器若上下限冲突先保证布局可操作，允许更小宽度并显露折叠入口；不引入新的移动端 drawer。现有 sizes 存储方式不做磁盘迁移，不自动持久化新设置。
- 中段没有固定比例：navigation 按内容高度，长导航限制可用高度；主体占剩余空间。插件内部滚动仍由插件负责，外层使用 min-height:0/overflow约束，不把第二滚动条无条件套在滚动插件外。用自滚动与非自滚动两种 fixture 验证。
- 底部改成侧栏 footer，utility/statusbar 各一次；不硬编码连接/账号。原无条件“本地工作台”装饰不作为业务状态保留。可恢复且不会误报的通用状态才能出现。
- 侧栏折叠时在主区留下明确恢复按钮；utility/statusbar/设置须仍有可访问位置（紧凑底部带），不能因折叠消失。同一时刻只用一个 footer 挂载点，避免重复订阅和动作；重排尽量保留内容实例，测试计数钉住。

## 3. 不改契约的映射

| 现有入口 | 新显示位置 | 语义是否改变 |
| --- | --- | --- |
| composition.addModule | SidebarNavigation | 不变 |
| navigation/primary 命令 | SidebarNavigation（沿既有分组与排序） | 不变 |
| navigation/utility | SidebarFooter | 仅位置变化 |
| statusbar command/component | SidebarFooter / 收起时紧凑底部带 | 仅位置变化，不复制实例 |
| left view / sidebarViewId | SidebarContent | 仍用现有 ViewSurface 与选择/移动机制 |
| main toolbar | 主区 header | 不变 |
| settings sections / overlays | 既有 settings/overlay栈 | 不变 |

现有 `has.left` 同时用于区域宽度、控制可用性，需拆内部计算：`hasLeftContent` 和 `hasSidebarChrome`。全局导航、设置等 chrome 不因最后一个 left view 被关闭而被压为零。`model.collapse('left', …)` 仍控制侧栏整体折叠；重置布局需恢复 chrome 可访问性。模型不增加公开 API。

左侧内容的标签/移动/关闭：多视图标签继续显示；单视图不加标签。移动/关闭入口移到内容区域的更多/布局动作位置，焦点进入时可见，不仅 hover 可见；不从模型删除这些能力。无 sidebar 模块清旧 sidebar 的已有规则保持，普通用户打开的非模块视图不被误清。

主区 header 保留当前视图 title 与现有 toolbar；工具性布局按钮收进明确入口，但不能移除键盘可访问性或原动作。不要读取插件内会话 title 来伪造 Workbench 页面标题。原生标题栏不在此包权限内。

## 4. 包内模块落点

```text
packages/workbench/
├── api/                         # 不改公共形状/Token
├── src/
│   ├── shell.tsx                # 保留总体组合与overlay管理
│   ├── sidebar.tsx              # 四段骨架/导航/footer，包内私有
│   ├── region-header.tsx        # 标签与布局操作（必要时提取）
│   ├── model.ts                 # 必要的内部可见性/折叠协调
│   └── styles.ts                # 壳层样式，禁止命中插件私有类
├── tests/                       # 原门禁 + 侧栏/组合/浏览器证据
└── 来源/许可记录                # 真正复制的部分逐项登记
```

不为侧栏新建服务、全局 store、第二布局引擎；DOM移位保持原 ViewSurface 生命周期。应用如果需要修改 Electron 窗口最小尺寸、产品配置、插件 props 才能达到效果，则该部分出本批，不可偷偷扩大范围。

## 5. 执行协调

与 C7/C8 可能同时修改 Workbench 或测试，**不能在它们活动的目录另开写者**。用户已批准从固定提交 `1ea2084dfbbc7e488f085da7e1ad9b2298ccc149` 创建独立树，具体见 handoff.md；不复制 C8 未提交内容，不等待其新 UI 包。独立分支允许开发，但不证明平台检查点已验收；先复跑自身基线，最终集成再对比 C7/C8 后续改动，冲突不可自动覆盖。根 main 保持不动。

旧 Chat 导航中的 Refresh、草稿项目选择等会原样保留；这意味着外壳先统一，但中部内容尚有后续 Chat 改造。该差异如实列出，不靠隐藏按钮、跨插件 CSS 或 MutationObserver “美化”而破坏功能。
