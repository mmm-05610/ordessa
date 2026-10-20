# apps/mcp

可选独立 MCP 进程的启动与装配。施工基线没有此独立应用实现；现有 MCP 资源业务仍由 plugins/agents/resources/mcp 唯一拥有，不搬入应用，也不声明第二个执行入口。

依据：已批准的上层收敛说明及 architecture-review 中对应职责说明。本目录仅记录已确认逻辑边界，不宣称实现、发行、集成或功能验收通过。允许依赖公开 interfaces、共享 system-access 和显式注入贡献；不得反向导入应用私有实现、读取工程数据库或绕过现有后台权威。
