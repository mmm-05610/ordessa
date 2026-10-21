# T04-B：Server 的 agents instances/native 接入（2026-10-21）

## 已实现

- `ServerAgentAuthority.allow/check_instance_lifecycle`；`ServerInteractionAuthority.check_native_dispatch/
  check_read_native_operation/guard_native_dispatch`；`ServerPromptWriteGuard.guard_write`
  （prompt→`agents.prompt`、cancel→`agents.cancel`、native→`agents.native.freeze`，未知 binding 拒绝；
  先 `authority.verify` 再查精确 grant）。
- `ServerInvocation` 的 owner scope 改为 `OwnerScope('principal', principal_id)`，使 `kind:ref` 与 principal scope
  同一拼写（修复 reconcile/stop 的 `LIFECYCLE_OWNER_MISMATCH`）。
- 产品：`build_session_roots`（`root/state/agents/<key>`，0700）、`build_agent_ports`
  （真实 `EnvironmentEndpointResolver` + `PreparationResolver`，preparation 拒绝映射为 manager 拒绝类型）、
  `build_agent_group(profile, harness, instances, native)`；删除 4 个 `Unavailable*` 死类。
- 默认 grants 增加 agents 实例与 native 的精确操作；`InteractionService(native_prompts=catalog.prompt_handlers())`。

## 主控独立复现（真实 Server + 真实 CLI，随机端口/临时根）

```
environments create local → acquire → export-endpoint   → completed
agents.start（Profile revision 0.1.0, sessionMode=fresh）→ completed，state=running，真实 sessionId
agents.get → completed；agents.reconcile → completed（process running）
agents.native.freeze → completed（FrozenNativeRequest + inputDigest）
agents.stop → completed（terminate confirmed）
agents.query → refused PERMISSION_DENIED（无 turn；turn 需 prompt=真实模型）
agents.prompt（坏 params）→ refused INVALID_INPUT（写入前拒绝）
负例：删 token → PERMISSION_DENIED；收紧 grants（无 agents.start）→ refused PERMISSION_DENIED
```

品牌实测：**kilo / pi / claude / codex 四个品牌 start 成功**；hermes 需 prepared `home/config.yaml`（INVALID_INPUT），
dsh 需要未批准的 `dsh-home` root（`harness root is not approved`）；`sessionMode=none` 上游不支持
（`CAPABILITY_UNSUPPORTED`）。失败品牌均记录真实错误码，未伪造 session/turn。

## 回归

新增/更新测试：authority（+6 例）、`test_server_agents_capability_group.py`（45 个 operation id、三组能力、
默认 grants）。回归合计 **112 passed / 0 skipped**；主控复跑 cli+4 集成测试 **99/0**、新测试 **13/0**。

## 未完成（如实登记）

1. `ordessa-system-access-client` 的 operation-id 正则不接受连字符 → 远程 CLI 的 `call environments.export-endpoint`
   不能用，e2e 改用同 token 的真实 wire/1 请求（客户端缺陷，待修）。
2. CLI 静态 metadata 未含 `agents.cancel`/native（远程 `list` 是静态表而非 Server 注册表）。
3. 真实 prompt 回合（需模型预算）与 `agents.native.recorded`（需真实 native dispatch）未做。
