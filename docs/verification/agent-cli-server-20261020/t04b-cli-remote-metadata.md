# T04-B：CLI 远程模式公开保留句柄操作（2026-10-21）

## 改动

`apps/cli/src/ordessa_cli/cli.py`：静态元数据改为按模式投影 —
本地一次性进程无法持有 live Use/进程句柄，`environments.acquire/launch/export-endpoint/process-release`
仍隐藏；**远程模式**（Server 持有句柄）全部公开。判定：`remote = --config 指定 或 未指定 --state`。

## 验证

```
ordessa describe environments.acquire --json           → completed（远程默认目标）
ordessa --state /tmp/lm1 describe environments.acquire → refused（本地模式仍隐藏）
```

`apps/cli/tests`：92 passed / 0 failed（未新增失败）。
