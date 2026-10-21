# T04-B：两个已登记缺陷修复（2026-10-21）

1. **transport client 拒绝连字符 operation id**（导致远程 `call environments.export-endpoint` 不可用）
   - `ordessa_system_access_client/client.py` 的 operation-id 正则由 `[a-z][a-zA-Z0-9]*` 段放宽为允许连字符；
     服务端本来就发布 `environments.export-endpoint` 等合法 id。
   - 实测：`ordessa call environments.export-endpoint --input …` → **exit 0 / completed**（此前只能走原始 wire）。
2. **CLI 静态 metadata 缺 `agents.cancel` / native 操作**
   - `apps/cli/src/ordessa_cli/cli.py::_metadata` 改用 `instances(include_native=True, include_cancel=True)`。
   - 实测：`ordessa describe agents.cancel --json` 可解析。

回归：`apps/cli/tests` + `test_server_full_stack.py` = **93 passed / 0 skip**；install exit 0。
