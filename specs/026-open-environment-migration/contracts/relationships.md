# E3/F3 — 受管理能力关联、领域单写者与订阅生命周期

2026-10-03用户要求补齐。本合同修订E1/F1，不引入新的核心、服务总线或业务调度器。方法名由002冻结，语义不可省略。R3沿用原12单/96任务；R4显式扩充为114任务，仍同12单，强制交付如下。

## 1. 一个核心，不引入外部业务语义

后端能力发布、绑定、Usage、订阅、调用准入与退出责任统一归Pacthold Environment；使用同一environmentId、activation/generation、admission fence、StorePort和生命周期。禁止独立PluginBus/ServiceManager/RelationshipRuntime另建注册表、授权或停用账。关系管理是Pacthold内部模块，environment-api只提供合同，不持运行状态。Server只代理同一Environment，不复制关系权威。

核心只理解契约身份/版本、目标标识、来源、作用域、调用者、操作类别和生命周期。不得理解Agent、Profile、模型、Skill、MCP、ACP、原生workflow/审批或OpenShell；字段含义、补丁规则、原生协议由插件解释。不得加入品牌枚举、业务currentConfig、native session字段或导入领域插件。新增异协议资源/参与者无需修改核心。

插件可导入公开业务类型与无状态codec，不跨插件导入私有实现，不取得裸provider后绕过准入。同进程受管理调用允许直达提供者，不强迫序列化、网络转发或数据库写入。这不是对恶意同进程代码的隔离保证；真正隔离沿用现有executor/broker合同。

## 2. 发布、发现与绑定

能力描述声明contractId/version、operationKinds(read/observe/mutate)、目标范围及关系要求。实例随激活事务发布，不允许全局set_provider覆盖。

- discover(contractId,versionRange,scope)：只返回调用者可见的CapabilityRef/描述，不返回实现，也不授予调用权限。
- bind(refs,expectedRevision,consumerScope,requiredness,access)：扩充E1既有入口，返回BindingSnapshot及关联Usage。检查双方激活代次、主体、目标、版本、权限、准入；查找到绑定期间提供者变化则明确拒绝，不暗中换提供者。
- required能力缺席/不兼容，依赖它的入口不得发布为可用；optional缺席明确不可用，其他能力继续。多个候选需显式选择或装配给定，核心不猜。
- 激活阶段拒绝required依赖环；运行期等待采用E1 wait的预算与环检查。不得持DB锁等待外部调用，不以同步递归实现关系调度，也不执行有副作用的“可用性探测”。

绑定固定consumer/provider activation与generation、target、access、scope。Ref只定位；提供者重启后旧绑定无写权，须重新显式绑定，contractId相同不能自动继承权限。

## 3. 单写者与读写分离

业务状态由领域owner维护。对authorityKind + CanonicalFactTarget只有一个可写owner；它是Environment能力注册的独占约束，不是第二套状态引擎。目标规范化及别名证据由可信领域插件提供，核心不解析原生会话。

authorityKind即既有factDomainId的语义名称，唯一键仍使用现有CanonicalFactTarget，不新增平行authority namespace。领域目标映射不得让同一事实两套key各自合法写入。

authority身份与契约版本分离；以新schema/major/别名开第二writer必须拒绝。实体区分证据不足则拒绝竞争写入或只读unverified。读取返回不可变快照，禁止泄漏可修改共享对象。消费者只能提交操作，由owner合成、更新、推进版本；表单草稿不算权威状态。

核心不解释patch，也不保存第二份业务currentConfig。原生实际状态仍由原生/Harness拥有；Agent拥有意图和有来源的确认投影，不伪造原生事实。expectedRevision按领域合同核验，不把不可比较native序号冒充CAS。修改接纳、原生配置确认、输入接纳及输出终态仍分开，遵守C1/C2。

## 4. 快照与订阅连续性

