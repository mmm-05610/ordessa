# MCP 业务插件：Spec Kit 实施包

日期：2026-09-28。状态：**DESIGN_REVIEW_READY**，仅设计，未实施、未联调、未做真实外部 MCP 访问。目标业务目录 `plugins/assets/mcp/`；现有实现位于 `plugins/server-compat`，不把其行为直接视作新契约已经可用。

## 一句话边界

MCP 插件拥有**连接定义、批准的不可变版本、作用域启用、工具目录与连接状态**；每个实际连接只有一个运行/关闭所有者。Profile 只保存选择和覆盖，Harness 负责原生配置应用与会话恢复，Permission 拥有最终工具调用授权。工具出现在模型上下文中并不表示获准执行。

## 必读顺序

1. [spec.md](spec.md)：用户行为、边界、需求。
2. [data-model.md](data-model.md)：定义/分配/会话快照/租约。
3. [contracts.md](contracts.md)：注册点、领域服务、权限接缝。
4. [harness-adapters.md](harness-adapters.md)：Pi/Codex/Claude 三品牌与两种托管。
5. [ux.md](ux.md)：Settings/Profile/Chat。
6. [research-and-reuse.md](research-and-reuse.md)：官方资料、本仓复用裁定和许可。
7. [plan.md](plan.md)、[tasks.md](tasks.md)、[verification.md](verification.md)：实施顺序和可审计验收。

## 首版能力裁定

- 支持定义 stdio 与 Streamable HTTP MCP server；不把旧 SSE 当默认新建方式。协议协商依实际服务端，不能把存储的 URL 当连接成功。
- 一次会话的有效 MCP 集合在**下一次用户提交**前冻结；当前正在输出的 turn 不受编辑打断。定义升级需显式批准修订，保存新版不静默影响现有绑定。
- 可选择 `harness-native` 或 `ordessa-managed`，但每个实例只准一个 lane。Codex/Claude 优先检验 native；Pi 无已证原生 MCP 配置，按受控 Ordessa-managed + 单一 Pi 扩展接线设计。任一 lane 的会话级隔离、工具权限或真实装载无法证明则该格标 unsupported/unknown，不能假绿。
- 首版不建第二个 credential vault、permission engine、MCP SDK fork、Server/Workbench 分支，也不把远端 MCP 服务本身当作 Ordessa 进程管理。

上位设计：[业务分包](../plugin-layout-and-preparation-decisions.md)、[Harness C2](../harness-v2/contracts.md)、[Profile facet](../profile-v2/contracts.md)、[Skills 生效规则](../skills-v2/README.md)。这些同样是设计稿；T00 必须记录最终已集成 SHA 与实际公开 API，不能仅凭本包判定实现已就绪。
