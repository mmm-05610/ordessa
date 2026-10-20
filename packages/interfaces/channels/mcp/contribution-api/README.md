# packages/interfaces/channels/mcp/contribution-api

当前公开 MCP tool 注册与 handler 逻辑由父目录 `src/ordessa_mcp_server/server.py` 持有；本目录没有独立贡献 API package，也不声明额外权限、schema 或 journal owner。

单次外向请求经共享 system-access client 发出；工具返回服务公开的 wire 结果，不在 MCP channel 重建服务业务规则。
