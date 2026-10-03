# 现状盘点与证据索引

2026-10-03。M = main b4bf7cd；P = 产品树 7951bf06 + 未提交内容。精确 HEAD、初始脏清单、源码摘要见 evidence/source-snapshot.json；下列行号均相对于 evidence/source-excerpts.txt 内原文件编号。P 是检查时文件内容，不能用提交 SHA 单独重建。无安装版运行验证。

## 事实链

|编号|树、文件、行|读到的实现|判断及证据级别|
|---|---|---|---|
|I01|M plugins/profile/integrations/chat/src/selection.ts:34–108|selections、lastConfirmed、applyOnSubmit，注释把同 Profile 重选定义为 no-op|与025产品原则8冲突；这是源码语义，不是当下故障复现|
|I02|P 同文件:45–120、154–221|另含登记/错误及回执校验|比M增强，仍为独立Profile意图和确认记录；不能当M行为|
|I03|P plugins/profile/integrations/chat/src/glue.ts:82–104、135–239|bindings、retainedSelections、clickQueues；prepare里创建/关联、登记、核实、应用|界面贡献掌握配置路由和发送门，职责混合|
|I04|P plugins/assets/model-provider/chat-contribution/src/next-turn-client.ts:129–220|pending、sequence、route、undecided；query还写pending|形状转换与领域意图/路由/恢复混合；不能仅换store名字|
|I05|P 同目录/chat-api-entry.tsx:35–63、72–96|读取Profile贡献身份以取得binding/serializer；组件另有queued、lastConfirmed、current|跨插件实现耦合；配置展示存在多个可写镜像|
|I06|P 同目录/selector.tsx:29–64、73–85|目录加载/错误、弹层、资格证据、queued/current输入|弹层草稿和目录缓存合法；实际配置不应由此拥有|
|I07|M plugins/chat/frontend/src/views/chat-page.tsx:61–126、147–183|局部DraftStore、全通知contextRevision；冻结文本/附件；pane切换忽略结果；成功按文本相等清空|已有身份和未知保护可复用；文本ABA及离开页后结果收尾须设计补足|
|I08|M plugins/agent/sessions/src/model.ts:137–220|选中client发送；草稿createAndSend；requestId跨未知保留；accepted不代表执行成功|生命周期/绑定是领域责任；全局selected不得成为冻结命令的新路由|
|I09|M plugins/connectors/acp/src/client.ts:36–40、155–169、650–705、895–925|不投影部分原生事件；models unsupported；原生命令目录|未知事件不应推断配置；开放原生承载需独立于枚举目录|
|I10|M plugins/connectors/ordessa/src/client.ts:45–78、489–500|models unsupported，config.changed未结构化投影|M没有真实模型切换能力，不用P资料宣称M闭环|

检查入口 Profile选择→glue选择记录→提交guard→prepareSubmission建立native绑定→Profile登记/应用回执→model query/观察→各控件展示。P中两个guard与两个队列通过binding/serializer互相协调；不能据此断言某两个转换器是全部根因，也没有本轮实际发送证据。重构将这些入口收束为同一配置领域所有者，投影单向消费。

## 平台、宿主和装配

|编号|树、文件、行|证据与边界|
|---|---|---|
|I11|M packages/desktop-platform/extension-api/src/index.ts:1–45；extension-host/src/runtime.ts:46–136|Token来自Lumino；PluginRegistry为唯一依赖/生命周期调度，关闭scope先于deactivate；复用，不加Workbench加载器|
|I12|M extension-loader/src/index.ts:5–39|模块加载超时、身份校验和重复provider拒绝；超时不隔离已经执行的JS|
|I13|M packages/workbench/src/model.ts:20–60、90–154；api/workbench.ts:17–60|视图/模块/弹层/设置贡献，移除弹层时收尾；Workbench拥有组织状态，不拥有Agent事实|
|I14|M apps/desktop/renderer/host-services.ts:94–109、main.tsx:54–94；workbench/src/model.ts:24、108–125|宿主settings数组与Workbench sections独立，且有两套设置呈现/弹层；统一展示注册入口，值由原领域拥有|
|I15|M contracts/foundation/src/contract.ts:1–14|Workbench/Connections契约单一runtime carrier；包含HarnessAvailability产品契约，语义领域进入平台伞包，应拆到领域，保留旧共享入口迁移|
|I16|M ui-components/src/index.ts:60–95、106–160|组件provider generation、revocable binding、record identity保护；保留机制，不能视为领域owner代际|
|I17|M connections/src/index.ts:24–46|连接尝试独立实例、invalidated与AbortController；传输事实可拥有，不应复制配置|
|I18|M plugins/connectors/acp/src/host.ts:3；apps/desktop/renderer/agent-native.ts:8–11|插件导入宿主内部桥类型，必须迁至公共契约，不能复制类型规避扫描|
|I19|M native-bridge/src/index.ts:20–71、preload.ts:20–29、security.ts:8–28|原生入口open/send/close，校验窗口/frame及frame形状；同renderer插件身份和能力授权不是此校验的结论|
|I20|M extension-host/src/main/extension-protocol.ts:7–38|共享import-map、enabled目录限制、confinedFile、CSP frame-src none；当前没有第三方隔离视图承载|
|I21|M apps/desktop/electron/main.ts:63–70、335–369；server-bridge/src/wire-port.ts:25–48|wire method为数据，凭据在main；普通renderer方法入口不等于独立插件权限|
|I22|M products/desktop/extensions.json:1–19；P同文件:1–26|M启用Profile但无model-provider；P启用model及UI选择；清单差异明确记录，不能推断安装版|

包入口遍历覆盖extension API/loader/host、foundation、ui、ui-components、connections、bridges、Workbench、main/preload/renderer、Agent/Chat/connector/Profile与产品树model-provider。ui为基础控件/CSS，组件注册与替换归ui-components。当前边界测试 products/desktop/tests/contract-ownership.test.mjs:126、242–306，connections-platform-isolation.test.mjs:173–199，product-bundles.test.mjs:65起；spec010 data-model/UI/Connections/组件契约及P spec021 zcode-profile-model-closeout.md:64–74、187–202提供设计/历史材料，均未在本轮运行。

## 盘点局限

spec010/data-model.md 在当前树已演进，不能按数字假定是旧前端冻结状态。024当前公开status处于盘点，不存在可依赖的稳定后端契约。生产包目录存在不等于已安装/已被实际用户使用。所有运行能力和历史验收数字仅为文档引用，未转作本轮实测。
