# 第一轮：V1 三路攻击

冻结输入 models/v1.md、boundary/inventory、source-snapshot/source-excerpts；三代理只读，无嵌套。本页主会话记录原报告实质，文义反例不是产品故障复现。严重度来自代理。共25项（3 blocker、16 high、6 medium），全部进入V2明确规则；没有用代理好评代替验证。

表中每行包含前提→事件序列、不变量/预期、建议与处置。完整返回报告在本会话代理消息；此页为可独立审计的结构化记录。

|ID/版/严重度|前提与精确事件序列|破坏/预期|建议与V2处置|
|---|---|---|---|
|A1-01/V1/high|两窗口同target；S1捕获op1未回执→S2又捕获op1→两次apply|N3；只允许一次领取同操作|提交串行、reserved及unknown锁；§11.1|
|A1-02/V1/high|r10 A/P0，op1仅model B→冻结B/P0→native prompt=P1 r11→写B/P0|字段覆盖；不得写回未声明prompt|writePatch与Resolved区分，条件应用；§11.1|
|A1-03/V1/high|S1 r11 B→native r12 C→先观察r12再回执r11|N5；旧应用成功不应误判冲突或回退|同版本冲突、更新版本覆盖；§11.2|
|A1-04/V1/high|Profile含model/prompt→model已应用→prompt拒绝|N2/5；不能整体成功或重复覆盖|只允许具备全patch原子保证路径；部分unexpected进入unknown；§11.2|
|A1-05/V1/high|回执无nativeRevision→普通当前观察B→native变C|值相等不能证明执行；不得误消费|关联证据与当前证据分开，最低证明条件；§11.2|
|A1-06/V1/medium|点击Profile v1未解析→目录v2→model op2→resolver返回v2|序号保留不保证内容；必须v1|固定revision/digest，错版本refused；§11.1|
|A1-07/V1/high|draft target T0→创建N1迁T1→op2→回执T1|严格匹配拒合法回执；宽松易串号|稳定LogicalKey+一次binding proof；§11.3|
|A1-08/V1/high|发S1→关联未存→崩溃→恢复草稿→S2|N5；不能把可能发送当未发|outbound前持久最小关联标记，失败禁止发送；§11.3|
|B1-01/V1/blocker|required依赖O运行中→deactivate先关scope→之后拒卸载|N6；拒绝应保持完整激活|preflight在revoke前、required闭包；§11.4；现有runtime需新增机制|
|B1-02/V1/high|资源prepare R→卸载scope→返回引用→旧回调拒绝→无清理者|N6资源owner；旧结果收尾不能丢|UI/交互scope与settlement scope分离，未决阻完整移除；§11.4|
|B1-03/V1/high|新作者仅公共包→注册owner/surface/借用/撤销找不到入口|完整接入不可判定|新增候选公共注册/lease/结果接口，三例调用序列；§11.5|
|B1-04/V1/high|Oa/Ob同domain target→控件各借一个→双seq/配置|N1/3；唯一槽原子选定provider|唯一AuthorityKey，注册冲突拒整个batch；§11.5|
|B1-05/V1/medium|资源无Chat启动→Chat出现→准备引用→Chat移除→重启|optional动态规则缺席|独立集成子插件required Chat，基础owner不重启；§11.4/5|
|B1-06/V1/high|staging addView已可见→异步lease失败→用户期间已操作|N6；失败不应暴露半激活|batch staging，不发业务副作用，active原子发布；§11.4|
|B1-07/V1/medium|共享Token同renderer→隔离frame无Token→字符串自报身份|跨构建身份不是授权|同域Token，跨域版本schema+broker绑定；§11.5/6|
|C1-01/V1/high|composition→面板先吃Enter；或end后尾Enter误发|N8；候选确认不得发送|输入组合守卫先于面板；尾键屏障；§11.7|
|C1-02/V1/high|组合中→无关流通知→受控value刷新→组合/selection丢失|N8；稳定key不充分|编辑本地缓冲/稳定selector/单写入口；§11.7|
|C1-03/V1/high|设置组合中→停用强撤弹层→无end→焦点主输入→尾Enter|N8；不能丢草稿或穿透提交|cancel保存缓冲、inputEpoch隔离尾键；§11.7|
|C1-04/V1/medium|popover Esc关闭→冒泡workbench又关dialog|一次事件最多关闭原top|单一dispatcher捕获instance、消费事件、focus栈代际；§11.7|
|C1-05/V1/medium|A表单r10改草稿→B存r11→A通知覆盖/旧保存|N2/8；草稿与值分开|每表单草稿、保存base/field mask，冲突拒绝；§11.7|
|C1-06/V1/high|多流各低于预算→总内存涨；大对象先stringify后限|N8；总量/解析都须有界|全局/plugin/target预算，raw UTF8先限，深度/时限；§11.8|
|C1-07/V1/high|UI暂停→native继续→IPC堆积→gap未到owner|N5/6；每跳有界并同步失效|端到端credit/断流、快照cursor屏障；§11.8|
|C1-08/V1/blocker|隔离UI但native entry在main import→顶层任意系统代码|N7；默认隔离必须覆盖native代码|第三方native只隔离executor；缺机制拒加载；§11.6|
|C1-09/V1/blocker|验证lease→await open→撤销g1→g2→g1返回发副作用|N5/6；入口检查不能越await|授权commit point，await后复验，已承诺真实收尾；§11.6|
|C1-10/V1/medium|内容画系统审批→外链/消息→冒充用户能力授权|N7；视觉和事件来源不可升级|宿主来源chrome、不可占用审批区、scheme策略；§11.6|

正向纸面序列：A的字段覆盖/同值重选/旧回执仅消费捕获操作/文本ABA，B的未知workflow和旧generation入口，C的恶意HTML禁止与嵌入不授shell均能从V1推导，但不包含实机或离线测试证据。所有代理明确未验证实际契约、真实IME、IPC、隔离进程与Token构建。
