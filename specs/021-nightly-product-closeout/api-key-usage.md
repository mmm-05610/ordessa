# api-key-usage.md — 真实 E2E 模型资源与用法规程

## 资源

| 项 | 值 |
| --- | --- |
| 文件 | `/home/maoqh/projects/ordessa/worktree/021-ordessa-product-closeout/key.txt` |
| 内容 | DeepSeek 官方 API key（仅一行 key，无其他） |
| 授权 | 用户 2026-09-30 提供，**不限额度**，用于产品真实端到端测试；用户声明可用于所有 harness |
| 历史 | 23:5x 首版为 OpenCode Go key（51B）；00:14:03 用户换为 DeepSeek 官方 key（35B）。OpenCode Go 研究结论保留作 fallback（`https://opencode.ai/zen/go/v1/`，Bearer `OPENCODE_API_KEY`） |

## 处理铁律（所有 Agent 无例外）

1. **不可读**：任何 Agent 不得把 key.txt 内容读入上下文——禁止 cat/Read/echo/打印。
2. **只许脚本用**：脚本运行期读取，如 `curl -H "Authorization: Bearer $(cat <path>)"`；key 不得出现在任何命令回显、日志、evidence、截图、commit 里。
3. **不进 git**：已由 `.git/info/exclude` 的 `/key.txt` 模式忽略（共享于所有 worktree 根，已验证）。任何 packaging/tests 改动不得把 key 或其形状写入仓库。
4. **不落盘到产品外**：运行期只注入隔离 runtime home / 执行环境 env（`DEEPSEEK_API_KEY`）；不写入用户真实配置（`~/.config/*`）；不写进 deb。
5. **Closeout 清理时不得删除 key.txt** —— 它是用户资产，不属于本轮 branch/worktree 清理范围。
6. 验证 key 一律用零 token 探针：`GET https://api.deepseek.com/models`（已验证 HTTP 200，见 evidence.md E-P0-8），不烧 token。

## DeepSeek API 事实（官方文档 2026-09-30 核对）

- Base URL：`https://api.deepseek.com`（OpenAI/Anthropic 双兼容；OpenAI SDK 改 base_url 即用）。
- 认证：`Authorization: Bearer ${DEEPSEEK_API_KEY}`。
- 模型（/models 实测）：`deepseek-flash`（DeepSeek-V4.1-Flash，1M 上下文，393K 输出上限，**text+image 输入**，effort low/high/max，支持 anthropic_messages 能力）、`deepseek-v4-pro`（DeepSeek-V4-Pro，text-only，1M 上下文）。
  - 旧名 `deepseek-chat`/`deepseek-reasoner` 已不在列；legacy 名仍被接受但由 V4.1-Flash 服务。今晚一律用 `deepseek-flash` / `deepseek-v4-pro`。
- `thinking`（`{"type":"enabled"}`）与 `reasoning_effort` 参数可用；流式 `stream:true`。
- **Anthropic 兼容端点**：`https://api.deepseek.com/anthropic` —— 供 `ANTHROPIC_BASE_URL` 类消费（Claude Code）。
- 官方文档明确列出的 no-code 接入：Claude Code、Codex、OpenCode、OpenClaw、Hermes、Reasonix、WorkBuddy/CodeBuddy、Qoder；DeepSeek 自家 harness（dsh）为 developer preview。

## 与仓库的对齐（已核实）

- 产品自带验收模板：`plugins/harness/deploy/opencode/opencode.json` —— deepseek 官方 provider
  （`baseURL: https://api.deepseek.com`、`apiKey: {env:DEEPSEEK_API_KEY}`、model
  `deepseek-flash` "bounded acceptance"（thinking disabled、context 1M、output 64））。
  今晚 E2E 直接复用该模板模式，逐 harness 物化到**隔离** config/runtime home。
- Harness 注册表（`plugins/harness/src/ordessa_harness/harnesses.toml`，7 家）×
  key 消费路径（Phase 1/4 逐项实测验证，不许只信文档）：

| Harness | provider slot | 预期接法 | 状态 |
| --- | --- | --- | --- |
| opencode | 有（slots 含 provider） | 仓库模板物化到隔离 `OPENCODE_CONFIG_DIR`；env `DEEPSEEK_API_KEY` | Phase 3 首选 Harness B（CLI 未装，需装） |
| claude-code | 有 | `ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic` + auth token 物化到隔离 CLAUDE_CONFIG_DIR | Phase 3/4 验证 |
| codex | 有 | `$CODEX_HOME/config.toml` model_providers + env_key=DEEPSEEK_API_KEY | Phase 4 验证 |
| dsh | 有 | DeepSeek 自家 harness，原生 | 环境允许则测 |
| kilo | 有 | opencode fork，同模板模式 | 环境允许则测 |
| hermes | 无（instruction/mcp/skill） | DeepSeek 文档列有 Hermes 接入——查其自身 provider 配置面 | 诚实核实 |
| pi | 无（instruction/mcp/skill） | 查 pi agent-dir 自身 provider 机制；**若不支持则如实报不支持，不伪装** | 诚实核实 |

- 注：Harness A 的候选是 pi（本机已装，Round H 受控验收的既有人选）——若 pi 无法
  以 DeepSeek 为后端，Harness A/B 顺序在 Phase 3 现场重排（以真实可用为准），
  但"两个不同 Harness 真实证据"的验收条目不变。

## 用途分配（哪些验收项烧 token）

1. 真实 Harness E2E（acceptance §真实 Harness E2E A/B）：prompt → streaming → tool call → approval。
2. Profile→Harness 硬验收：Profile 配置（含 model provider facet）实际进入 runtime 并完成真实 Session。
3. MCP smoke：真实 MCP tool 经 Conversation UI 调用。
4. Permission/Approval：真实 approval 往返。
5. Multi-harness：Harness A/B 同 UI 隔离证据。

费用纪律：额度不限 ≠ 挥霍——每次调用必须对应 acceptance 条目或回归验证；
不跑无目的的循环压测；long-context 用小项目，别拿 1M 上下文当玩具。
