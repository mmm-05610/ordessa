# N001-3 第一家隔离纵向入口实测证据（pi 原生RPC）

执行：主执行者亲跑，2026-10-04（Asia/Shanghai）。真实模型调用0。

## 实物与钉版（L0）

| 项 | 值 |
| --- | --- |
| 家族/通道 | pi · 原生RPC（`pi --mode rpc`，严格JSONL，非JSON-RPC 2.0） |
| 安装形态 | 受管安装 `~/.pi/agent`（包装器shell脚本→releases/<v>/node_modules/.bin/pi） |
| 固定版本 | **0.86.1**（`install/current-version`） |
| 包/许可 | `@earendil-works/pi-coding-agent` 0.86.1，**MIT**，github.com/earendil-works/pi（packages/coding-agent） |
| artifact | `dist/bundle/cli.js` shim → `cli-runtime.js` + `chunks/`（8.2M）；bundle摘要 sha256 前40位 `e79626f2dd6f94aa45d30f3fa63cd84319a6eefc`（cli.js；全量摘要待N003补） |
| 协议来源 | 官方文档 `packages/coding-agent/docs/rpc.md`、`rpc-commands.md`（2026-10-04查阅） |
| 启动副作用静态审 | 包装器只解析releases路径并exec（无网络/无hook）；bundle URL扫描均为模型provider端点（openrouter/bedrock/openai/…）与 `radius.pi.dev`（radius模型provider，非遥测）；遥测存在但由 `PI_TELEMETRY` env或settings门控（`isInstallTelemetryEnabled`），本次 `PI_TELEMETRY=0` 显式关闭 |

## 运行隔离（L2前置，G8/G9/G12）

```
unshare -rn   # 网络命名空间：外部网络不可达（禁外部模型网络）
env -i        # 干净env：HOME=/tmp/n001-pi-home（XDG/TMPDIR全部钉进scratch）
              # 无任何用户Token键（isolated_env 剔除表生效）
--offline --no-session --no-extensions --no-skills --no-context-files
--no-prompt-templates --no-approve   # 禁启动期网络、项目本地文件信任与扩展加载
```

用户真实 `~/.pi`（含 auth.json/models-store.json/sessions，凭据与用户数据）**未读取**；pi仅在scratch TMPDIR写node编译缓存。未运行任何 `pi update/install/auth` 命令。

## 实测结果（证据文本 `N001-vertical-pi-rpc.txt`，探针 `N001-vertical-pi-rpc-probe.py`）

| 步骤 | 结果 | 证明什么 |
| --- | --- | --- |
| `get_state` | `success:true`，真实 `sessionId`（进程内，`--no-session` 无sessionFile），model=unknown，thinkingLevel=off | **真实上游进程协议握手成功**（L2 partial）；无模型选择、无模型调用 |
| `get_commands` | `success:true`，列出inline来源命令（llama） | 原生能力发现通道可用（G4：不猜测能力面） |
| 未知命令 `definitely_not_a_command` | `success:false, error:"Unknown command: …"` | 未知命令typed失败、进程不崩（反例✓） |
| 非法JSON行 | `type:response, command:parse, success:false`（文档语义一致） | G5 typed失败，不误解析继续（反例✓） |
| stderr | 空 | stdout协议/stderr诊断隔离（G5） |
| 关闭stdin→进程退出 | exit 0 | 生命周期：关闭即止（detach/后台语义未测） |

## 证据分账（不夸大）

- **L2 partial（已观察）**：真实已安装CLI进程、真实原生RPC握手/状态/能力发现/退出、隔离home+无网+无Token+无启动hook。只启动握手与只读状态，**不覆盖**L2会话持久化/恢复、prompt受理语义、steer/abort、extension UI回调。
- **L1（fixture）**：transport接缝30用例（G4/G5/G11/G12反例）已绿，但fixture≠真上游，独立分账。
- **L3/L4**：未测。无本地loopback provider任务验证；真实模型0（未授权，预算0）。
- **不发布 runtimeReady=true**：029前置（节点/原生session reservation/InputAttempt/transport fence）缺失，见 `N001-source-snapshot.md`；本证据只证明「适配实现/协议验证」层。

## 已知语义要点（进N003实现）

- 严格JSONL：`{"id","type":"<command>",...args}` 请求；`{"id","type":"response","command","success","data"|"error"}` 响应；字节LF分帧，U+2028/U+2029不得当分隔（官方文档明示，与G5一致）。
- **prompt回执≠完成**：`data.disposition=started/handled`；`agent_end`≠run终结；仅 `agent_settled` 确认不再自动继续。
- 反向回调 `extension_ui_request`→同id `extension_ui_response`（不是普通command response）。
- 无initialize/版本协商（文档未写明）；resume/replay语义文档未写明——均登记unknown，不得臆造。

## 清理

`/tmp/n001-pi-home`、`/tmp/n001-pi-work` 为本次scratch（仅node编译缓存与空目录），夜间收尾删除；探针脚本存档于evidence目录。借用的真实 `~/.pi` 进程树未动（无pkill、无写入）。
