# T04-B 第一步：`agents` 能力组 + operation id 迁移（2026-10-21）

## 1. 做了什么

- 新增 `ordessa_agents.capability.agent_group.build_agent_group(*parts)`：把已组装的能力部件合成
  **一个** `agents` 能力（注册表拒绝重复 capability id，这是唯一合法形态）；未组装的部件不会被声明，
  不造假。
- Profile operation id 从 `profiles.*` 迁移到 **`agents.profiles.*`**；Profile 能力自身描述符 id 改为
  `agents`（契约校验要求 operation id 归属于其 capability id）。
- 三处守卫/校验同步：CLI `LocalProfileGuard`、Server `OriginalProfileAccess`、
  客户端 `supportedMethods` 校验均要求 `agents.profiles.` 前缀。
- Server 产品注册改为 `agents` 能力组；默认配置 `capabilities=["agents"]`，默认 grants 为 11 个
  `agents.profiles.*` 精确操作。
- CLI 本地 agent 域与 Server 的 registry helper 都改用 `build_agent_group(...)` 组合 Profile + Agent 部件，
  消除 "capability id 重复" 冲突。

## 2. 顺带修复

- **端口占用变成类型化拒绝**：`bind_loopback_socket` 之前位于 try 之外，端口被占会抛 traceback 退出 1；
  现在与组合错误同一处理，返回 `PORT_ALLOCATION_FAILED` 退出码 2、无 traceback。

## 3. 验证

| 项目 | 结果 |
| --- | --- |
| 零配置启动 banner | `capabilities agents`（不再是 `profiles`） |
| `ordessa … call agents.profiles.capabilities` | exit 0，completed |
| `ordessa … agents profiles create demo --manifest …` | exit 0，catalogRevision 1 |
| `ordessa … agents profiles list` | exit 0，completed |
| CLI + packages_convergence 3 文件 | **98 passed / 0 skip** |
| S-09 安装闭包门 | 2 passed / 0 skip |
| environments + local | 181 passed / 1 skipped |
| pi 品牌 | 71 passed |
| agents 收集 | 1008 collected / 36 errors（与 pristine HEAD 相同，既有） |

## 4. 迁移影响（必须知道）

1. **Profile manifest 的 harness revision 变了**：H2 之后品牌由 `ordessa-agents` 发行提供，
   pin 的 revision 取该发行的版本，即 `0.1.0`（不再是 `ordessa-harness-kilo==0.1.0a1`）。
   e2e 中 manifest 使用 `{"definitionId":"kilo","revision":"0.1.0"}` 通过校验。旧 revision 会被拒绝，
   这是 H2 的直接后果，已在 known-issues 登记。
2. 任何外部调用方若使用 `profiles.*` 旧 operation id 会失败（设计上不留兼容层）。
3. capability id 由 `profiles` 变为 `agents`；`hello`/`capabilities.list` 的 id 集合随之变化。

## 5. 仍未做（T04-B 剩余）

- 实例生命周期 / native / harness 三个部件接入 `build_agent_group`（需要真实 endpoint/preparation/
  lifecycle/interaction 端口，替换现有显式拒绝端口）。
- environments / decisions 两组能力的正式注册；长操作；工具权限。
