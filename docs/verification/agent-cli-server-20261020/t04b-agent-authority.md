# T04-B：Server Agent lifecycle/interaction authority（2026-10-21）

## 已实现

`apps/server/src/ordessa_server/composition/agent_authority.py`：

- `ServerAgentAuthority`：`principal_scope / check_start / check_lifecycle_write /
  check_read_instance / guard_instance_lifecycle`。
- `ServerInteractionAuthority`：`principal_scope / check_read_binding / check_read_turn /
  check_send / check_cancel`。
- 每次检查都 `authority.verify(principal)`（撤销立即生效），并要求**精确** operation grant
  （`agents.start` / `agents.prompt` / `agents.query` / `agents.cancel` …），无通配、无回退；
  收到的不是 `ServerInvocation` 时拒绝。

## 验证

新增 `tests/integration/packages_convergence/test_server_agent_authority.py`：**5 passed / 0 skip**
（GREEN_NO_SKIPS）：

1. 正确 principal_scope；已授 start 通过；未授 `agents.stop` 的 guard 拒绝。
2. 未授 start → `START_NOT_AUTHORIZED`；未授 prompt → `SEND_NOT_AUTHORIZED`。
3. `agents.prompt` 通过 send，但读 turn 需 `agents.query`；只有 query 时读通过。
4. 撤销后所有检查（含 principal_scope）立即拒绝。
5. 传入非 ServerInvocation 对象被拒。

## 尚未接线

产品仍用显式拒绝端口占位；下一轮按 `NEXT-PREPARATION-PORT.md`：端点/preparation 端口上提 +
把这两个 authority 装入 `AgentOwnerInputs`，再把 instances/native 部件并入 `agents` 能力组。
