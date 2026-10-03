# 场景矩阵与验收证据

最终规范以 models/v4.md 为准；模型输出不是已实现产品。证据分级：S=冻结源码检查；D=模型推演；L=本目录离线确定性检查；U=隔离UI夹具（本轮未运行）；P=真实产品（本轮禁止）。下表每行的正/反例和缺席行为为未来可执行验收要求，不能把L结果扩写为U/P。

|编号/场景|预期及正例|反例必须捕获|缺能力行为|本轮/未来验证|
|---|---|---|---|---|
|01 无业务插件|空enabled；仅基础壳/工作台设置可启动；resource单独装入|root必须Chat/品牌，空清单被defaults覆写|required业务拒能力不崩壳|S I11/22+D；未来隔离空产品构建/U|
|02 Profile含模型|opA(M1/P1)；Resolved标签M1 pending，Confirmed旧M0|模型控件空/旧值或未回执标confirmed|resolve/version不可证则resolving/refused|L字段fold；未来公共owner+两个控件U/P|
|03 Profile无模型/model单项|已有B/P0；A只prompt→B/P1；modelC→C/P1|缺model转unset或model清prompt|显式字段mask缺席阻提交|L字段fold；原子model/provider字段组仅D，未来领域服务P|
|04 覆盖顺序|A(M1/P1)→B为B/P1；B→A为M1/P1|异步解析返回顺序胜点击顺序|固定revision不可取拒该操作|L解析版本拒绝/字段覆盖；真实resolver返回乱序仅D，未来wire夹具|
|05 同值重选|A→B→再A，新opId恢复A声明字段|同值React/native select无事件而丢操作|用可触发每次选择的菜单动作，不额外重应用按钮|L新seq；U原生select/鼠标键盘待测|
|06 输出中改配置|运行不断；操作排入next配置；下次发送冻结同一快照|控件即时apply/abort；两个转换器拼send|输出busy拒发送但保留选择；无一致边界拒配置发送|L冻结与reservation；未来输出中配置P|
|07 输入与中文IME|流/配置通知不写value；候选Enter不送；光标保留|panel先吃组合键、ABA清空、remount|无可靠键周期用显式按钮；真实平台未证|L抽象inputEpoch；U实际Chromium多IME待测|
|08 成功/拒绝/未知|accepted清相同revision；refused保留；unknown核对不重发|仅文字相等清草稿、异常都当拒绝、auto retry|无核对端口unknown保持，拒依赖路径|LABA/结果状态；未来断线注入U/P|
|09 草稿首次绑定|选项无create；首发送C1绑定N1；新op不丢|selection调用prepare/open空session；unknown再create|缺首次边界仅选择/草稿，发送unsupported|L简化creationAttempt/binding身份判断；实际首次创建仅D，未来native创建P|
|10 会话/窗口隔离|S1旧结果回S1；S2草稿不变；同model不同owner实例|selected重路由、以model作key、窗口重复领取|跨窗口共享owner缺席明确单窗口限制|L隔离/同targetbusy；未来多窗口U|
|11 断连/重启|lastObserved historical，possiblySubmitted核对旧id；新generation不冒认|恢复操作自动apply、未知草稿当未发、历史当current|持久标记写失败禁止outbound；旧核对缺席未知|Lcrash marker/epoch；未来kill夹具进程仅隔离环境|
|12 native自主变更|pending只覆盖声明字段；消费后新native值生效；r12先到保留|旧回执覆盖r12，永久overlay，未声明prompt写回|无版本证据标stale；CAS缺席拒依赖保证发送|Llate receipt/patch/CAS；未来native入口P|
|13 未知workflow|已授权native入口原样/workflow，不需core枚举|本地registry未注册即拒|无native通道unavailable不fallback|D+L路由；未来新能力兼容夹具|
|14 同名命令|native输入→native；环境面板显式选→environment|依据字符串猜路由/双执行|目标入口无能力明确拒绝|Lroute来源；未来两注册入口U|
|15 未知内容|来源标记、有界原文；富展示缺席不造审批|script/事件URL/伪审批/视觉覆盖|可信interaction证据缺席审批不可用|D安全规则；U恶意内容隔离待测，不能用字符串过滤代替|
|16 新插件完整贡献|公共context注册owner/page/sidebar/settings/menu/input；无需品牌branch|直接导入host internals、每view创建owner|缺required拒batch，optional集成不激活|D三接入序列；未来独立manifest/build/U|
|17 卸载|preflight拒绝完整移除保持active；允许停UI；旧收尾记录继续|scope关后才拒、引用无人收尾、kill运行|无settlement服务则拒完整移除|Lpreflight/commit竞态；未来资源夹具U|
|18 升级/旧Token|g1旧ref/lease拒绝g2；同信任域Token单实例|名字相同当权限、旧dispose删新记录|major不兼容拒绝；隔离用协议握手|S I15/16/20+D+L；未来真实build Token guards|
|19 多视图同事实|page/settings/sidebar借同authority；关view不销owner|重复register、projection反写、关闭view销run|owner缺席显示absent，不另造替身|Lauthority槽/借用；未来替换组件U|
|20 菜单设置窗口|portal越overflow；一Esc关原top；焦点回有效trigger/chrome保留|双Esc、窗口按钮被全页盖、卸载尾键新焦点提交|anchor无效拒popover并给有效入口|D+L Esc/inputEpoch；U视口/焦点/窗口按钮待测|
|21 高频长列表流|每跳总/局部预算；cursor快照屏障；不可丢输入满则拒|多流绕预算、UI暂停但IPC涨、未决记录丢失|无背压断surface并gap；无snapshot/incomplete|L预算/gap/epoch；性能/长列表U待测|
|22 native安全|真实realm身份+lease+commit point；隔离native不进main|第三方native import main、自报pluginId、跨await撤销仍发|隔离/lease机制缺席拒第三方执行；网页无native|D+L授权竞态；真实进程/IPC对抗U未验证|

