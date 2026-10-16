# Engineering — 本轮公开契约与跨组消费请求

## 真实入口

唯一原 Facade 实现已迁到 `ordessa_engineering.application.api.EngineeringService`。
`application.usecases.facade` 退役，无 alias/shim/回退实现。原 SQLite UoW、command
journal、grant、review、submission、Work、CAS 及数据标识保留；没有另建状态权威。

调用入口是 `await service.execute(operation, parameters, admitted_context, read_set=...)`
和 `await service.query(query, parameters, admitted_context)`。请求者不得选择具体来源、
reviewer、records、数据库或确认政策；`ActorRef` 仍不认证。

公开 `EngineeringService.input_schema(operation)`、`supported_commands`、
`supported_queries`、`operation_capabilities()` 描述有限真实入口。20 core commands 及其
owner 原 input schemas/outcomes 保留；描述不是 access grant、production catalog
或方法发布证明。`record_report.completed` 仅提交 `pending_review/accepted=false`。

新增 `service.bound_operation_capabilities()` 返回本实例实际选择的原用例与端口
所支持的描述子，按稳定顺序输出。未绑定 Work、确认／审核、报告或原生派工来源时，
对应 operation 不进入该投影。Server catalog 只需将它与实际 callable registrations
取交集，不必读取 `_work`、`_commands`、`_packages` 等内部对象。这个投影不验证
某次输入、不发 Grant、不代替运行时 admission，也不代表方法已经发布。

公开 `application.api.bound_review_check_capabilities(original_admission,
expected_factory=selected_factory, expected_access=selected_access,
expected_scope=selected_scope)` 描述原 MixedReviewerSource 中实际映射的
mechanical/invariant/Decision 检查来源。owner 内核对选定 factory 的同一对象、
composite access/principal 关联及 realm/project；这些装配校验不认证或授予权限。
实际注册归产品 catalog，当前权限和 reviewer trust 仍经原运行时 guards。
详见 CATALOG-CLOSURE-REQUEST.md。此为 amendment 75 源码合同；rev74 wheel
不实现新增签名，新版测试与 wheel 交付等待串行窗口。

构建入口：

```python
from ordessa_engineering.application.assembly import EngineeringPorts, build_engineering_service
service = build_engineering_service(original_factory, EngineeringPorts(
    access=original_access,
    # 由 apps 选择的实际端口实现，可显式注入其余命名依赖。
))
```

assembly 仅接收应用需求侧 ports，不 import adapter、execution、interface 或 plugin。
可选 ports 缺失继续按原 owner 拒绝，不合成可信来源。实际 port 字段及 Protocol
见 `application/contracts/service_ports.py`；原 factory 生命周期仍由 composition 管理。

`application.assembly.build_method_run_bindings(factory, *, method_control,
work_condition_source, registry_loader)` 返回原 MethodRunBindings。来源必须声明原
factory 并提供三个 Work guards；builder 不调用 loader，也不生成 Work facts。
`build_review_check_admission(factory, *, method_control, blobs, review_bindings,
records, unit_review_bindings, unit_reviewer_authority, composite_reviewer_authority,
expected_access, expected_scope)` 在包内组装真实 Mechanical、DeclaredInvariant、
GenericDecision(UnitReviewCheckSource) 和原 admission；whole-review JEV 不能代替它。
API 重导出同一个 `OwnerOperationResult`、`UnitReviewBinding`、
`UnitReviewBindingResolver`、`UnitReviewerAuthority` 与 `MixedReviewerAuthorityPort`，
供需求侧端口实现和一次 wire 投影；没有复制 payload/result 或状态权威。

`application.assembly.bind_execution_dispatch(service, *, execution, selection,
source_snapshots, history_sources)` 在暴露服务前一次性绑定实际 canonical owner，
包内复用 service 原 package/report/approval/MethodRun/records/blob 对象。
返回原 `EngineeringOwnerOperations` 的 factory/access/execute 端口；已绑定或原对象
不一致时拒绝，不替换。Apps 不读取 service 私有字段，也不把旧 dispatch routes
重命名为此 canonical owner。精确公开参数和边界见 PUBLIC-SEAMS-75.md。

## 跨区请求（工程组没有争写）

新增已可消费入口：`service.query("engineering.reviews.get_request", {"review_id": id}, ctx)`
返回 `{"request": 原 ReviewRequestState, "plan": 原 ReviewPlan}`。读取经原 access、
scope、同一读 UoW；不把历史Plan/Request读变成当前review trust。接口只负责线上表示与
human_review projection，不再自己读取这些repositories。

