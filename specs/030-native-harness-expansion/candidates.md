# 十家候选与通道核查

以下2026-10-04已打开官方文档/上游正文；是通道线索，不是本机适配或安装证据。网页main及命令会变化，执行者必须钉实际版本，记录选择理由与固定源码链接。

| 顺序 | 家族 | 候选主通道 | 官方资料 |
| --- | --- | --- | --- |
| 1 | Codex | app-server，原生JSON-RPC | [正文](https://learn.chatgpt.com/docs/app-server) |
| 2 | Pi | 原生RPC JSONL；必要时比较公开SDK | [正文](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/rpc.md) |
| 3 | OpenCode | 原生HTTP Server/OpenAPI＋事件流 | [正文](https://opencode.ai/docs/server/) |
| 4 | Claude Code / Claude Agent SDK | 官方Agent SDK；比较原生stream-json，ACP只作有证据备选 | [正文](https://code.claude.com/docs/en/agent-sdk/overview) |
| 5 | Kimi Code CLI | 原生Wire JSON-RPC；比较官方ACP | [正文](https://moonshotai.github.io/kimi-cli/en/customization/wire-mode.html) |
| 6 | Qwen Code | 比较官方qwen serve HTTP/SSE、SDK与原生ACP | [正文](https://github.com/QwenLM/qwen-code/blob/main/docs/developers/architecture.md) |
| 7 | Gemini CLI | 官方ACP；headless JSON仅明确有限备选 | [正文](https://geminicli.com/docs/cli/acp-mode/) |
| 8 | GitHub Copilot CLI | 官方SDK＋CLI server JSON-RPC | [正文](https://github.com/github/copilot-sdk) |
| 9 | Goose | 官方goose acp；比较serve ACP HTTP/WebSocket | [正文](https://goose-docs.ai/docs/gdk/acp/) |
| 10 | Mistral Vibe | 官方ACP/vibe-acp；启动参数以固定发布源码为准 | [正文](https://docs.mistral.ai/vibe/code/use-vibe-in-other-ides) |

## 每家必须攻击的假设

### Codex

初始化与通知、反向审批/工具请求、thread/turn身份和resume；未知新method/event不得丢弃。不要混淆exec-server、模型API与本地app-server。

### Pi

prompt回执不是完成；区分settled/event、extension UI、steer/abort；真实版本可能不同于现有pi-acp资产，不能沿用旧桥覆盖结论。

### OpenCode

全局事件按session/project隔离；认证、随机loopback端口；断开SSE不是任务结束；未知HTTP路由保持原生可达但不扩大权限。

### Claude Code / Claude Agent SDK

SDK callback权限、会话恢复、技能/插件配置加载；别把Anthropic Client SDK或Managed Agents当Claude Code。官方SDK认证/分发条款须逐项记录，不偷用订阅token。

### Kimi Code CLI

Wire版本协商、question/approval反向请求、steer、replay；replay不能再次回答历史审批，Rust变体不得冒充Python版同能力。

### Qwen Code

serve与ACP谁持有workspace/runtime/权限；serve源码可能设计与实现不同；不让桥创建第二会话账，不把CLI输出当完整管理面。

### Gemini CLI

ACP客户端文件/terminal回调、版本与扩展覆盖；同引擎不代表所有TUI命令可用，headless不能冒持续双向通道。

### GitHub Copilot CLI

SDK可能自动启动/下载CLI并读取账号环境；显式绑定受控二进制与临时home，校验ownership、权限回调、session resume和token隔离。

### Goose

Goose自身作ACP server与其使用别人作provider不是同一件事；secret/origin与会话边界；不得开启dangerously-unauthenticated。

### Mistral Vibe

认证和配置共享home、skills/MCP的实际加载、ACP扩展；不使用installer改变uv或用户全局环境，不把IDE上下文当必要且已提供。


## 备选，不冒充已确定接入

Cline：[上游CLI正文](https://github.com/cline/cline/blob/main/apps/cli/README.md)可见JSON/headless和后台hub线索，完整双向通道与取消/历史需另查；不能把--yolo作为接入条件。
现有Hermes/Kilo/DSH保留原身份，可以补研究，但没有本轮证据不能算十家完成。替换主候选需记录具体理由、同等验收，不静默换名。

## 钉版要求

每家保存查阅日期、上游release/完整SHA、实际artifact digest、协议版本、SDK版本、license/NOTICE及分发限制。网页只作为方向依据；关键行为用固定源码或实物核实。第三方桥另列维护者、版本和桥后的损失，不能把“上游官方”移植到第三方实现上。

Claude官方SDK文档包含认证和商业使用限制，需复核选定路径适用条款；不使用登录Token绕过限制。Copilot SDK自动管理进程与可能携带CLI，需要查实际版本依赖行为。Goose旧block站点已跳转goose-docs.ai，按当前正文而不是过期安装脚本操作。

