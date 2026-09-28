# 三品牌适配和托管矩阵

下表区分**官网机制**与**当前 Ordessa ACP 通路已证事实**。官网支持不等于本仓固定二进制、ACP adapter、会话隔离已经通过。T00 固定 native/adapter 版本、SHA、入口与受控证据；未填不得将格子设 supported。

| Harness | 官方可参考的连接机制 | 首选 lane / 备选 | 本仓当前证据与首版关口 |
| --- | --- | --- | --- |
| Pi | 官方 [Extensions](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/extensions.md) 提供 `registerTool`、session 生命周期与动态激活；不能由此推断存在统一内建 MCP 配置。 | `ordessa-managed`，经固定、审过的 Pi extension 暴露受限工具入口；不悄悄依赖第三方 `pi-mcp-adapter`。 | 现有 `plugins/server-compat/assets/mcp.py` 仅存定义、probe 仅 initialize；尚无双会话受管转发/授权证据。extension 的 code/许可/pin 与唯一 client owner 须 T02 落证。 |
| Codex | 官方 [MCP 配置](https://learn.chatgpt.com/docs/extend/mcp?surface=cli) 有 stdio/HTTP、`enabled_tools`/`disabled_tools`、超时、required；当前文档还描述插件带 MCP。 | `harness-native` 优先；若当前 adapter 无逐会话隔离/受控装载与重启恢复，改由明确评审的 managed lane，不双开。 | 旧 renderer 可写 TOML stdio 片段，但其明文 `resolved_env` 路径不符合本设计；无运行装载/权限实证。C2 目标必须是 Harness 授权的实例配置 generation，非全局 `$CODEX_HOME/config.toml`。 |
| Claude Code | 官方 [MCP 文档](https://code.claude.com/docs/en/mcp) 支持 stdio/HTTP、多 scope、严格指定配置；原生重复项有优先级，项目 `.mcp.json` 在非交互场景可能无提示加载。 | `harness-native` 优先，受控 `--strict-mcp-config`/实例配置源仅在固定版本验证后使用；否则 fail-closed 或审定 managed lane。 | 旧 JSON renderer 只支持 stdio；无 ACP 下同一会话动态 reload/严格来源隔离证据。特别要测原生 user/project/plugin MCP 是否额外发现、名称/endpoint 冲突与身份恢复。 |

三品牌均须证明：A 会话配置与 B 不同→两套 tool catalog 与凭据互不串；A close 不影响 B；输出中变更只在下一次用户提交生效；需要重启时由 Harness 恢复**同一 native session**，恢复失败保持拒绝/未知，不新建替代。

## Native lane

MCP adapter 输入完整 `McpEffectiveSnapshot`，在 C2 `compile` 里生成目标配置 intent；所有服务器作为一个受管集合规划，而不是逐服务器向同一 JSON/TOML 追加文本。Harness C3 做结构合并、冲突检测、路径封闭、generation 发布与原生观察；MCP adapter 不能自行写 HOME。`verify` 至少比较实例 identity、server name、transport、实际加载状态和观察到的 tool catalog digest；“文件字节一致”只能记 `projected`。

native lane 的子进程和连接由 Harness/其原生 MCP client 关闭。插件仅保留定义与租约记录，native owner 失败报告 unknown 并触发 reconcile。若原生配置本来已有同 endpoint 但不同名称，不能偷偷覆盖；可只读显示“原生发现”，或拒绝冲突。Codex `disabled_tools` 后置于 `enabled_tools` 是原生产品规则，不能假定两家的 allow/deny 算法相同。

## Managed lane

MCP 域进程/连接 manager 使用固定版本的官方 MCP SDK **client** 能力或目标最小子集；首版只需 initialize、tools/list、tools/call、正常 close/取消与受限重连。不得为了首版实现资源、采样、elicitation、Tasks 等全协议能力；服务器要求未支持能力时标 unsupported。对 stdio：一会话一子进程，一 owner，受限 env/cwd，stdout 有帧上限、stderr 脱敏，进程组幂等清理。远端 Streamable HTTP：每会话独立 client/session，TLS/Origin/redirect/auth 检查按固定 SDK 与配置策略，远端服务自身不归本插件停机。

Managed 接到 Pi 的扩展只登记由 Server 校验的工具桥接，不得持有原始 secretRef 或直连目标 server；任何扩展绕过 Permission 调用的路径都必须拒绝。扩展安装本身是可执行代码，需独立版本/许可证/信任审批；不是“安装一份 MCP 定义”自动获得代码执行权。未通过这一入口门，Pi 只可管理定义，不能声称已可用。

## 避免双启动的机械约束

`laneByDefinition` 对每个 definitionId 恰有一个 lane，`endpointFingerprint` 维护实例级占用；native projection 与 managed lease 在同一配置 plan 中互斥校验。关闭先停新调用、等待在途请求/记录 unknown，再调用对应 lane owner。不能 MCP 插件在 native 关闭后猜 PID kill，也不能 Harness 清理由 MCP 域持有的子进程。