## Profile/model端到端轨迹

|步|事件|Confirmed权威投影|操作与待应用|发送/显示|
|---|---|---|---|---|
|0|native r10={M0,P0,skill S0}|配置owner证据known|无操作|标签M0 confirmed|
|1|点击Profile A v7={model M1,prompt P1}，op1 seq1|仍r10|Resolved M1/P1/S0|M1 pending；Profile来源A v7|
|2|点击model B v3，op2 seq2|仍r10|B/P1/S0|所有view同一selector B pending|
|3|点击不含model的Profile C v2={skill S2} op3|仍r10|B/P1/S2|C是操作来源，不冒充全配置|
|4|Agent仍输出中|仍r10|op1/2/3 ready|不abort、不apply；发送busy可保留|
|5|显式发送S1|仍r10|原子领取1/2/3、capture digest D|草稿r5、writePatch B/P1/S2、base r10冻结|
|6|发送等待时再选A op4 seq4|仍r10|op4留next，Resolved M1/P1/S2|S1不会吸入op4|
|7|S1整体应用r11，输入拒绝|E-execution消费1/2/3；current r11|op4仍pending|草稿r5保留；显示待应用M1、已确认B|
|8|native自身改model C r12|current r12 C/P1/S2|op4仍覆盖model M1|分别展示C confirmed/M1 next|
|9|迟到S1 r11重复回执|不回退r12|不消费op4|去重，非冲突|
|10|下一次S2 capture基底r12、op4|冻结M1/P1/S2|领取4|只有原子条件边界匹配才输入；冲突拒本次|
|11|S2 result unknown、重启|lastObserved historical|reserved4/possiblySubmitted→unknown|只读核对S2，不自动send；草稿保留|
|12|S2关联证据确认并有current r13|消费4，Confirmed r13|没有永久overlay|输入接纳只清相同r5；用户r6即使文本相同也保留|

每一步已确认字段只有配置owner写入；控件/适配器只投影/编解码。backend接口缺席及partial结果按最终模型限制，不能把本轨迹当实机日志。

## 主验收新增序列（2026-10-03）

- A-03：r10=M0→r10=BAD进入conflict→重复r10=M0两次/旧观察/patch仍拒绝capture→可信完整r11快照解除。未提供新版本或可信核对结论时不得选择冲突的一边。
- A-04：r10→先到r11→r12 patch产生gap→完整r12快照清覆盖段→r12→r13连续patch可提交；迟到旧patch不回退/再造stale。r14→r15未来未覆盖段必须保留gap，补齐链后方恢复。
- 两项已在有限参考脚本执行，当前30项；旧28项证据保留。真实证据校验/后端协议/UI仍未运行。
