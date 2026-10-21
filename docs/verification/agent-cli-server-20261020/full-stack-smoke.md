# 正式装配全栈冒烟（2026-10-21）

一个 Server 进程 + 零配置 CLI，三组能力端到端：

```
== startup ==
{"event":"listening","origin":"http://127.0.0.1:48765", "serverId":"ordessa-21d7ef35"}
instance token …/secrets/http-token (generated, 0600)
capabilities agents, environments, decisions

== harness ==      status completed ['kilo','pi','claude','codex','hermes','dsh']
== profile create == status completed rev 1        (manifest revision 0.1.0)
== env exec ==      status completed stdout 'smoke-ok\n'   (Server 进程内执行)
== decisions run == status completed result {'answer':'accept'}  (真实 CEL)
```

另：本轮把 `ServerAgentAuthority` / `ServerInteractionAuthority` 真正装入
`AgentOwnerInputs`（此前只是独立适配器）；endpoint/preparation 仍是显式拒绝端口。
回归：CLI + packages_convergence 3 文件 + authority 测试 = **103 passed / 0 skip**。
原始输出：`raw/full-stack-smoke.txt`。

## 已固化为可重复测试

`tests/integration/packages_convergence/test_server_full_stack.py`：在测试用解释器所在的 venv 内启动真实
`ordessa-server` 控制台脚本（临时根、随机端口、零配置），读 handshake 后经 `ordessa` 客户端依次执行
harness list → profile create → environments create/exec → decisions run，并断言
stdout `full-stack-ok\n`、`{'answer':'accept'}`、token 文件 0600。**1 passed / 0 skip，约 2.4s。**
回归合计：CLI + pkgconv 3 文件 + authority + full-stack = **104 passed / 0 skip**；S-09 = 2/0。
