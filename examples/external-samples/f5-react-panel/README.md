# F5 fixture sample — react panel（样例#5，T008-13/20）

## Owner
`f5-react-panel`：PanelOwner 持状态；TitleView/NoteView/TickView 经 useStoreSelection
订阅选择。零 Agent/Profile/Chat/Harness 依赖。

## 公开能力
F5 选择绑定（`@ordessa/ui-components/react/state`）：同源快照、无关字段零重渲染、
卸载退订、旧代次监听不触新 owner。

## 缺席行为
无后端、无持久化、无真实业务数据。

## 生命周期
`npx vitest run --root examples/external-samples/f5-react-panel`（jsdom；构建期经 vitest
从仓源编译平台状态库=受控 fixture 接线；声明运行时依赖只有公共平台包）。
