# 前端重构实施方案（未实施）

候选模型 models/v4.md；用户审核模型与方案后才可编码。只迁目录不能解决事实重复，迁移必须移除I01–I05中的配置写者。代码搬迁与行为变更分开验收，禁止把新配置协议/安全模型包装成内部重构。

## 1 子包依据与公共入口

包数由职责与运行域导出。此提案九个packages/frontend子包，加独立Workbench与领域插件；不是预设“七包”。入口示例都是待迁移，不创建生产目录。

|候选包/公共入口|允许依赖|禁止依赖|唯一拥有的状态|独立验证|
|---|---|---|---|---|
|extension-api：index、scope、protocol types|Lumino公开类型/Token；平台types|业务、Electron、React、host内部|契约身份，无业务store|exports/typecheck、Token构造正反例|
|extension-runtime：renderer、main/discovery分入口|extension-api、Lumino、独立环境adapter|Workbench/Agent配置、品牌|插件activation、authority注册槽、scope/贡献批次/借用记录|激活失败/重复槽/预检/旧句柄/晚open收尾|
|contracts：公共carrier/版本schema|api+各通用公开契约|Agent/Profile/Harness语义、业务实现|Token单构造，不持数据|真实构建import-map identity、重复打包故意注入必须失败|
|ui：控件、styles|React及平台呈现types|domain/runtime/native/internal|局部hover/open等呈现；不持事实|bare-root/import副作用/a11y/IME控件夹具|
|ui-components：api、react outlet|api、React、ui|领域owner、Workbench内部、host|provider availability、binding generation|旧dispose/选项过期/缺provider/组件异常|
|connections：api、runtime|api|Agent/Harness、Electron实现|连接尝试/handle/transport phase及close关联|connector缺席/abort/晚resolve/close unknown|
|interaction-surfaces：api、runtime、react adapter|api、ui-components、通用domain access|已知品牌命令、配置字段、审批业务|表面绑定/cursor/credit/来源及输入事件路由|未知kind/cmd、路由重名、每跳预算/epoch、输入夹具|
|native-bridge：api、main broker、isolated executor protocol|api、connections、明确main安全adapter|renderer app内部/业务品牌、第三方main顶层模块|lease/instance/授权commit/传输预算|caller/lease伪造、await撤销、main恶意模块拒绝、网页降级|
|server-bridge：api、main|api、通用transport|业务配置/插件store|wire readiness/request关联、凭据仅main|断线Unknown、不自动retry、字符串method校验、秘密不进renderer|

packages/workbench暂保留独立package，公开api/contributions/react shell；依赖api+ui+ui-components+平台command contracts。它拥有布局/overlay/settings展示注册唯一状态；禁止加载插件、复制settings业务值。是否后续移入frontend命名空间只是路径迁移，与其语义无关。domain access/操作关联在runtime公开types，配置解析器和Application语义在Agent插件，不另造万能state库。

## 2 现有源码逐项映射

|现有|处置|精确责任变化|
|---|---|---|
|desktop-platform/extension-api|保留并迁名|仅契约/scope；公共native types从app内部迁入该体系|
|extension-loader|合入extension-runtime加载入口|保留发现/校验；与唯一registry组合，禁止第二scheduler|
|extension-host/runtime|拆分runtime/shell|保留Lumino；新增preflight/staging/settlement/代际；Shell交给Workbench/neutral host fallback|
|contracts/foundation|拆分carrier与业务契约|平台Token共享carrier保留旧specifier；HarnessAvailability移Agent领域公开carrier；旧入口只薄兼容，设移除门|
|ui|保留基础呈现包|不接领域store|
|ui-components|保留可替换组件平台|绑定只拿同owner props/actions；UI gen不当native gen|
|connections|保留协议无关runtime|不合并Agent workspace；adapter仅frame/request映射|
|native-bridge/server-bridge|保留各环境入口，强化隔离边界|不合并成通用任意IPC；native第三方executor与trusted main代理分开|
|workbench|保留并扩完整贡献组织|统一settings registry、global overlay、menu位置；不增加插件加载器|
|app renderer host-services.settings/main.tsx overlay|并入Workbench唯一注册/打开入口|宿主平台设置也做平台贡献，值仍由main settings/domain拥有|
|Profile selection/glue|拆为目录操作源/薄Chat集成|移除selections/lastConfirmed/retained/bindings/clickQueues领域写权|
|model next-turn-client/chat-api-entry|拆codec与薄贡献|移除pending/route/queued/current独立写权；共用配置domain|
|Chat DraftStore/page controller|Chat接入迁移至独立DraftOwner和领域协调服务；非Chat输入借通用edit ticket，不依赖Chat|保留revision/附件；支持视图外结果收尾，文本相等清空改revision|
|Agent sessions|保留领域、明确逻辑绑定/多窗口共享|selected只是投影，command必须capture target|
|ACP host.ts→app内部import|退役内部路径|公共NativeTransport契约，同一导出身份，不copy类型|
|products extensions/lock/build|保留装配职责|选择required/optional集成、UI provider、共享carriers，app无品牌imports|

