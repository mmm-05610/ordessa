# phase2-design-mcp · MCP 域四家（hermes/opencode/dsh/kilo）扩展设计草案

016 夜批 overnight-3 · 阶段二产物（只文档不改代码）。依据：spec.md 品牌优先级
节、son-cmp-mcp 包（q4 甄别 + wire 调和）与 011-q4 线交付（T04 native
adapters：pi/codex/claude-code 的 assess/compile/verify 纯函数 + C2/C4 链）、
harnesses.md 四家 MCP 行、source-index.json。**草案，不是实施授权。**

## 1. 目标

把 `plugins/assets/mcp/adapters`（现有 pi/codex/claude-code 三家品牌 adapter）
扩到四家：原生 MCP 配置面存在者做 native intent 投影（C2/C4 同链），不存在
或不完整者逐格 honest unsupported；权限双门（T06）、受控 probe（T03）、受管
client（T05/T011）全部复用，不重造。

## 2. 四家证据格

| 品牌 | pin | 原生 MCP 面（harnesses.md 行 + source-index） | 设计要点 |
| --- | --- | --- | --- |
| hermes | 2.0 | :104 `mcp_servers`（command/url/env、工具 include/exclude、prompts/resources、认证/超时）；`/reload-mcp` 与 gateway 自动监视是两种生效路径 | 投影进 config.yaml `mcp_servers`；生效路径二择一钉死（reload 命令 vs gateway watch），未证实者 applyMode=unknown；工具 include/exclude 与 Ordessa 工具子集（T02）映射 |
| opencode | 2.0 | :127 `mcp` local/remote、OAuth、enabled、工具权限；stdio 进程与远程连接生命周期不同 | 投影进 opencode.json `mcp`；OAuth 流程不入 adapter（秘密/交互面），认证缺席=typed unsupported；local stdio 与 remote 分两个 claim 目标 |
| dsh | 0.1.5-rc.1 | :152 `mcp-client` stdio/streamable-http、reconnect、startup failure、instruction budget | Cordis 装配链包级 patch（同 lsp 设计的包级 target 变通）；reconnect/budget 为运行语义，投影只钉配置键、不承诺运行行为 |
| kilo | 7.7.2 | :196 `mcp` local/remote、command/env 或 url/header、OAuth、timeout、enabled；官方文档多格式示例并列，以目标 CLI schema/parser 为准（:206） | 投影前先钉 kilo schema 单一解析（app.kilo.ai/config.json + 目标版本 parser），不拼接混合格式；重启生效（:206）→ applyMode=restart |

## 3. 适配形制（复用 011-q4 既有件）

每家 `adapters/<brand>.py`：纯 assess/compile/verify（复用 `backend/native_*`
意图词汇与 `adapters/common.py` 形制）；descriptor 经真实
`harness.configuration-adapters` 点注册（零 claims 起步、按证得的原生键逐步
加）；`backend/permissions.py` 双门与 `probe_policy` 原样复用；受控 probe 走
T03 的 loopback/fake-stdio（零真实外网）；wire 守卫（tests/contract）按
wire-alignment.md 方法学同步扩账本——**账本与报告同动**（contract-guard 纪律）。

## 4. 测试门

1. 每家 golden：native 集合编译/双会话不串/额外原生来源识别（V04 口径）；
2. 权限双门在四家格上同样先于副作用（T06 复用，不另造）；
3. 受控 probe 四家配置形制（stdio/remote 循环假端点）；
4. 契约守卫扩格（WCG 方法学）+ contracts.md §1/§4 交叉引用（工具调用授权
   `authorizeToolCall` 由 Permission 裁定——此为 **Ordessa 侧设计不变量与
   测试约束**，非对四家运行行为的断言）；
5. unsupported 格带证据指针（信任阶梯 L2-L4，L6 不入账）。

## 5. 派工边界与待核

写入面：`plugins/assets/mcp/**` + 报告。前置：dsh 包级 patch 与 C2 字段级
claims 的接缝登记（同 lsp 设计）；kilo schema 解析钉版；hermes reload/gateway
生效路径取证。真 CLI 装载格（L3）维持 011-q4 线登记（需用户提供 CLI 环境）。
