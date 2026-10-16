# 81 批次的具体接收请求

本组完整切换清单 81 files／141 old Harness import groups。全仓 AST 2190 文件
（排旧 c1 自身／build）发现旧 Harness/provider modules import 为零。
这允许独立退役 Harness 定义片段，尚未证明整个产品或全部原集成测试完成。

1. **Execution packaging owner：类型标记接收。** 原 C3 历史契约测试保留
   `py.typed` 字节/存在断言；目前 Execution agents 全树没有该 marker，
   `pyproject.toml` 也没有它的 package-data。请确认真实标记范围，并在该 owner
   实际源码与 wheel 中发布 marker。Foundation 将把 Sandbox 原断言的接收路径
   指向这个已确认文件；不删断言、不另复制类型包。下一个关闭点：marker
   source/wheel存在且历史字节一致，C3原测试通过。
2. **Interfaces/Server owner：原配置集成测试接线。** 当前产品
   `composition.py:237` 的 `compatibility_plugins()` 明确拒绝，
   `server_contribution_points()` 返回空。Sandbox 25 个原配置/事务/unknown
   行为测试和 Runtime Preferences 5 个原 C4 测试因此仍无可用原装配入口。
   实际 `build_runtime(server_plugins=ServerPluginSelection(...))` 接受显式选择，
   现有 `HarnessContributionAssembly` 能提供原配置 registry handler，但属于
   Server 内部。请给原测试应使用的真实 assembly 接线方式/入口，或确认该
   原跨 owner 测试的归属；Foundation 只改其独占 plugin test helpers。
   不恢复旧 compatibility composition，不把受控测试 assembly 当首发产品。
   下一个关闭点：保留原效果/拒绝/unknown/回滚断言，通过同一个真实 Runtime。
3. **父协调：Prompts 持久引用测试。** `test_resource_manageability_without_profile.py`
   仍需旧 `CanonicalFactTarget/PersistentReference/ReferenceStatus/RevisionSelector`
   和 `publish_reference_set/inspect_incoming/prepare_resource_change/release_reservation`。
   实际 `ordessa_environments` 管理进程和 FileArea/Use，不能替代该关系存储；
   本机当前 source 没有等价接收者。请指定持久引用及 DataArea 的真实 owner 或
   明确修改这项能力目标。该问题不阻止独立旧 Harness 定义退役，不用新中央 API
   兜底。下一关闭点：真实接收能力及原测试，或经用户批准的明确 unavailable行为。

源失败日志均保留。本组没有 skip/删断言、恢复旧链或越区改 production。
向原父 thread 的投递返回 `thread not found`；共享文档及本会话 commentary 是实际
可读交接，不声称请求已经由另一组接受。