条件实施端口：`EngineeringPorts(implementation_routes=原routes)` 的 factory/access 必须
与service原authority同一对象，原 invoke/Unit/effect guards保持；所有调用先经service
access gate。`execute`支持条件 dispatch/reconcile，`query`支持条件 get_dispatch。
详见 `application.contracts.implementation_routes`。返回原payload/result，不转译成工程接受。
缺绑定明确 OPERATION_UNAVAILABLE，未加入已发布method descriptors。不开放旧独立
`implementation.start_run` 或旧 `submissions.record` 到新gate；当前MethodRun package_slot绑定和report入口已实现，生产来源仍须装配。

1. 接口组更新 `packages/interfaces/system-access/bindings/src/ordessa_system_access_bindings/engineering_wire.py`
   中 `EngineeringFacade` import/构建为新 `EngineeringService` 或上述 assembly；对应
   `apps/server/tests/test_engineering_slice.py`、`test_engineering_report_ports.py` 的旧路径和
   monkeypatch 名称同步。本工程组仅改自有 package callers。
2. Interface/Execution owner 继续提供确切 method-work/report binding、current reviewer
   authority、native Records query_factory 与明确 dispatch/package/Unit/output refs。
   实际效果派发仍由原 `ImplementationDispatch` + Unit authority，不将 RPC completed
   推导为工程接受，不把未绑定旧 owner_operations 描述放入生产 catalog。
3. 原 `SubmissionSourcePort` 要求 tree/test/effect provenance 的文字已改为 method-required
   docs/reports/current immutable source guards。对应接受来源目前仍缺实际生产实现；
   缺 source 的 `acceptance.adopt` 继续明确拒绝。产品 source 不得恢复执行代码/Git 扫描。
4. 原生 Records adapter 当前依赖 `ordessa_units.public` 的 EffectWriteGuard/UnitServices，
   以及 Profiles/DirectoryBindingRef 的公开服务。Execution 公开 API 若变动，请给实际
   文件、类及签名再串行切接，不用新中央 API 代替责任模块。

## 已确认差异与仍未闭环

- domain/methods 现有组织保留；二者须互不依赖。methods 的 definitions/loading/validation/
  compilation 机制无第二 MethodRun authority。
- 外部策略归根 methods；alternate-method 有真实 loader/validate/compiler 验证。
- 旧 `EngineeringWorkflow` 与DID专用helpers已从包内源码删除；CAS归当前Work。原五测试
  逐字归档，通用约束映射与未覆盖项见 orchestration-luna/OWN-BEHAVIOR-MAPPING.md。
  独立 `ImplementationDispatch.start_run` 创建与旧descriptor resolver均已删除；
  实際效果owner缺当前Work/package来源时明确拒绝，不回退implementation-run。
  历史行/材料仍可读。根历史C09 examples的消费者清理由父协调者核对；当前原方法节点/package_slot绑定见 FIRST-EDITION-API.md。
  证据见 `orchestration-luna/RETIREMENT-REVIEW.md`。
- 方法2.5.0仍为 candidate，保留历史 bytes；其完整compile/publish/registered catalog
  及真实 Pi/JEV 串行产品链路尚未证明。

Work.start来源契约已收紧：`WorkSeed(slots, read_set)` 必需持有owner生成的原
`ReadSet`，其scope必须与context一致；在原write UoW中、写marker/run前重检，
并再次比较registry identity。caller read_set独立保留，原method selection/control
guard保留，不合并/丢弃冲突期待。没有新存储；外部依赖必须由来源自身guard持到
COMMIT，不宣称跨存储原子。两连接竞争实测见work-start-snapshot.log。

当前source-closure registry revision及精确digest以CAPABILITIES.json/registry-current-owned-pin.json为准（未发布，后续自有源码变动会再次递增）：删除九个旧DID runner策略名字，
只描述Service实际20个handlers的schema/outcomes；不意味着production注册。

## 通讯记录

已尝试对 delegation source thread 发送消费请求；当前 app 工具对该source id返回
thread not found/no rollout，未声称投递成功。本文件供父协调者直接消费；平台会在本任务
结束时通知父任务。没有发往其他人的消息。

当前 canonical native dispatch 经 `execution_dispatch` port 保持原 owner result。
新增 `engineering.work.record_dispatch_step` 在原 UoW采纳原 dispatch completed/failed，
核对方法输入、run/step/attempt、package、unit/action、原ACP payload和result blob。unknown拒绝推进，
不重派；共享原step log/receipt/round/cursor写切点。旧 `SubmissionUseCases.record`、
OwnerOperations.record_submission与其旧execute/descriptor均物理退役；历史codec/rows保留。
