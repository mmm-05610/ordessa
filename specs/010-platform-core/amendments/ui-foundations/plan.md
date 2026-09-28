# Implementation Plan / Public Contract

## 现状与复用

C7 已有 API 与实现中的 registry/React Outlet，直接续做，不重建。现有 Workbench 有面板、浮层、焦点与 `--ui-*` CSS 变量，但本次只读盘点未发现可独立消费的完整基础件包，因此不把“现有平台 UI”当成已经存在。

基础件采用 React + HTML 原生元素 + scoped CSS；浏览器已有的表单、按钮、滚动能力直接复用，不为这些结构移植 ZCode 服务依赖或增加一套组件框架。复杂浮层继续使用 Workbench；本批不需要新增 Radix/Tailwind/图标依赖。后续确需复杂交互再按模块选型。

组合契约参考 React composition patterns：children/子部件表达布局，业务状态由消费者持有，避免一个组件堆布尔开关。`disabled` 等原生状态不在禁用范围内。

## 目录

```text
packages/desktop-platform/ui/
├── package.json
├── src/
│   ├── index.ts
│   ├── containers.tsx      # Card、Panel 组合部件
│   ├── layout.tsx          # Stack、Inline、Toolbar、ScrollArea、Separator
│   ├── controls.tsx        # Button、IconButton、Input、Textarea、Select、Checkbox
│   ├── field.tsx           # Field 组合部件
│   └── feedback.tsx        # Badge、Notice、EmptyState
├── styles.css             # 显式导出，scoped，无全局 reset
└── tests/                 # 类型、行为、样式/真实浏览器

packages/desktop-platform/ui-components/
├── api/                   # C7 既有通用契约
├── src/、react/、assembly/ # 依当前 C7 实际落点
└── tests/                 # 保留 U01–U16；增加与 ui 的组合样例
```

## 最小公开基础件（本批上限，不借机扩展设计系统）

| 基础件 | 输入/行为 | 边界 |
| --- | --- | --- |
| Card.Root/Header/Title/Description/Actions/Body/Footer | children；明确外观 variant（outlined/subtle/plain）；padding；className；原生 aria | 普通信息框，不自动注册视图；不自己折叠、拖拽、关窗口 |
| Panel.Root/Header/Title/Actions/Body/Footer | 高度可分配、头尾不收缩，body min-height:0；children | 内容区域骨架，不接管 Workbench docking/tabs |
| Stack / Inline | spacing token、align、justify；Inline 可 wrap | flex 排版，不是响应式工作区引擎 |
| Toolbar | 水平/垂直操作排列、可访问名称 | v1 原生 Tab 顺序，role=group；不虚称完整 ARIA toolbar roving 模式 |
| ScrollArea | 原生 overflow、方向、ref、children | 不自动跟随、不虚拟化、不劫持滚轮 |
| Separator | 水平/垂直、装饰/语义分隔 | 无业务状态 |
| Button / IconButton | 原生按钮属性；variant、size、busy；IconButton 必需 aria-label | 默认 type=button；busy 禁重复点击且 aria-busy；无异步状态机/自动重试 |
| Input / Textarea / Select / Checkbox | 原生类型与事件、ref、受控值；Select 用原生 option children | 不建实体搜索、多选标签、schema、文件上传；原生 select 多选能力可原样保留 |
| Field.Root/Label/Control/Description/Error | 关联 ID、invalid/required/readOnly 展示；原生标签关系 | 不计算业务验证；Error 不凭存在就每次抢焦点 |
| Badge / Notice / EmptyState | 通用 tone（neutral/info/success/warning/danger）、标题/文字/children | tone 不映射运行结果；Notice 的 live region 必须显式启用 |

`Field.Control` 用 children 函数提供 `{id, 'aria-describedby', 'aria-invalid'}` 给实际控件，不 clone 任意第三方 child、不引入 `asChild` 注入魔法；这是需要向 child 传数据的明确例外。Label 使用同一稳定 ID，两个实例不得重复。普通布局 children 不需要 render 回调。

公共 props 可透传适当 HTML 属性和 ref，避免限制组合；禁止任意 HTML 字符串渲染。实现可以使用独立命名导出，若同时提供 `Card.Header` 风格，应是同一实现，不复制两套。

## 装载示意（不是实现签名承诺）

```tsx
// 真实领域 key 位于其插件 API，不进平台；这里只演示组合关系。
<Card.Root>
  <Card.Header>
    <Card.Title>变更预览</Card.Title>
    <Card.Actions><Button onClick={refresh}>刷新</Button></Card.Actions>
  </Card.Header>
  <Card.Body>
    {/* 按 C7 实际 props 使用 ComponentOutlet，传入已绑定的领域组件。 */}
    <DomainComponentOutlet />
  </Card.Body>
</Card.Root>
```

Card 不提供 `componentId`/`providerId` 属性；具体 ComponentOutlet 在 children 里。无需创建 Card 注册点，也无需 registry 知道 Card 的存在。普通静态内部组件直接 import；公开领域组件是否注册由其插件决定。

## 主题、样式与构建

1. 包名 `@ordessa/ui`，显式导出组件与 `./styles.css`。导入 JS 不自动插 style、不访问 document；样式装配只接现有产品 CSS/build 入口，不创建 DOM 单例。
2. 使用 `.ods-ui-*` 前缀；每条作用于组件的规则均有该前缀，不写裸 button/input、`:root` 或全局 reset。语义变量沿用 `--ui-surface/ink/line/accent/error` 等已有名称，缺失值提供局部 fallback。
3. Workbench 已提供上述变量，继承它们；裸根可通过局部 theme wrapper/数据属性提供深浅值。不要在每个 Button 上重置主题变量，防止覆盖宿主主题。产品主题状态仍是既有装配所有，本包不建主题持久化。
4. 实测现有 `.wb button`、`.wb p` 宽选择器的竞争；用组件规则合理 specificity 解决，不加全局 `!important`、不顺便改 Workbench 全站样式。
5. React 沿 C7 实际单例共享；如果 Field 使用 Context，其包必须走同一真实构建共享入口，防止 Root/Control 来自不同副本。优先沿现有 neutral carrier/build 映射接线，不发明 loader 协议。样式不可重复污染，独立构建消费者亦须可加载。

## 修改所有权 / 追加顺序

继续 T030–T036（C7）。新增 C8 UIB001–UIB008（见 tasks），放同一前端工作树。主代理先更新本线文档并审契约；生产代码派给单包子代理，`ui` 与 `ui-components` 各有唯一写者。共享 lock、carrier、产品接线由指定集成写者串行处理，测试串行。

允许：两个 UI 包、必要公共 build/exports/测试聚合、产品显式样式接线、本线 specs/reports。host/loader 只允许既有 C7 批准的通用接线；C8 不扩大 host 行为。禁止业务插件实现、Python/Go、其他工作树、根 main 切换、用户服务操作、模型调用、push/自动合并。

## 风险与局部阻塞

保留未提交 C7 改动；不得 reset/rebase 清场。若 C7 已完成则加 C8 检查点，不重跑开发流程但须保留回归。公开接缝不满足时报告最小差异和反例，继续基础件独立测试；不得把需要的领域字段塞进平台解堵。无需为本次读取的活动树状态做“独立验收通过”结论。
