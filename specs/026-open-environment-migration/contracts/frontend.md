# 前端公共合同 F1（待002编译冻结）

必须联合遵守relationships.md（E3/F3）：后端authority的DomainAccess仅代理/只读投影；纯前端领域保留本地owner。UI句柄不是第二后端关系核心，订阅连续性、撤销和晚到清理遵守同一合同。

R4联合platform-services.md（E4/F4）的dialog/native能力与诊断接入；Agent领域公开合同见agent-domain.md，不进前端底座。逻辑插件/多入口与通用命令归属见../plugin-architecture.md。

extension-api公开PluginDeclaration、ResourceScope、ServiceToken、Contribution、DomainTargetSchema、AuthorityRef、DomainAccess。extension-runtime负责用Lumino解析依赖，维护唯一权威槽与贡献事务。

registerAuthority(domainId,targetSchema,provider)先可信normalize到CanonicalFactTarget，再acquire槽；同实体不同schema/major不能开第二writer。不兼容消费者typed拒绝。跨窗口authority由renderer共享服务或主进程协调实现，不能每个窗口私建writer；主进程只调度不解释配置业务。

DomainAccess.observe(target)→带owner/revision的只读快照；dispatch(target,op)→操作回执。配置字段schema、解析与提交属于Agent域，不进入平台。非Agent资源、文档、终端使用各自target与owner。

WorkbenchAPI：registerView/registerNavigation/registerSettings/registerOverlay/registerCommandLink/openView/openSettings；贡献绑定scope；业务设置值通过领域service读写。menu全局overlay域不遮窗口控制，Esc只处理顶层可关闭面。

SurfaceAPI：registerSurface(spec)/attach(ref)/detach(handle)/write(inputTicket)/observe(cursor,credit)。spec声明来源、执行域、schema版本、预算和raw/reliable能力；unknown类型原文有界降级，无权限只读不可回答控制请求。

Bridge API独立exports/api；main/isolated-executor实现禁止被renderer公开入口import。IPC每次校caller/lease/activation/target/commit授权，await后重核撤销。第三方模块不得直接作为main任意动态import入口；受信内建明确allowlist。隔离方案缺席拒不可信代码，而非关闭所有内建功能。

关闭视图仅detach；停用owner先preflight→drain→settlement→revoke。存在unknown关联拒直接销毁必需owner，必要恢复实现保留。旧generation dispose不能撤新贡献。

Token carrier构建只生成一个运行对象来源，所有extensions shared import-map指向该来源；隔离域用schema/消息握手，不跨进程传JS Token对象。
