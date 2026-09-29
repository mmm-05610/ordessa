**1) 三条以内最重要的问题**

1. `plugins/permissions/backend/src/ordessa_permissions_backend/authority.py:281-297`（`query`）— 只捕获 `PolicyRefusal`，文档声称的"store 不可读 → `ready:false` + 空 records"实际未实现：`availability()` 返回 False 后仍继续调 `effective_for_operation`/`lookup`，底层读异常会原样抛出；`AUTHORITY_STORE_UNREADABLE` 分支零测试覆盖。
2. `plugins/permissions/backend/src/ordessa_permissions_backend/authority.py:236`（`revoke`）vs `plugins/permissions/api/src/ordessa_permissions_api/authority.py`（`PermissionsAuthorityQueryPort.revoke(reason: Any = None)`）— 契约声明 reason 可选，实现强制 `reason: str` 且 `_filter_text(reason) or ""` 把 None 硬转空串再被 `facts.revoke` 深层拒绝：既是契约漂移，又违背本包"refusal, not coercion"的自述；`test_wire_plugin_registration.py` 只断言 `callable(port.revoke)`，漂移测不出。
3. `plugins/permissions/backend/src/ordessa_permissions_backend/authority.py:158-169`（`effective_for_operation` rule 分支）— `digest_q` 完全不作用于 rule 记录，带 `operationDigest` 的查询仍返回无 digest 的规则事实，"narrow 到该操作"的过滤语义名不副实。

**2) fake green 迹象**

未见删断言/跳过/谎报；测试跑真库真路径。但 `plugins/permissions/backend/tests/test_authority_query.py:154` 的 `assert facts.get(grant_id)["approvalId"] == grant_id` 是同义反复——注释声称的"首次撤销生效、reason/时间戳不被覆盖"（`facts.py:revoke` docstring 的核心保证）没有任何断言支撑，属弱测而非 fake green。

**3) 结论**

有保留——写入面未越界（仅 `facts.revoke` 的补列 + 事件追加，无新存储、无第二决策引擎），无 fake green；但 §1 的契约/文档与实现不一致处需澄清或补测后才宜合入。
