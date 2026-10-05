# 原 Unit 记录的唯一公开引用

冻结于 AU003 共享检查点：`UnitReservation.public_ref` 返回不可变 mapping，严格四字段 environmentNamespace/unitId/ownerProviderRef/sourceRevision。unitId 是原 journal 分配并保存的 Unit 身份；ownerProviderRef 是原 prepare InvocationContext 核实后写入的完整 provider 引用。sourceRevision 为原 unitId、既有 intent digest 与 scope digest 的 SHA-256 来源摘要，不是 native session、配置 actual 或新的可写版本计数。

该引用从已经核实的原 UnitReservation 生成，prepare 可以使用 `reserve_unit` 返回的对象；观察端口必须从同原 journal 的授权读取获取对象。`UnitRecords.resolve_unit_reference(ref, query_context, input_digest=...)` 使用既有 read_unit/ScopeAuthority/Verifier/epoch 核验，再比较全部四字段，不能只取 unitId、删掉 owner/source 或相信消费者复制的 fields。字段缺失、额外字段、owner/generation、来源或环境不同均拒绝。该方法不派发、不建第二缓存、不修改旧表或 native 事实。

公开身份不含 privateRootFacts、scope 路径或运行凭据。session 从 opening→confirmed 或配置 attempt 变化不会改变这个固定 Unit 来源身份；当前 native/session/configuration revision 保留各自 owner 观察版本。原 Unit intent/scope 损坏必须经现有读核验拒绝，不能由引用本身证明权限。

Pi/Codex/Claude 独立包应返回与消费此唯一来源引用。可信 projection.read_unit 负责原授权读取；提供者再核对读取对象的 public_ref 与完整收到引用相等，不能只核 family/unitId。prepare 返回这个引用，start/configuration/access 等入口传递原引用，旧两字段引用不得当完整来源成功。测试 fixture 可以给显式受控 public_ref，但必须记录它不是生产 owner/native 证据；包不能导入 Harness 私有记录模块来复制生成算法。

共享主执行者负责真实 Core+UnitRecords+family 贯通与串行 pytest；家族执行者仅各自包/测试，compile、collect、diff-check。本冻结不提供 Claude sessionless Unit 确认、不新增 native truth 或宣称 P/M 通过，三家生产 projection、writer fence 和生命周期仍待完成。