每个退役状态都需“谁是新写者、旧入口如何不能再写、消费者如何迁移”证据。禁止新owner包装旧Profile/model两个store后同时留写权。迁移期间如需兼容，所有旧select/choose都转dispatch到同owner，仅保留codec请求映射。

## 3 兼容规则

- extension ids、extensions.json显式空覆盖、UI component ids/major、旧共享import specifier不随目录改名。package exports旧入口暂指向唯一新实现，不能同时bundle两个Token。
- domain载体不能平台反向re-export；先迁消费者到domain载体，确认无旧路径再移除。旧public入口需有冻结兼容测试和退出条件。
- 构建app/插件external同一React/API/Token carrier，import-map来自装配；不同构建hash但同major共享运行身份，major不兼容拒绝。隔离域使用schema握手，非JS对象跨域。
- 持久格式/DB路径/history ids本提案不更名。恢复关联标记若需新本地schema，仅新增版本命名空间，保留旧草稿并显示来源；真实用户数据迁移须另获授权，离线copy fixture两次启动/回滚验证。
- CAS/整体应用/证据语义是行为与协议变更，不能复用旧beginTurnApplication名称假称已兼容。backend-interface-questions先获得双方契约，再实现；旧生产链保留明确保证等级，不静默启用新保证。

## 4 分阶段落地与验收/回滚

|阶段|实现结果与不变量|正例/反例|回归范围与缺席/失败|回滚点|
|---|---|---|---|---|
|P0 固定证据/契约审核|用户认可模型，固定实施树、HEAD、脏文件和接口版本|验证产品main/P差异；反例用错树/未知契约也通过|资源不存在即blocked，不运行真实模型；先fixture|仅设计快照，无生产变更|
|P1 纯代码入口迁移|目录/exports/carrier调整，无业务状态变化|真实build同Token；故意第二Token应失败|typecheck、contract-ownership、product-bundles、connections isolation；缺工具/产物不是绿|恢复旧package exports/import-map，无数据变更|
|P2 组织与生命周期|唯一settings/overlay；runtime preflight/staging/settlement|拒卸载保留scope；失败activate不可见；Esc一次|host/workbench/ui-components/empty product/旧回调；无preflight停在旧安全受限模式|切回旧装配入口，结清未决后换runtime，不能弃未知|
|P3 领域权威收束|一个配置owner，Profile/model仅操作源|两顺序/不含字段/同值/异步版本；反例旧store仍能写|Profile/model集成、Chat草稿、sessions及checks全部；无公共解析/证据拒相关路径|旧codec兼容仍指同owner；禁止两写者并存回滚，先静默UI新入口并核对操作|
|P4 提交/恢复保证|原子capture、reservation、binding、outbound前持久标记|乱序r12/r11、ABA、unknown crash；反例新key重发|connector controlled-race/first-send/attachment/send outcome；Q01–08缺席此阶段blocked|关闭新提交能力，保留关联/草稿核对；不回滚已发生配置|
|P5 可插拔surface|三个完整插件无需core品牌、raw native命令开放|workflow/同名/无Chat/optional子插件；unknown event降级|真实独立插件build+受控fixture；无native通道只读unavailable|撤新surface贡献，保留owner结果与旧输入draft|
|P6 第三方安全承载|默认隔离renderer/native、每跳预算、commit授权|恶意main module拒绝、伪lease、await撤销、审批视觉|隔离进程/IPC/权限/解析/洪流对抗；缺机制拒第三方执行|撤新lease/禁加载，收尾已commit操作；CSP不全局放宽|
|P7 用户验收/退役|定向真实UI验证后退役旧入口|真实中文IME/焦点/overflow/window按钮；反例尾Enter|产品清单/build、安全、跨窗口、离线history；真实服务/模型需单独授权|按装配快照恢复，关联/未知记录不得删除|

P1为内部迁移；P2及后续明确是行为新增/修正；P3/P4涉及配置语义和协议，P6涉及授权和隔离。不能用移动包路径的回归绿覆盖这些新行为。阶段可分批，但完整权威收束需切换单一写者的受控边界，不能先让两个owner并行生产。

## 5 验证与实施限制

未来测试优先扩已有定向suite，测试必须证明能抓反例；不为重命名机械复制测试。主任务只运行checks标准库状态模型，未运行生产npm aggregate、构建、Electron、真实服务。当前源码及未提交P改动必须实施前重新核验；本计划不覆盖它们，不将P已修改项目归为本轮完成。UI/安全性能验证成本与真实权限另列实施工单，经用户认可后执行。
