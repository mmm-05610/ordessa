# packages/interfaces/channels/mcp/runtime

MCP server runtime 当前位于父目录 `src/ordessa_mcp_server/`；本目录不是独立 package 或单独发行单元。它通过 system-access client 访问远程 Server，不负责建立后端服务。

应用启动入口由既有 distribution console script 提供；资源管理功能仍归负责它的 MCP plugin。
