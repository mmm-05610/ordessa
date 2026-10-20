# 协调者实际校验记录

完整外部流程承载结论：**unsupported**。本记录只证明 `projection/` 内单次报告登记冒烟投影可加载、校验、编译，并完成报告结构及真实输入编解码检查。没有工程命令写入、MethodRun、外部步骤执行、方法发布或生产接入。

验证日期：2026-10-12 UTC。核心 HEAD：`751707e1f1558d6b868a8761aed7c5a8dfbd4ef2`；HEAD 下有本轮既存工作树改动，不能只用 Git commit 识别核心。共同核心文件索引 SHA-256：`c825c329a83775685bd048c144068ca31e0a5369d68e317bee3d95f0f79b40f5`。Python `3.12.14`，依赖版本见 [core-snapshot.json](core-snapshot.json)。

Engineering 与 Infrastructure 的 Python 源码字节在导入前固定，所有子进程串行继承同一捕获。复验使用同一字节索引；源码文本保存在 Nova 的 `_support/verification/core-sources.json`，不会被 manifest 或 loader 读取。`capture-stability.json` 记录本次验证期间源文件未变。其他组无需改核心或测试环境。

调用命令（从仓库根目录，已有解释器；无安装）：

```bash
.venv-nightly/bin/python -B methods/nova-feature-delivery/_support/verification/verify_both.py
```

最终总命令退出码：`0`。每项真实子进程退出码与原始错误见 [results.json](results.json)。来源：当前源码的公开 `load_method`、`validate_method`、`compile_method`，以及真实 owner `command_capabilities()`；仅检查 `engineering.artifacts.create` 的现有描述，未注册替身或拼造生产 catalog。其 registry snapshot ref 为 null；静态 host 描述不是可信生产注册证明。

| 检查 | 退出码 | 实际结果 |
| --- | --- | --- |
| projection 基线 | 0 | load、validate、compile 均成功，无诊断 |
| 未注册 operation | 1 | UNKNOWN_CAPABILITY |
| 把批准/no-spec/返工/延期塞入 artifact outcomes | 1 | UNHANDLED_OUTCOME；不能冒充业务决定 |
| parallel 控制节点 | 1 | METHOD_STRUCTURE_INVALID |
| 返工回边 | 1 | UNSUPPORTED_FLOW_CYCLE（GitLab另有不可达诊断） |
| 资源改动却不更新摘要 | 1 | RESOURCE_DIGEST_MISMATCH |

本包 `3` 份合成报告 value 通过声明的文档 schema、真实 MethodPayload codec、实际操作 input schema 和 MethodBridge.operation_inputs 映射；空报告被 schema 拒绝。这些是设计样例检查，不是流程成功/等待恢复/拒绝的引擎轨迹。codec 使用明确的未发布示意 MethodRef，只检验值的表示；没有伪造已发布快照、审批或来源。

真实 FileResourceReader 仅尝试读取 projection manifest、三个声明资源和可选 bundle-lock；没有读取 `_support/`。不存在根级 full-flow manifest；覆盖表中的业务阶段均未被这个图调度。条件 JSON Schema 约束报告形状，也不会变成流程条件或并行控制。

网络连接、DNS 查询和发送通过 verifier 拒绝；编译/schema 引用解析没有进行网络读取。流程来源的在线研究发生在验证之前，来源与可变版本说明在根 SOURCES.md。

失败历史保留：[initial-tooling-error.json](initial-tooling-error.json) 是校验脚本初始化错误（编译器尚未调用），[attempt-01-results.json](attempt-01-results.json) 是首轮完整结果。

首轮 GitLab 基线退出 `2`：报告小数能通过原 schema，却不能通过当前 `canonical_bytes`/MethodContent codec。仅在此方法包把小数表示为精确十进制字符串，收窄 schema 为 string/integer/null并同步 hash；没有更改核心。最终三份报告复验通过。

主要限制：业务条件分支、一般循环/并行、可信外部状态/角色、注册的 wait source/catalog 与方法生产装配不完整。Git/CI/部署由外部系统执行；不能据静态通过声称本方法已承载完整流程。具体逐项见 ../../COVERAGE.md 和 ../../GAPS.md。
