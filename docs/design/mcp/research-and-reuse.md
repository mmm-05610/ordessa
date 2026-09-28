# Research and reuse ledger

日期 2026-09-28；官网资料为当日检索的**文档事实**，不是锁定的产品运行证据。外部项目若要直接依赖/移植，T00 必须补固定 tag/SHA、包版、许可证与供应链审计；本包当前不授权源码复制。

## 标准与产品事实

| 来源 | 可采纳事实 | 本方案的限定 |
| --- | --- | --- |
| [MCP 2025-11-25 Transports](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports) | 标准传输 stdio 与 Streamable HTTP；HTTP+SSE 为旧版兼容；stdio 由 client 启动 server 子进程；HTTP 可由独立服务承载多个 client。 | 协议支持不证明会话间隔离；旧 probe 固定 `2024-11-05`，实现须按协商版本区分。不能将远端服务 shutdown 当成连接关闭。 |
| [MCP Tools](https://modelcontextprotocol.io/specification/2025-11-25/server/tools) | tools/list 与 tools/call；tool annotations 在未可信来源时必须视作不可信。 | 工具 schema/annotation 不能充当 Ordessa Permission 授权。 |
| [MCP Authorization](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization) | HTTP auth 有协议化约束。 | 不让 MCP 域自建密钥库；stdio 凭据方式按安全边界另验证。 |
| [Codex MCP](https://learn.chatgpt.com/docs/extend/mcp?surface=cli) | 原生 stdio/HTTP、工具过滤、required/timeout、插件自带服务器配置面。 | 先钉目标版本与运行时，现有 ACP 路径无逐会话 native 装载证据。 |
| [Claude Code MCP](https://code.claude.com/docs/en/mcp) | 多 scope、stdio/HTTP、严格指定配置；原生 scope 冲突按优先级；非交互项目 MCP 的批准行为不同。 | 必须证明受控实例只装载目标配置，不能只凭 `.mcp.json` 不存在推断没有其他来源。 |
| [Pi Extensions](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/extensions.md) | 扩展可注册工具和处理 session 生命周期，代码拥有 Pi 进程权限；官方强调运行期资源清理。 | 不能把任意社区 MCP adapter 当 Pi 原生能力或默认可信。 |

协议规范可能有更新的 draft；首版**固定 2025-11-25 作为核验基线**，运行时协商和兼容按实际 SDK/服务端验证，不从 draft 自动升级。旧 SSE、WebSocket 等新定义范围外；导入可保留旧记录，但不能错误启动。

## 逐模块复用裁定

| 模块/来源 | 现状 | 裁定与要剥离的债 | 许可/版本 |
| --- | --- | --- | --- |
| `plugins/server-compat/src/ordessa_server_compat/assets/mcp.py` | canonical + digest + 不可变 revision；只允许 env/header `credentialRef`，remote URL 限 https/loopback。 | **迁移并改造**定义校验/内容地址；区分 literal 与 secretRef，保持旧 revision 字节与 digest 可校验；无连接逻辑。 | 本仓代码，无外部许可证问题；迁移要旧数据样本。 |
| `plugins/server-compat/src/ordessa_server_compat/assets/mcp_probe.py` | 有 bounded stdio initialize、超时和进程组收尾；固定旧协议版本、无凭据。 | **限定复用**限时/收尾模式；升级为版本协商和可信响应解析，不把 probe 当实际连接。需无凭据/有凭据结果区分。 | 本仓代码；测试必须证明无孤儿。 |
| `plugins/server-compat/src/ordessa_server_compat/assets/rendering.py` | 针对原生文件的 JSON/TOML 片段、仅 stdio，`resolved_env` 明文可写。 | **仅借鉴格式测试**，不直接迁 renderer：改 C2 IntentSet，禁止明文普通配置文件，完整集合交 Harness 合并；不直接写 HOME。 | 本仓代码；旧行为不满足新 secret 边界。 |
| `plugins/server-compat/src/ordessa_server_compat/composition.py` MCP 段 | 旧 Profile binding 注入 sidecar，部分 secretRef 直接拒绝；同段还合成 subagent bridge。 | **拆出业务到 MCP 域**并通过产品公开注册点装配；原 subagent bridge 不被 MCP 资源库偷偷吸收。不得从 compat 复制并继续扩张。 | 本仓代码；先冻结迁移样本。 |
| `plugins/server-compat/src/ordessa_server_compat/assets/records.py` + `core_wire.py` | `server_assets` 及 profile binding、publishMcp wire 方法。 | **迁移数据库/API 语义**，保 ID、修订、digest、wire 兼容需求；新方法归 MCP 描述符，compat 对 mcp kind 只减不增。 | 本仓代码。 |
| 官方 [TypeScript SDK](https://github.com/modelcontextprotocol/typescript-sdk) / [Python SDK](https://github.com/modelcontextprotocol/python-sdk) | 提供协议 client/transport 能力，需选一套与项目运行时一致的固定版。 | **首选直接依赖受审 client**，只封装必要 initialize/list/call/close，不移植其协议实现；若与 ACP/Python 进程边界不符，T02 记录限定替代，禁止临时写全协议。 | 实施时 pin tag/SHA、lockfile、许可证/notice；本设计未固定可装版本。 |
| Pi 第三方 MCP extension | 社区多实现，行为/许可证/更新不一。 | **不直接依赖或复制**；先验证官方 Pi extension API，以本项目极小的受管桥接模块实现；若要用第三方必须单列 pin/许可证/安全审查。 | 本包无授权的第三方源码。 |

## 不能借复用掩盖的缺口

旧 `render_for_family` 的文件存在证明不了 native client 实际加载；`mcp_probe` 返回 initialize 不证明 tool catalog 或权限；跨会话共享相同定义也不证明隔离。官方文档与本仓固定版本之间缺口由 T00/T02 受控对端补证，未获证的品牌保持 unsupported/unknown。
