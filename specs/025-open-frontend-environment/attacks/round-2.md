# 第二轮：V2复查与新攻击

输入 models/v2.md（§11优先）、round-1、state-ownership、接口问题；三位原攻击代理全部只读。第一轮A1八项/B1七项/C1十项的原反例均被明确规则排除，结论只是文义闭合。B1-03从缺公共入口进展为可审查候选，通用target和surface歧义另列B2-02/04。本轮新增16项（13 high、3 medium、0 blocker），进入V3第二轮实质修订。

|ID/版本/严重度|前提→精确事件序列|破坏/期望|V3处置|
|---|---|---|---|
|A2-01/V2/high|C1同native提交unknown→重连C2→新LogicalKey→S2绕锁|N1/5；连接传输身份不分裂权威|§12.1稳定连接配置身份、native alias唯一映射|
|A2-02/V2/high|r10完整A/P0→r11 modelB→r12 promptP1先到→r11后到|N2/5；不能旧model伪称r12 current|§12.2 patch链完整性、缺链stale、完整快照发送基底|
|A2-03/V2/high|g1选Profile op1→绑定替换g2→op1仍ready→新提交|N3/5；旧绑定意图不自动跨g2|§12.2绑定适用性，旧操作stale重选|
|A2-04/V2/medium|reserved→持久写失败零outbound→S2永久busy|N2；未发可原子释放|§12.3 not-dispatched终态释放，只影响零承诺|
|B2-01/V2/high|preflight读无未决→await→新操作commit/新required借用→drain|N6；预检裁决不遗漏竞争|§12.4 admission fence+依赖revision共同原子门|
|B2-02/V2/high|无Agent资源插件→AuthorityKey强制server/session→虚构身份|开放原则；本地领域不依赖Agent|§12.1通用TargetRef/schema与AgentKey分开|
|B2-03/V2/high|config major1注册→major2另槽注册→两个写者|N1/3；major不是新事实|§12.1唯一factDomain+canonicalTarget，major仅协商|
|B2-04/V2/high|Agent/terminal surface均input/1/g1→bind未含provider→串接|N7；捕获明确注册身份|§12.5 SurfaceRef不可伪造、namespace/activation完整|
|B2-05/V2/medium|业务运行保留→停UI→重新activate造owner冲突/旧scope复用|N1/6；新UI附着借原owner|§12.4独立presentation activation与旧settlement角色|
|C2-01/V2/high|IME缓冲新文本未发布→click send→捕获旧DraftOwner→end发布|N4/8；所有入口均等候编辑发布，但不自动迟发|§12.3 edit publication barrier，忙则拒本次|
|C2-02/V2/high|保存W1/C1草稿→重开C2或重启W2/C3→找不到草稿|N8；稳定draftId可恢复|§12.3持久draftId与attachment身份分离|
|C2-03/V2/high|授权A读→selector取B→撤lease→队列仍送→settlement扩读|N6/7；读权限与逐投递撤销|§12.6 broker先过滤+read/event/reconcile独立权利|
|C2-04/V2/high|frame F D1获L→F导航D2→端口/lease继续|N5/7；文档epoch不同即失效|§12.6来源/documentEpoch/port broker绑定|
|C2-05/V2/high|I/v1 A拒绝→I关闭v2→B旧批准/双击|N5/7；可信来源仍需条件领取|§12.6互动版本单次claim，未知不重答|
|C2-06/V2/medium|256KiB raw解码膨胀→credit归还→owner/history/views无限复制|资源有界；预算覆盖解码/历史/视图|§12.7 decoded工作集/owner缓存、接管后credit|
|C2-07/V2/high|准备路径P获权→symlink替换→lease检查通过→打开越界|N7；授权实际资源身份而非字符串|§12.6 scoped resource handle+安全open，缺机制拒|

第二轮正向文义序列：同target第二提交busy；CAS冲突不发prompt；执行证明无当前快照只消费且保持stale；staging失败不publish；资源Chat集成不重建基础owner；commit撤销两先后不同；Esc单次关闭；旧streamEpoch不能进入新快照。均未代表UI/IPC/真实服务测试。

复查证据：A原报告逐项指出§11.1–3，B指出§11.4–6及B1-03局限，C指出§11.6–8。最终独立复查另见review.md，不以本页处置声明自行验收。
