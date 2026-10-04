# UI01 只读复用盘点（尚未接口冻结）

盘点后检查点 HEAD abb7670601ebd04fa7638fdaf43bbf5684dcf9ad；原013仍在前端原生身份/可靠提交与干净发行阶段。只读准备不算UI-T完成，UI-A仍全部NOT_RUN。

现成公共机制：Workbench的Module/View/五区tabs与分屏、stable portal、scoped contribution registry、单overlay stack/LIFO Escape/focus trap/anchor退出；Commands及既有Keybinding服务；ui-components Key/provider/binding和F5 EditSession；runtime F5 state/query/projection/task/uiStorage；ui显式CSS/主题token/基础控件。

需要最小增量而非重造：
- 保持全局导航可达，侧栏收起不隐藏整个模块入口。
- layout安全偏好只存稳定View IDs/比例/收起状态，复用F5 CAS；缺adapter明确session-only。缺席插件引用恢复时丢弃，不启动业务。
- 菜单及子菜单持既有commandId和捕获UI目标，经Commands执行；不另建命令/overlay服务。
- 设置由Workbench可返回工作区承载；元数据搜索不读业务正文/秘密；保存事实与F5编辑由领域消费者提供。
- 在ui补确实缺席的menu/search/switch/list/tabs/settings/unknown/loading呈现；可替换provider仍走ui-components。
- 两个独立中性fixture module A/B，仅消费Workbench/Commands等公共出口；各自scope、settings与导航，卸载A不影响B编辑及命令。无Chat/Profile/Agent依赖。

历史jsdom和360/768 Electron场景不抵UI-A01–12。新尺寸1440×900、1024×768、800×600，四角菜单/子菜单、Esc焦点、设置dirty晚保存、退出/迟到回调、干净发行均须新增逐场景证据。当前源码UI-foundations Chromium检查另有继承样式断言失败（期望5px 10px，基线和当前Workbench均6px 10px）；保留失败且不修改断言，不记新增UI通过。
