# T08：claude / pi 用本机第三方 API 配置重跑（2026-10-21）

用户指出两者本机已用第三方 API 配置。经核实：
- claude：`~/.claude/settings.json` 的 `env`（`ANTHROPIC_BASE_URL`/`ANTHROPIC_AUTH_TOKEN`/模型名），
  Claude Code 从 `$CLAUDE_CONFIG_DIR/settings.json` 读取；preparation 把 `CLAUDE_CONFIG_DIR` 绑到 `config` root。
- pi：`~/.pi/agent/{auth.json,models-store.json,settings.json}`；preparation 把 `PI_CODING_AGENT_DIR`
  绑到 `home` root。

## claude：✅ SUCCESS（真实调用 1 次）

- Profile 声明 `credentials.file`：`~/.claude/settings.json` → `config/settings.json`（0600 落盘，字节不进记录）。
- `agents.start(fresh)` completed；`agents.prompt`（17×23）→ **completed，answer `391`**。
- 清理：stop/reconcile/process-release/release；残留进程 `[]`。

## pi：🟡 PARTIAL（已不再超时，但 answer 未被观测到）

- Profile 声明三个 `credentials.file`（auth/models-store/settings → `home/`）。
- `agents.start(fresh)` completed；`agents.prompt` → **completed**（不再 30s/120s 超时），
  但 observation 只有 `event: "agent_settled"`（`pi-rpc/1`，delivery confirmed，bytesSent 120），
  **receipt 里没有 assistant 文本**，工作区 home 也没留下 pi session 记录 → **answer 未取得**。
- 说明：认证与回合已经跑通；缺口在 pi 原生协议的消息/观测提取（需要读取 pi 的 session/消息帧，
  或在 pi 通道捕获 assistant 文本），不是"没登录"。

## 结论

- claude ✅（391）；pi 🟡（认证通过、回合 completed、answer 提取缺口）。
- 两者均不再依赖交互式登录，配置以 Profile 声明 + 文件绑定实现（符合"密钥不落记录/不落仓库"）。
