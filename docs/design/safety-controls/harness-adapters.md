# Harness adapters：三品牌差异与证据矩阵

矩阵为设计输入，不是当前产品通过声明。证据等级：D=2026-09-28 官方文档；S=本仓固定代码可见；L2=本仓受控路径验证；L3=产品真实端到端。**没有 L2/L3 就不宣称生产权限或隔离已接通。** T00 须补当前集成 SHA、包版本和可执行 pin；本仓官方桥 Go 测试不自动证明 Server 侧全链。

| 品牌 | 权限/审批官网能力 | 原生 sandbox 官网能力 | 当前 Ordessa 证据 | 适配裁定 |
| --- | --- | --- | --- | --- |
| Pi | 官方可通过 `tool_call` extension 阻断；`permission-gate` 是示例，不是内建托管规则 | 官方 `sandbox/` extension 示例替换 Bash，依赖外部 sandbox runtime，不是 Pi 内建全工具隔离 | S：Go bridge `pkg/piacp` 与 `session/request_permission`；缺 Permissions 权威生产接线证明 | 首版仅对已验证可拦截的工具/扩展组合开放；无 extension 或插件失效时强制策略拒绝，不能回退为裸 Pi |
| Codex | `approval_policy` 与规则/管理员限制由 Codex 自身定义；本仓桥可映射审批请求 | `sandbox_mode` 及网络/可写根等随原生版本/平台；不与 Ordessa `SandboxV1` 混同 | S：桥 `pkg/codexacp`、`types.go` 有 policy/sandbox 字段与请求；固定版本接受值、配置注入及全链效果未验证 | 分别编译权限与 sandbox 字段；受管理设备 requirements 不可提升；`danger-full-access` 被上限禁用时拒绝，不尝试旁路 |
| Claude Code | 原生 deny/ask/allow、managed 上限、mode；支持审批；不同 mode 不能和 Codex 一键等价 | 官方 Bash/PowerShell/Monitor 沙盒，Linux/WSL2 bwrap，macOS Seatbelt；非全工具 | S：本仓 Claude 官方 adapter/packaging 存在；从当前 ACP/Server 到原生权限/沙盒收据仍需 L2 | 只写原生允许范围内的字段；`permissions.deny/ask` 与沙盒字段分别所有；不得把 `bypassPermissions` 或 auto 当同一“YOLO”跨品牌输出 |

## 官方来源与版本注意

[Codex config basics](https://learn.chatgpt.com/docs/config-file/config-basic)；[Claude permissions](https://code.claude.com/docs/en/permissions)；[Claude sandboxing](https://code.claude.com/docs/en/sandboxing)；[Pi extensions](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/extensions.md)、[permission-gate](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/examples/extensions/permission-gate.ts)、[sandbox example](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/examples/extensions/sandbox/index.ts)。官方文档可能晚于 Ordessa pin；拿源码/受控测试再填 supported。

## 逐品牌测试填表（实施时必填，不得跳过）

每一格记录 `harness binary pin`、`native/adapter version`、`OS`、`entry point`、`tool coverage`、`administrator ceiling`、`scope (request/session/process/project/user)`、`application path`、`reset/default`、`observed receipt`、`negative probe`、`cross-session impact`。无法证明的格写 `UNKNOWN`，不以品牌大类推测。

至少六个横向反例：上限 deny 被用户 allow 尝试放宽；运行中切 Profile；两个会话不同上限；审批失联；原生 sandbox 只罩住 Bash 却试图宣称 MCP 隔离；Pi 扩展缺席却 UI 显示安全。所有反例须在**工具副作用之前**可观察拒绝。