readAndSubscribe(binding,target,cursor?,credits)是同一能力的observe操作：提供者交付快照@revision及后继游标，或可证明无缝的回放；禁止先read再无游标subscribe产生漏事件窗口。

核心管理订阅句柄、consumer/provider代次、scope、预算、credit和释放；领域提供者管理业务revision、快照和事件内容。核心只管理envelope来源/ingest，不代替业务状态缓存，沿用E2三序号。

credit不足、回放过期或溢出必须给gap/resync-required，不能静默丢后仍标同步。重取快照清掉旧patch buffer。建立中scope撤销或断线，晚到句柄须释放，释放未明登记待收口责任，不得泄漏。

普通同进程观察可不落盘；崩溃恢复保证通过现有StorePort提供，缺持久实现拒该保证，不禁普通观察。unsubscribe/release幂等；删除本地map不证明责任已释放。

## 5. 三种作用域、撤销与在途工作

插件激活、UI、领域对象三个作用域分别持有Usage。关闭UI只释放其观察关系，不删除对象、不取消已接纳操作。接纳前callerScope必须有效；接纳时将捕获的绑定与必要Usage移交Activity责任，不能只挂在菜单或发起插件上。

消费插件退出不默认取消已接纳工作。provider drain与bind/invoke/subscribe/required依赖发布共用同一准入门；已接纳工作仅按M04在原授权范围收尾。缺退出证据保持retire-pending，不另开第二实例掩盖未收口责任。borrowed只释放本方关系，不停止外部服务。

断线不等于对象结束。重连按权限查原requestId并重新获取权威快照；不创建第二writer、不清unknown、不自动重发。重启后重新绑定需C2/E2身份证据，不足则不可写。

## 6. 前端协作与桥接，不双权威

F1运行底座管理本地UI scope/句柄/槽，Workbench只展示与贡献。已有后端owner的DomainAccess仅代理和只读投影，不重判后端接纳/退出责任，不另存可写镜像。纯前端领域仍可用本地owner，不强迫每次UI观察绕后端。一个事实不能两端各登记writer。

前后端scope经已有Bridge映射，不用新增全局PluginBus自行握手。调用及await后核验caller/lease/target/generation。视图关闭或网络中断只detach，后台Activity由同一Environment管理。

## 7. 领域示例，不是核心schema

Agent发布会话配置read/observe/mutate能力；Profile管理配置清单、Model-provider管理供应商/模型/凭证引用，通过绑定提交操作并观察同一owner。Profile按出现字段覆盖，模型操作只改模型字段，重选Profile是新操作。Harness做原生适配与确认。资源表不等于会话配置。

OpenShell插件发布自己的环境对象/能力，不需要Agent/Profile；关联Agent时由领域插件声明关系。无Agent时仍能创建、绑定、查询和退出，证明核心不依赖Agent业务。

## 8. 实施分配与强制验收

| 工单 | 既有阶段/任务追加交付 | 验收 |
| --- | --- | --- |
| 002 | E3/F3 DTO/公开exports、能力查找/绑定、owner声明、无缝观察、typed错误与Python/TS codec联合冻结 | A67 |
| 003 | 空Environment中异协议能力和纯资源真实公共路径，无Agent/Server/SQLite | A66 |
| 004 | 同注册事务、准入门、Usage、owner独占、scope收口、在途责任、释放与代次 | A68、A69、A70、A73 |
| 006 | Server仅代理，不复制关系权威 | A66、A75 |
| 007 | Harness/资源插件受管理访问，不绕私有调用，可证别名 | A67、A68、A74 |
| 008/009 | UI scope/远程代理、gap/late attach、不双writer | A71、A72、A75 |
| 010 | 配置多入口单owner与原生确认投影，业务不进内核 | A74 |
| 012 | 默认产品与独立外部包全部新增验收回归 | A66–A75 |

本表交付属于原工单codeReady所需S/I证据，不可只冻结接口、拖到012才首次实现。新增修订未取得独立审查或生产行为证明；旧R2审查不自动覆盖本合同。
