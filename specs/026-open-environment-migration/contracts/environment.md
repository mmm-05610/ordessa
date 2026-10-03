# 后端环境公共合同 E1（待002编译冻结）

提供者：Pacthold Environment；消费者：Server、领域插件、产品。契约包environment-api零运行状态。建议Python模块名ordessa_environment_api，dist ordessa-environment-api；实际名称须002锁定并检查与现安装不碰撞。

必须联合遵守relationships.md（E3/F3）：能力关联、领域单写者、读写与订阅生命周期属于同一Environment，不建第二关系核心，不引入领域业务语义；扩充入口由002联合冻结。

R4追加platform-services.md（E4/F4）和resource-references.md（E5）：数据/秘密/诊断适配是受管理能力，持久引用扩同关系模型；不将Agent A1业务字段加入E1。源码插件归属见../plugin-architecture.md。

- activate(manifest,principal)→ActivationReceipt：依赖和贡献一事务，失败无可见半组；外部责任单独settlement。
- instantiate(capabilityRef,requestId,descriptor)→CreationReceipt：创建attempt先登记，返回Object/Usage必须连贯交接；未知不再创建。
- bind(refs,expectedRevision)→BindingSnapshot：scope/owner/代次核验；历史Ref没有invoke权限。
- invoke(surfaceRef,requestId,principal,binding,input,guarantee)→ActivityReceipt：参数指纹/请求占位按保证执行；同key不同输入拒，unknown只查。
- use(objectRef,purpose)→Usage；release(usageRef,evidence)：释放不自动kill borrowed。
- query(activityOrRequestRef)、lookup(objectRef,mode=history-read)：只读独立权限；不得用read-or-invoke混合重放。
- subscribe(surfaceRef,cursor,credits)→事件envelope：来源identity/序号/gap，关键事实不可默默丢。
- reply(controlRef,responseSlot,expectedVersion,answer)→回执：可信控制来源、principal、单消费，普通输出不产生审批。
- drain(activationRef)→CutReceipt；retire(activationRef,closureEvidence)→已退出或待完成：原权限范围内收尾，不得重开新business入口。
- wait(activityRef)为观察接口：实际跨活动等待登记、预算/环检测；不实现Agent协作业务。

StorePort：transaction、reserve_request、commit_activity、commit_creation_and_usage、append_receipt、read_current、lookup_history、claim_response_slot；不跨外部调用持DB事务/锁。每项隔离实例，禁止模块级configure_database。

PolicyPort负责环境入口与对象访问；native内部审批不纳入核心业务。持久Store/fingerprint/Policy可选注入，但没有对应能力不可宣称该保证；无policy按显式安全默认拒effects，资源只读是否允许按装配声明。

旧CoreStore(path)消费者迁产品提供的SQLite工厂；旧facade可保submit/query等兼容入口但只转同Environment。不能为签名兼容把具体SQLite实现重新导入核心。
