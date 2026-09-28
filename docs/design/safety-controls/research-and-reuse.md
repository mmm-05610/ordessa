# Research and reuse decisions

核查日期：2026-09-28。分 **官网当前说法**、**本仓代码事实**、**尚未证实的产品通路**；不能将官网最新版本替换为本仓 pinned 版本的运行证据。

## 官方机制与风险

- [Codex Config Basics](https://learn.chatgpt.com/docs/config-file/config-basic) 将 `approval_policy` 和 `sandbox_mode` 分开；组织 `requirements.toml` 可禁止某些宽松值。`read-only/workspace-write/danger-full-access` 是 Codex 本家的模式，不能转成 Claude 同名布尔值。具体 CLI/App Server/ACP pin 的接受范围仍要用本仓测试核定。
- [Claude Permissions](https://code.claude.com/docs/en/permissions) 的 deny/ask/allow 跨设置层级有优先顺序，managed 设置不可被项目或 CLI 放宽；`default/plan/auto/bypassPermissions` 等是 Claude 原生模式，不代表 Codex 或 Pi 的同等策略。权限覆盖工具，审批与 sandbox 互补。
- [Claude Sandbox](https://code.claude.com/docs/en/sandboxing) 说明沙盒是 Bash/PowerShell/Monitor 子进程的 OS 级限制，不是全部工具；Linux/WSL2 使用 bubblewrap，原生 Windows 不支持。它与普通权限规则交互，不能用其中一层替代另一层。
- [Pi 官方 extensions](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/extensions.md) 和 [permission-gate 示例](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/examples/extensions/permission-gate.ts) 显示 `tool_call` 事件可阻止执行，headless 下示例默认拒绝；[sandbox 扩展示例](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/examples/extensions/sandbox/index.ts) 借 Anthropic sandbox runtime 替换 Bash 操作。它们是示例/可装扩展，**不是 Pi 内建的统一权限/沙盒配置保证**。具体 pin、装载、绕路工具和 ACP 桥必须验证。

## 本仓实际资产

| 候选 | 固定位置 | 复用方式 | 必须补齐/不能误用 |
| --- | --- | --- | --- |
| 审批事实与原子决定 | `plugins/server-compat/src/ordessa_server_compat/approvals/records.py` | 迁入 Permissions 域或明确归属迁移；保留 CAS/事件与一次性决定语义 | 旧表 `server_approvals` 与 ID 不改；`decide` 落账不等于 native 工具实际执行，必须关联接收回执、失联对账 |
| 旧权限规则 | `plugins/server-compat/src/ordessa_server_compat/profiles/permissions.py` | 只迁移输入兼容/测试样本，不原样复用为管理员上限引擎 | 旧实现为 last-match-wins，后来的 allow 可盖之前 deny；跨上级策略必须拒绝提升，迁移歧义项需人工裁决/收窄 |
| 品牌投影 | `plugins/server-compat/src/ordessa_server_compat/profiles/{posture_config,posture_translation}.py` | 逐品牌导入并迁入 Permissions 的 Harness configuration adapters | 旧 Codex `untrusted` 字样可能随官方版本变更，不能照单全收；写盘成功非行为证明；不能把 sandbox 投影混作权限许可 |
| ACP 请求/响应 | `plugins/harness/adapters/acp-adapter/internal/acp/{types.go,server.go}`、`pkg/{piacp,codexacp}` | 保留通道所有者与 `session/request_permission` 往返、取消时序测试 | 目前 Pi/Codex 执行门事实与本包策略门之间尚无生产权威接线证明；不可仅靠桌面端选择校验 |
| 通用插件贡献 | `packages/server-plugin-api/src/server_plugin_api/contract.py` 与平台 C1 交付 | 直接消费公开组合接缝 | 不写第二注册表、不从业务 import `apps/server/plugin_host` 私有类；若缺 pre-effect 接缝，须提出最小公共端口并单独验收 |
| Profile Facet | `docs/design/profile-v2/contracts.md` | 两域分别注册自身 facet、Settings section | 不往 Profile 添加硬编码 permissions/sandbox 字段；Profile 存意图不存管理员权威 |
| Harness 配置意图 | `docs/design/harness-v2/contracts.md` C2–C5 | 按配置 adapter 合同编译、核验；应用由 Harness 控制 | 权限批准是运行时事件，不能只靠 C2 写配置；native sandbox 与权限可分别注册 facet，但同 native 字段冲突须组合期拒绝 |
| 中性执行 sandbox | `packages/pacthold/src/pacthold/extensions/runtime_composition/sandbox_port.py` | **不复用为本业务实现**，仅边界测试 | `SandboxV1` 是 Ordessa execution resource；不是 Codex/Claude/Pi 原生 sandbox 配置 |

未选任何上游源码直接复制。本包对 Pi/Claude/Codex 只借设计与官方接口说明；许可证与 NOTICE 门对未来复制或新增 `@anthropic-ai/sandbox-runtime` 等依赖仍是硬门。当前 Go ACP bridge 自有 LICENSE，但不能凭其存在推定所有依赖可再发布。源码 pin/包版本应在 T00 从集成基线记录，官网是功能上限线索而非实施能力结论。

## Spec Kit 方法

组织方式对照 [GitHub Spec Kit spec](https://github.com/github/spec-kit/blob/main/templates/spec-template.md)、[plan](https://github.com/github/spec-kit/blob/main/templates/plan-template.md)、[tasks](https://github.com/github/spec-kit/blob/main/templates/tasks-template.md)；不是宣称安装/运行了 Spec Kit CLI。
