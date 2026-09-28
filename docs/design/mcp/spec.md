# Feature specification

## 用户场景

1. 用户在 Settings 保存一个 MCP 服务器定义，配置可读常量、秘密引用和连接方式；保存不启动服务、不授予工具、不修改用户原生配置。
2. 用户为当前用户默认、项目、某个 Profile 启用已批准修订，可勾选工具子集。预览能区分「已定义」「已启用」「连接成功」「工具已发现」「本次可调用」。
3. 同一 Harness 的两个会话可用不同 Profile/凭据/工具子集；改变 A 不影响 B 的连接、工具目录和权限，关闭 A 只释放 A 的资源。
4. 输出中改变选择不打断正在运行的 agent；下一次用户提交在配置闸门下装配并确认后再发消息。连接/重启/resume 失败不偷偷创建新会话或重发 prompt。
5. 移除、禁用、升级、卸载的效果与副作用清晰；正在使用的租约进入 drain/reconcile，秘密不泄漏到日志和桌面帧。

## 功能需求

| ID | 需求 |
| --- | --- |
| FR-01 | MCPDefinition 有稳定 ID、不可变修订、来源与摘要，严格区分 stdio 和 Streamable HTTP，结构/大小/路径/URL 校验；常量与 secretRef 类型不同。 |
| FR-02 | 保存/探测/启用/连接/工具发现/可调用分六级事实，不用一个 `available` 布尔混淆。probe 有超时/输出上限/取消与完整清理，不能用无凭据 probe 证明有凭据运行。 |
| FR-03 | 启用分配按用户默认→项目→Profile→会话覆盖解析，显式 enable(revision)/disable/inherit；同层冲突拒绝。更高管理员策略和未授权项目始终不能被覆盖。 |
| FR-04 | 工具子集与服务器启用一起冻结于会话快照；nativeName/endpoint/进程归属冲突在副作用前拒绝，不 last-wins。工具变化必须重新发现并比对，默认不自动扩大已批准集合。 |
| FR-05 | 每个连接有唯一 `connectionOwner`、lane、runtimeGeneration、sessionRef、凭据修订与关闭/对账记录。默认每会话隔离，不复用 stdio 进程；远端连接也不跨主体/配置池化。 |
| FR-06 | Harness-native 由 Harness 启动并关闭原生 client/子进程；MCP 插件只生成 C2 intent 并解释观察。Ordessa-managed 由本插件拥有连接/进程/目录/调用代理，不再把同一服务器投影给原生配置。 |
| FR-07 | Profile 贡献独立于业务核心；Profile 仅存定义引用/版本/选择/工具子集，不存凭据原文或活连接；提供者卸载时 UI 隐藏、数据保留、应用 fail-closed。 |
| FR-08 | 秘密仅经统一 credential reference 服务于后端解析，在受控启动环境或授权 HTTP 请求时注入；不写普通 JSON/TOML、日志、事件或前端 DTO。凭据轮换使计划过期，不能沿用旧快照。 |
| FR-09 | MCP 工具的模型可见性只是 discoverability；调用前由 Permission 公开授权服务作最终决定。未接上该权威时，沿既有 Harness 原生权限运行并如实标注，不能声称跨品牌新策略已生效。 |
| FR-10 | 失败须区分 definition-invalid、secret-unresolved、auth-required、connection-failed、protocol-mismatch、catalog-changed、permission-refused、owner-conflict、isolation-unproven、unknown-outcome；未知不能装成确定回滚。 |
| FR-11 | Settings 提供管理/探测与安全说明，Profile 提供启用/子集，Chat 显示会话实际连接状态和明确重试；未安装 UI glue 不影响后端实体。 |
| FR-12 | 现有 `server_assets` 的 mcp kind 和 `server_profile_assets` 绑定按 ID/摘要保全迁移；不删除未迁移内容，不修改磁盘标识、不复活 server-compat 新写入。 |

## 非目标与权威分工

- 不实现 MCP 服务端自身、搜索服务、OAuth vault、凭据库或 Permission 引擎。
- MCP Resources/Prompts 的协议列表不自动变成 Ordessa Skills/Prompts；跨域导入另设明确操作与所有者。
- 「Profile 允许」不等于强制权限；工具 schema 的 `readOnlyHint` 等是未受信声明，不替代授权。
- 不把用户全局/项目的原生 MCP 文件当 Ordessa 数据库；原生发现项是只读观测，不能默认为受管，也不能覆盖。
- 不因新建 MCP 包要求改 Pacthold、Server、Workbench 主体。缺公开扩展点则列明确接口缺口，禁止业务插件 import 宿主私有模块绕过。

## 成功判据

Pi、Codex、Claude 每品牌至少一个受控、无真实外部副作用的目标 lane 完成双会话隔离/启停/工具发现/权限拒绝/清理证据，不能仅测试 renderer。任何品牌无法通过原生或受管 lane 的完整门则该品牌不计完成；局部完成仍可落库，但整体首版不得报告三品牌全绿。
