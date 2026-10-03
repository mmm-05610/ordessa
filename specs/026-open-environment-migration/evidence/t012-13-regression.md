# T012-13 A96–A111 逐项回归（2026-01-04 夜班实测）

逐项回归基准=008 期证据映射（order-008-a96-a109-evidence-map.md）所载承载测试；
本轮以**全量套件实测**复核（零 skip、零删断言；每套件跑数见 t012-01-02-sweep.md 计数表）。

| case | 承载套件（本轮实测） | 回归结果 | 备注 |
| --- | --- | --- | --- |
| A96–A98 | ui-components（77F）+ f5-counter/f5-react-panel 样例 | ✅ 绿 | identity-stable/deep-freeze/单通知/卸载退订 |
| A99–A101 | ui-components（77F）query/tasks 投影帧、stale barrier、cancelWait | ✅ 绿 | gap/合流/代次隔离/unknown 单次尝试 |
| A102–A103 | ui-components（77F）editing/uiStorage | ✅ 绿 | ABA 双例/冲突保本地/未知 schema 拒 |
| A104–A106 | model-provider/chat-contribution（120F）+ agent-contracts（27F） | ✅ 绿 | 任务/通知/进度/查询机制；资源无 Chat/Profile 依赖=T010-11 证据 |
| A107 | workbench（84F）+ F5 API/React 出口样例（f5-counter/f5-react-panel） | ✅ 绿 | 发行面独立验证见 T012-12（未跑，登记待续） |
| A108 | **真实 Electron 输入/焦点** | ⛔ **U 待验（缺授权/资源）** | 明文不算完成（T012-05 同因）；无头 smoke 不替代 |
| A109 | workbench（84F）interactions + ui（display-tools） | ✅ 绿 | ContextKey 同源/when 不授执行权 |
| A110 | 存储 fixture + uiStorage（77F） | ✅ 绿 | 跨窗口/发行级保证不以模块单例冒充（R7 合同）；发行产物验证=T012-12 待续 |
| A111 | **真实 Electron 通知/UI 恢复** | ⛔ **U 待验（缺授权/资源）** | 同 A108 |

**资源缺席记录**：本环境无显示器/无用户 GUI 会话授权、无真实模型调用授权（T011-08 同因）；
A108/A111 的真实 Electron 输入/通知/焦点/UI 恢复验收**未执行**，不以任何模拟绿替代。
无头 smoke（`npm run test:electron`）仅证启动面，不构成 A108/A111 证据。

**本轮总回归实测汇总**（同夜，同一树）：TS/Frontend 654F 全绿（12 套件）；
agent 域 Python 15F；pacthold+environment-api+server-plugin-api 386F；apps/server 1215P
（66F+2E 登记红集，stash 对照逐 ID 一致）。红色集合零新增。
