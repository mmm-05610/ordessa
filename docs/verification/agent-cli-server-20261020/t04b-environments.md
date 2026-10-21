# T04-B：Server 持有 Environment owner（第一步，2026-10-21）

## 1. 已实现并实测

- `ServerInvocation`（`composition/invocation.py`）：把已验证 `VerifiedPrincipal` 与既有 `OwnerScope`
  （`principal: instance:<principalId>`）绑成一次请求的受信调用者；Profile guard 从中取 principal，
  environments 的 authorize 从中取 scope。`RequestContext.invocation` 仍只放 `VerifiedPrincipal`。
- `ServerEnvironmentOwner`（`composition/environment_owner.py`）：在已独占的数据根内组装
  `SQLiteEnvironmentStore(state/environments.sqlite)` + `LocalEnvironmentResourceProvider(state/environments)`
  + `EnvironmentManager` + `EnvironmentCapabilityService`（alias 文件 `state/environment-aliases.json`）。
  授权 = 验证 principal + ownerScope 相等 + grant 含 `environments.<action>`；关闭顺序由产品 owner close 链保证。
- 产品默认能力扩为 `["agents", "environments"]`；默认 grants 增加 22 个 `environments.*` 精确操作。
- 启动 banner：`capabilities agents, environments`（实测）。

## 2. 实测通过（安装版 Server + 默认端口 + 零配置 CLI）

```
ordessa-server --data-root /tmp/w4/root --port 48765
{"event":"listening",...}   capabilities agents, environments
ordessa --data-root /tmp/w4/root environments providers --json     → completed（local available, isolation none）
ordessa --data-root /tmp/w4/root environments create local --root /tmp/w4/work --json
    → completed，identity=environment/a5835ee6…（真实目录）
ordessa --data-root /tmp/w4/root call environments.exec --input …
    → completed：exitCode 0, stdout "hello-from-server", useReleased true
```

即：**进程启动、stdout/stderr 捕获、Use 获取与释放都发生在 Server 进程内**，CLI 只是客户端。
这是"Server 持有下层 owner"的第一个真实证据（不是 fixture、不是 CLI 本地模式）。

## 3. 后续复核（同日更正）

上一轮记录的 `files`/`delete` 失败经复核为**误判**，两个都不是 Server 缺陷：

- **files 实为通过**：在干净 Server 上 `call environments.files`（write/cat）→ completed，文件真实落盘，
  CLI 与原始 wire 两条路径都通过。上一轮失败来自旧服务进程/旧 grants 状态的测量环境。
- **delete 的拒绝是设计行为**：本地 provider 的 `operations = frozenset()`，它不拥有 `stop`/`delete`
  生命周期（用户目录不由产品删除），capability 因此返回
  `INVALID_INPUT: Resource lifecycle refused; user files preserved`。这不是"删除能力缺失"，是"本地资源
  生命周期不属于 provider"。
- `use-inspect` 用环境 identity（而非 use id）也会正确拒绝。

## 4. 仍未做（下一轮）

- endpoint/preparation/lifecycle/interaction 端口仍为显式拒绝端口；instances/native/harness 部件尚未接入
  `agents` 能力组；decisions 未注册；长操作、工具权限未做；OpenShell provider 未接入 Server。
