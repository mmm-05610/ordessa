# E4/F4 — 数据空间、宿主交互、秘密与诊断

R4设计补充；002冻结公共类型，005/008/009实现平台适配，007/010迁消费者，012验收。实现未开始。沿同Environment/F1管理绑定/准入/scope，不新增宿主核心或业务存储引擎。

## 数据空间

DataAreaPort公开claim(namespace,access,schemaDeclaration)、open(handle)、close(handle)、inspect(handle)，由装配注入文件/数据库/外部存储实现。Environment为合法activation绑定能力和Usage，底层适配不另建插件激活账。namespace由稳定领域/发行身份与产品数据映射决定，不用窗口ID、activation generation或物理路径代替数据身份。现有磁盘标识保持，路径搬源码不搬用户数据。

DataAreaDescriptor含areaId、namespace、ownerDomain、backendKind、supportedSchemaRange、currentSchemaEvidence、access、persistenceGuarantee、retention；实例handle另含activation/generation、scope。调用者不能选择其他插件namespace伪装拥有者。共享数据必须显式授予受限合同，不默认给所有插件完整data_root/database；临时测试/内存能力不要求持久端口。

插件拥有业务表/内容与迁移步骤，底座只组织排他访问、迁移准入与安全记录。迁移先取得同Environment写入门和存储排他证据，获许可再备份/执行；不能持环境DB锁运行插件代码。插件迁移外部效果失败/未知保留记录、关闭相关写入口，不自动rollback覆盖数据，不把构造数据库当隐含升级授权。升级后旧二进制超出支持范围只读或拒绝；兼容性由明确合同声明。

关闭handle/插件卸载释放访问关系，默认保留数据；删除/purge是独立有授权的效果，与普通retire分离。owned临时目录可依原创建合同回收，持久用户数据不能借临时目录标签删除。领域库独立，核心StorePort仍只存环境事实，不能把所有CRUD强制写入core_execution。

默认提供文件与SQLite适配的公开工厂，SQL事务/锁域/CAS由实现声明并验证；读后rename只保证原子替换，不自动保证跨进程CAS。文件路径型授权对可信代码不是恶意同进程隔离。真正隔离需已有broker/executor证据，缺席拒对应保证。

## 宿主交互

Workbench公开requestConfirmation/requestDialog，内容由插件贡献，框架保证来源标识、overlay/focus/Esc规则与请求scope。native-bridge公开chooseFile/chooseDirectory、clipboardWrite/openExternal的受限能力；Electron实现OS效果，普通Web可声明unsupported。它们不访问插件私有全局变量，不是新UI调度器。

请求含operationId、callerActivation/generation、scope、purpose与声明的选项；结果为selected/confirmed、cancelled、revoked、unavailable、failed或unknown。cancel零领域写；调用及await后核验scope，晚选择不能自动导入/注册项目，返回的资源handle需释放或登记cleanup未明。已有对话框在停用时关闭或等待受限收口，不能阻挡窗口控制。

选择路径不是对任何Agent/插件授予读写权；后续打开、项目注册、上传由业务能力各自授权。普通确认只是用户选择，不是工具审批、Policy授权或native ControlDeliveryFact。clipboard操作需明确用户动作/能力范围；正文不进入诊断。项目列表、导入格式、影响判断和确认文案仍归业务。

## 秘密能力

SecretPort扩充既有SecretStore合同；提供store/import、describe、borrowForUse、revokeAccess、delete，字段为opaque SecretRef/revision/ownerNamespace/accessPurpose，可用性为available/locked/unavailable/unknown。ref不含秘密内容或可直接绕权限的native locator，知道ref不等可读取。

读取秘密限定可信执行侧：每次核验principal、activation、purpose、目标与代次，短期借用归Usage；普通renderer只能管理引用，不可通过代理获得明文。Profile/Provider管理用途、展示及资源关联；Harness负责原生登录/刷新/协议；核心不解析token格式、不模拟账号登录。

操作系统keyring/DPAPI/file-test实现是可注入平台适配，Pacthold只管理绑定与授权。锁定/缺实现明确拒秘密需求路径，不能回退明文文件或临时全局环境变量；纯无秘密功能继续。秘密导入需授权且不在启动扫描中偷偷读取用户文件。

引用版本固定，轮换产生新revision；旧可靠请求的MAC比较能力按C2保留，删除密钥不消除spent墓碑。撤访问不等从原生进程撤回已交付秘密，不作此安全承诺；在途borrow/持久引用参与删除准入。跨OS存储与元数据Store不承诺原子事务：登记操作意图与确认，结果未知只核对原ID，不重复导入/删除。

## 日志与诊断（复用013 C04/C06）

Logger/DiagnosticProvider经公开受管理能力或F1 scope注入；记录最小eventId、sourceActivation/generation、operation/activity关联、code、时间、safeFacts。业务提供结构化白名单事实和敏感字段声明；底层sink二次脱敏，不能把未知原生payload/String(error)直接当安全日志。核心不解释Prompt/Model内容。

默认不记录秘密、用户消息/文件正文、配置敏感值或完整locator；无法判安全则只记来源/代码和摘要引用。日志不是Receipt/FactView第二主账，诊断收集只读，不能导致probe/login/apply/重发。日志故障有health/drop统计，不推导业务成功或unknown；权威Store写失败仍按C2处理，不能用日志“不抛”规则吞掉。

诊断导出显式用户动作/许可；供应者超时返回unknown片段，不把缺席当健康。scope停用撤收集入口，late片段核代次且有界，插件不得经诊断获取额外秘密权。保留已有C04/C06约束与格式兼容，迁移不重写整个日志系统。

## 公开实现落点

backend/environment-api声明中性Ports/DTO；backend/pacthold现有能力/Usage/admission/lifecycle管理它们。backend/platform-services是可选平台适配包（文件数据空间、OS秘密、诊断sink），无Environment/插件激活注册表，不是第五个核心。SQLite实现继续backend/persistence-sqlite，通过相同Ports接入。

frontend/extension-api公开UI服务合同，Workbench呈现普通对话框，native-bridge负责OS能力。各域业务Schema留插件；新底座包名/发行名由002核对后冻结。旧SecretStore公共导入若需兼容用薄forwarder到同实现，不复制代码或反向导入业务。

## 门与反例

| 门 | 正例 | 反例 | 缺席/未知 |
| --- | --- | --- | --- |
| 数据空间 | A插件只访问自己的稳定area，卸载后字节保留 | 选择B namespace/源码移动换数据根/卸载purge→拒 | 缺持久实现拒持久保证，纯内存继续 |
| 数据迁移 | 声明版本、获批排他/备份和结果，旧代码拒写新schema | 构造时静默迁移/旧writer仍写/失败自动覆盖→拒 | 无许可/完整性证据BLOCKED写入 |
| 宿主交互 | 用户选择后仍有效scope才交付 | late选择自动注册/普通确认变审批→拒 | unavailable不造选择；未知不自动重做 |
| 秘密 | 限定purpose可信侧借用，renderer只ref | locator即权/锁定回退明文/日志泄漏→拒 | 锁定或未明拒相应秘密需求 |
| 诊断 | 只读有界脱敏、权威结果不变 | collect执行probe/日志改执行结论→拒 | 片段unknown，不伪healthy |
