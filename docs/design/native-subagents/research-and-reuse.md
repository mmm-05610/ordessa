# Research / reuse decisions

2026-09-28 查阅上游**官方**文档/官方示例；这些事实是当前官网口径，仍须以 Ordessa T00 锁定版本和实际 ACP 入口验证。外部源码借鉴不等于获准复制；如移植，先固定 commit、源文件、许可证/NOTICE 和依赖闭包。

## 品牌事实

| 来源 | 官方证据 | 对本设计的含义 |
| --- | --- | --- |
| [Claude Code custom subagents](https://code.claude.com/docs/en/sub-agents) | `~/.claude/agents`/`.claude/agents` 文件；Markdown frontmatter 描述工具、模型等；plugin-scoped 定义会忽略 `hooks`、`mcpServers`、`permissionMode`，未知 frontmatter 可静默忽略 | 必须选真实会尊重所承诺字段的入口；不能仅看输出文件即声称工具/权限限制生效 |
| [Codex custom agents](https://learn.chatgpt.com/docs/agent-configuration/subagents) | 用户/项目 `.codex/agents/*.toml`，`name`、`description`、`developer_instructions` 必填；可配模型、sandbox、MCP 等；子代理继承/覆盖规则仍受父会话运行时限制 | TOML 转换有现成格式可借鉴，运行权限需重新裁决，不能从本记录提升 sandbox |
| [Pi extension docs](https://pi.dev/docs/latest/extensions) 与 [官方 subagent example](https://github.com/earendil-works/pi/tree/main/packages/coding-agent/examples/extensions/subagent) | Pi 通过扩展注册工具；示例在单独 Pi 进程里运行子代理并有 agent Markdown 文件与 workflow presets | 这是 extension-backed 方案，不是 Pi 内建定义格式。示例的进程/工作流代码不应当搬入本业务内容插件 |

Claude 官方文档随版本变化，Codex 文档也提示定制 agent 格式可能演进。Pi extension 以主 Pi 进程 OS 权限运行，官方明确需只加载可信来源；因此不能把用户导入的“定义”变成可执行 extension，也不能直接安装远端扩展以换绿。Hermes/OpenCode 等未来品牌均填未知，不能借同名“agent”推断语义。

## 逐模块复用决议

| 模块/任务 | 现有具体位置 | 方式 | 必须补/禁搬 |
| --- | --- | --- | --- |
| 原生品牌启动/会话身份 | `plugins/harness/src/ordessa_harness/{claude,codex,pi}/`、`runtime/access-entry.mjs`，以及 `docs/design/harness-v2/contracts.md` | 消费 Harness 的公开 C1/C2；仅搬品牌配置翻译的已验证部分 | 不重建 ACP relay，不 import Harness 实现私类；核 ACP 实际是否可调用子代理 |
| 旧子代理工具语义 | `plugins/server-compat/src/ordessa_server_compat/profiles/subagents.py` | **只读盘点/数据迁移参考** | `grant_edges`、roster、`run_subagent`、cycle/timeout 属派工授权，不复制进资产插件；旧授权不等于定义选择 |
| 内容库存、安全检查 | `plugins/server-compat/src/ordessa_server_compat/assets/{records,catalog,skills}.py`，Skills v2 T03 的实际交付实现 | 按符号复用内容摘要、CAS、归属/审计模式 | 不复制 `server_assets` 整仓或自建统管 AssetsService；若共享模块真实存在才复用，否则保留本域轻量 store |
| Profile 贡献/编辑器 | `docs/design/profile-v2/contracts.md`，集成后 `plugins/profile/` 实际导出 | 直接消费公开 facet/UI 接口 | 不重新存 Profile、overlay 或渲染第二个 Profile 管理器 |
| 前端 UI/Chat 菜单 | `packages/desktop-platform/contracts/{workbench,agent-ui,commands}/`、`plugins/commands/shared/registry.ts`、`plugins/chat/` | 依公开贡献点/基础控件组装 | `plugins/commands` 是泛命令注册，不是子代理内容库；不因定义生成未授权命令 |
| Pi 示例扩展 | 上述官方 `examples/extensions/subagent/{index.ts,agents.ts}` | 仅借鉴能力探针和隔离/取消反例；Harness 端另审执行依赖 | 不直接 vendoring 示例调度器+workflow presets；版本/许可证/权限/取消与资源记账必须单独核实 |
| 版本化定义存储与范围解析 | 本包 `data-model.md`、`contracts.md` | Ordessa 自实现薄领域逻辑 | 不能用 Profile 旧 grant table 充作定义权限，不能并入 Pacthold/Server |

## 复用实施门

T00 固定 main/平台/Profile/Harness/Chat 的集成 SHA 和公开符号；T01 保存上面每个实际源文件/测试、许可证和可复用单元核对表。优先直接依赖现成契约、其次迁移本仓已有安全检查，外部官方示例优先仅借鉴设计。若某模块缺公开接口，应报告精确 DTO/调用者/失败反例给其所有者，先完成本域可独立内容与测试；不偷建第二宿主或修改核心。实在需要移植第三方文件，先核 SPDX、固定 SHA、NOTICE，再写改造测试；本方案本身不批准源码复制。

Spec Kit 结构遵循 GitHub 官方 [spec](https://github.com/github/spec-kit/blob/main/templates/spec-template.md)、[plan](https://github.com/github/spec-kit/blob/main/templates/plan-template.md)、[tasks](https://github.com/github/spec-kit/blob/main/templates/tasks-template.md) 模板的用户故事、需求追踪、研究决策、阶段依赖和验收思路，不使用派工单流程。
