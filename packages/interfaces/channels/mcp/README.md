# packages/interfaces/channels/mcp

本目录承载可运行的 Python MCP channel。`ordessa_mcp_server` 使用官方 MCP SDK 注册 `ordessa_capabilities` 与 `ordessa_wire_call` tools，并通过 `ordessa-system-access-client` 调用远程 Ordessa Server。MCP 进程不会装配 Server；现有 MCP 资源管理插件仍由其 plugin owner 提供。

Python distribution/import 名称、远程 wire 协议和 Server authority 边界保持稳定。`pyproject.toml` 声明 SDK 与 Python system-access client 的运行依赖。
