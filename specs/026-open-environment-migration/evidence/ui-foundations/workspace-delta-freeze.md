# UI01 公共工作区增量接口冻结

冻结基线：2dbbc20957（命令子接口冻结）；接收HEAD与源摘要沿用receipt.json/package-refresh-receipt.json。当前013受控恢复已到源码安全检查点；UI-T01进行中，源合同三文件已完整读、独立Luna已核对。该冻结只规定新增能力，不宣称实现或验收通过。原status/tasks/合同和历史evidence不覆盖；原109/129仍有20项开放。

## 所有权和兼容

唯一WorkbenchToken不变。原View/Module/Composition/Commands签名保持；增量通过可选workspace能力提供，旧服务没有能力时消费者明确拒绝，不造业务fallback。C07为单一生产命令owner，Commands只作兼容face；F5为唯一编辑/任务/UI偏好机制。UI components沿用原可替换provider/binding机制。Desktop/native-bridge承担原生文件适配；renderer只经公开桥，插件不取得Electron。现有Lumino、区域分屏、stable portal、贡献scope、overlay栈继续使用。

## 冻结中性接口

新增无React/Electron依赖的workspace DTO与接口，存放既有workbench/api目录并通过公开workspace子入口发布：

- WorkspaceDefinition：id/title/order，homeViewId、optional sidebarViewId；可选图标仍归原React导航贡献，workspace不携领域字段。Module新增可选workspaceId，模块入口绑定该workspace；没有新能力的原module行为保持。
- PageInstance：instanceId、viewId、workspaceId、region，optional targetRef={ownerId,targetId,generation}。四种身份分别存在，targetRef只瞬时传给消费者，不成为事实/writer，不进入偏好存储。view定义仍由原addView登记；component增量可读取optional instance属性，旧无参组件原样可用。
- WorkspaceCapability：forScope(scope).addWorkspace(definition)/openPage(instance)，返回scope-owned句柄；getSnapshot/subscribe；activateWorkspace(id)、activatePage(instanceId)、closePage(instanceId)。snapshot只包含UI身份/选择。close只移除视图，不取消任务；dirty/关闭许可通过消费者可选beforeClose回调，Workbench不持有编辑值。
- 延后UI入口使用captureWorkspace/captureView/capturePage返回绑定贡献对象的操作，失效拒绝，不能按同id解析新贡献。组件生命周期由原registry exact-object撤销保护；退出撤销实例引用，其他scope保持。没有公开授权投影时不可从connected/default猜测权限。
- LayoutV1：schemaVersion=1，稳定workspace/view定义ID的placements/activeViewIds、collapsed和finite bounded panel sizes/sidebar width；不存instance目标/运行代次/DOM/组件/标题/命令参数/秘密/会话或模型事实。restore只采用当前已经注册的ID，缺席降级且不触发插件激活、进程恢复或模型操作。
- createWorkbench的optional layout注入：原F5 VersionedUiStoreContract、UiNamespace、key。缺席或版本能力unavailable/session-only明确session-only。readVersioned与writeVersioned始终用同一adapter/revision，null仅首次缺席CAS；冲突报告、不自动覆盖/重放，未知不冒认写成功。Workbench model是唯一UI布局状态owner，shell resize投影进该model。现有旧DTO/namespace格式不迁移。

## 导航、设置和弹层

全局导航提至不被侧栏collapsed/inert遮挡的常驻rail，无贡献不留空槽；工作区侧栏只呈当前贡献，切换不销毁已接纳业务任务。标签仍沿用已有ViewTabs/指定区域移动操作和stable portal，实例新增不复制领域writer。

Settings使用内建可返回workspace/full-page呈现，保留openSettings(sectionId)入口；不使用modal overlay吞掉主窗。离开恢复先前workspace/page和仍存焦点。原WorkbenchSettingsSection仅增量category/description/searchTerms元数据，搜索只索引声明元数据、不读DOM/业务全文。现有C06 host→Workbench presenter桥复用，值/read/submit/dirty/secretref仍由原消费者/F5 EditSession拥有。旧测试若明确锁住modal语义，原断言不改，记录其与新用户合同的冲突及新增实际场景，不能以skip或业务fallback掩盖。

唯一Workbench overlay栈承载菜单/submenu/custom popover；ui只菜单内容/键盘/视觉，不创建portal/root/全局overlay。四角/长内容viewport约束、Esc逐层、outside、anchor卸载与焦点回退在真实浏览器验收。

## 纯控件增量与叶写路径

ui新增纯props组件：MenuContent/MenuGroup/MenuItem/SubmenuItem（submenu开关由Workbench层提供），Tooltip（无portal）、ListRow/ListGroup、SearchInput、Tabs、Switch、SettingsRow/SettingsGroup、Disclosure、LoadingState。原EmptyState/Notice用于真实error/unknown，状态由调用者提供。所有交互控件可访问标签，disabled与键盘行为；正常等待非红色。CSS仅root统一tokens/显式样式入口，叶不得注入样式或业务store。

叶1只写ui/src/workspace-controls.tsx及对应新测试；叶2只写products/desktop/ui-tests/neutral-consumers的中性消费者/fixture；叶3只读准备GUI场景。root独占契约/Workbench/共享CSS/Runtime接线/产品装配/Git/串行测试。两个消费者不导入Chat/Profile/Agent，独立拥有测试值和操作，用同一个公共F5编辑/命令/呈现接口；三处只读观察不得另造owner。

## 逐场景证据

UI-A01–12各建独立记录。GUI实际1440x900、1024x768、800x600；四角/嵌套菜单、Esc/焦点、tabs/分屏、设置编辑冲突/迟到保存、插件卸载/失败激活。真实IME缺席为PARTIAL，即使合成事件通过；最终固定源码干净DEB中新中性消费者打开和恢复，不能用旧4ad产物抵新增能力。所有新反例先红、修实现，原断言/skip不改。原核心开放项继续独立推进，UI不替代原生真实品牌/全产品变体验收。
