# Claude Code N005：原生控制协议与纯启动规划修复

日期：2026-10-05。只本实施树；不安装SDK/CLI、不读取用户home、不启动Claude、不调用模型。本轮修改限定Claude家族planner、对应测试与本报告；前一切片已修改Claude专属消费者及其测试。

## 通道选择与固定来源

优先复用官方Claude Agent SDK运行Claude Code引擎，不使用Anthropic Client SDK代替Agent引擎。现有stdlib消费者仍是有限的原生stream-json消费面；它没有重新实现Agent loop，也不是另一个SDK。生产SDK接纳、异步读写和上游生命周期管理尚未接入。

本次通过GitHub API读取并固定官方Python SDK源码SHA `9c69ce7aced5cdf2aa1ac86fe62e877b4962de8b`；该快照pyproject版本`0.2.163`、组件许可`MIT`。这只是源码证据，**不是本机已安装SDK/CLI版本，也不是已测CLI兼容范围**。运行artifact digest仍unknown。

- [官方query.py：控制请求、权限回应、interrupt、turn/run区别](https://github.com/anthropics/claude-agent-sdk-python/blob/9c69ce7aced5cdf2aa1ac86fe62e877b4962de8b/src/claude_agent_sdk/_internal/query.py)
- [官方types.py：控制类型、permission与result字段](https://github.com/anthropics/claude-agent-sdk-python/blob/9c69ce7aced5cdf2aa1ac86fe62e877b4962de8b/src/claude_agent_sdk/types.py)
- [官方subprocess_cli.py：stream-json输入与permission-prompt-tool](https://github.com/anthropics/claude-agent-sdk-python/blob/9c69ce7aced5cdf2aa1ac86fe62e877b4962de8b/src/claude_agent_sdk/_internal/transport/subprocess_cli.py)
- [官方pyproject：源码版本及组件许可](https://github.com/anthropics/claude-agent-sdk-python/blob/9c69ce7aced5cdf2aa1ac86fe62e877b4962de8b/pyproject.toml)
- [Zed官方ACP说明](https://zed.dev/blog/claude-code-via-acp)：Claude ACP是其SDK转换适配器，不能称Anthropic提供的原生ACP。现有Ordessa ACP桥另有转换与升级维护面，本切片不启用或替换它。

旧N005 decision中的“stdin形状未写明”已由上述固定官方源码补证；旧页保留历史记录，以本报告与当前channel_report为这次修订的证据。官方SDK的can_use_tool只处理上游许可规则判定为ask的调用，allow rules/settings可能在回调前放行；不能仅凭回调存在宣传逐工具强制审批。组件MIT不替代Claude Code运行及认证的商业条款审阅。

## 实现边界

`plugins/harness/src/ordessa_harness/claude/native_channel.py`新增显式`plan_launch(..., bidirectional=True)`，纯构造：

```text
claude -p --output-format stream-json --input-format stream-json --verbose --permission-prompt-tool stdio
```

默认output-only模式不自动切换。双向模式拒绝argv prompt和extra_args位置prompt，输入必须先完成原生control initialize再由stdin user frame提交。输送格式、stdio审批路由与verbose由planner持有，不接受extra_args覆盖；权限bypass、callback shadowing选项、resume/continue及短别名冲突发前拒绝。双向模式仅接受已编译配置选项，未实现启动配置明确拒绝，不声称任意launch flag兼容。

`compile_config(..., bidirectional=True)`拒绝acceptEdits/dontAsk等非default模式、allowedTools覆盖和含糊session选择。旧output-only可显式编译已有权限配置，但不会将其宣称为强制callback审批。resume和continue是两种互斥原生选择，continue必须bool、resume必须非空str；不会生成随机session。

消费者`products/agent-tools/src/ordessa_agent_tools/native_clients/claude_code.py`支持显式双向模式：原生control_request/control_response嵌套request_id，initialize/interrupt/user、显式permission decision、取消callback、一次回应、session核对、错误结果、partial-write/EOF unknown。无审批者保持pending，未知输入不重发。后台task-notification结果不完成用户turn；result只结束turn，不证明run/process或后台任务结束，不自动关stdin。

## 命令与证据分账

本次纯规划/编译验证：

```bash
/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -q plugins/harness/tests/claude/test_claude_native_channel.py
```

初次新增后35 passed/0.14s/exit0；再补短别名、位置prompt和session类型反例后最终**43 passed/0.15s/exit0**。不运行任何外部Harness进程；tmp fixture目录未创建planner计划的home/work目录。已有compile测试原先同时resume与continue的非法组合拆成两个独立正向断言，并新增组合拒绝反例，没有删除覆盖。

前一消费者切片：

```bash
/home/maoqh/.codex/worktrees/agent-tools-product/.venv-ordessa-py312/bin/python -m pytest -q products/agent-tools/tests/native_clients/test_claude_code_client.py
```

**22 passed/6.61s/exit0**。这是隔离Python scripted peer及定向transport故障注入，属于L1，不能当真实Claude/SDK运行证据。模型0、安装0、Claude启动0；没有全局配置/用户数据变更。

## 剩余缺口

L2/L3/L4未测；生产首选官方SDK的依赖与版本钉定、分发许可、实际无模型握手、真实审批/取消/resume、项目settings隔离与callback shadowing、后台run完整结束、生产provider接纳及transport fence、持久InputAttempt/session reservation尚需对应owner与公开接缝验收。stdlib消费面不实现SDK hooks、SDK MCP、完整异步运行生命周期或可靠原生输入查询，不声称exactly-once或runtimeReady。整体仍PARTIAL。
