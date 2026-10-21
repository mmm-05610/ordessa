# T04-B：Server 持有 Decision owner（2026-10-21）

## 已实现

- `ServerDecisionOwner`（`composition/decision_owner.py`）：在锁定数据根内组装
  `FilesystemEvidenceStore(state/decisions)` + `DecisionRunner` + CEL 引擎（`load_rules_engine('cel')`），
  `DecisionsSettings` 的 provider 为空 —— ask 类作业明确不可用，不伪造。
- invocation / evidence-scope 使用 Server 的受信映射：`EvidenceScope('principal', owner_scope.ref)`，
  操作白名单为 5 个 `decisions.*`；未配置 ACL 副本。
- 产品默认能力变为 `["agents", "environments", "decisions"]`；默认 grants 增加 5 个 `decisions.*` 精确操作。
- 启动 banner：`capabilities agents, environments, decisions`。

## 实测（安装版 Server + 零配置 CLI）

```
ordessa … decisions validate --job job.json        → exit 0，completed（job/limits 校验）
ordessa … decisions run --job job.json --request-id d3
    → exit 0，completed，result {"answer":"accept"}，evidence.digest sha256:72650b63…
ordessa … decisions query --original-request-id d3 --job job.json
    → exit 0，completed，返回同一 digest 与 result（冷查询，不重跑作业）
```

真实 CEL 规则（`input.score >= 5` 分支）在 Server 进程内执行并落盘证据。

## 边界

- ask 提供方（Jev）未在 Server 配置，`decisions.run` 的 ask 类作业应明确拒绝（未在本次单测范围）。
- 长操作、工具权限、instances/native/harness 部件接入仍未做。
