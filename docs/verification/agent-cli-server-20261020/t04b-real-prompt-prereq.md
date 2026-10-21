# 真实 prompt 回合：前置条件核验（2026-10-21）

> **已完成**：见 [T04-B：Server 的 `harness.providers` 配置面 + 一次受控真实 prompt 回合](t04b-real-prompt.md)
> （真实模型调用 1/3，Codex 原生 app-server，真实 answer `391`）。本文保留为当时的前置核验记录。

只读核验（未读取/打印任何密钥值）：

| 前置 | 结果 |
| --- | --- |
| 根 `.env` | 存在（125B），变量名：`DEEPSEEK_API_KEY`、`OPEN_CODE_GO_API_KEY` |
| 原生程序 | kilo / pi / claude / codex / hermes / dsh **均在 PATH** |
| 预算 | 累计 0/10 USD 未使用；模型固定 `deepseek-v4.1-flash`（OpenCode Go 渠道） |

## 下一步实现（未做）

1. 服务配置增加 `harness.providers`（品牌 `command` / `env` / `envFrom`，规则沿用 CLI：禁明文密钥、只允许 env 名），
   并把它传给 `PreparationResolver(harness_config=…)`（当前 Server 传空 dict，因此品牌只能走默认可执行名）。
2. 真实 prompt 回合的最小路径：`environments create local` → `agents.start`（fresh）→ `agents.prompt`
   （先选一个只依赖本机登录、无需额外配置的品牌；历史证据里 Codex 原生协议在本机有可用登录）。
   prompt 后必须 `agents.query` 取原生消息/answer，再 `agents.stop` 并核对进程/Use 释放。
3. 预算纪律：串行、每次记录 usage、累计到 ~9 USD 停；失败/NOT_RUN 单列，不拿别的品牌替代。

在此之前不得宣称"真实派活"完成。
