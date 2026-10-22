# Codex / Pi：真实日志统计任务

2026-10-22，经正式 Ordessa Server/CLI 分别运行 Codex 和 Pi。两次运行从同一份未实现源码和固定测试出发，没有共享生成结果。

## 任务

实现 JSONL HTTP 日志统计：按服务汇总请求数、5xx 数量、错误率、平均延迟和 nearest-rank P95；校验输入并报告原始行号；通过已有 CLI 读取日志文件。允许修改 `src/stats.py`，不允许修改测试或原有 `src/report.py`。

## 结果

| Harness | 环境 | 初始测试 | 宿主独立验收 | 全流程耗时 | 异步受理 |
| --- | --- | --- | --- | --- | --- |
| Codex | Local | 19 failed | 19 passed | 52 秒 | 0.374 秒 |
| Pi（OpenCode Go / kimi-k2.6） | Local | 19 failed | 19 passed | 105 秒 | 0.366 秒 |

两次运行均只改变功能源码。测试文件及原有 CLI 文件的 SHA256 保持不变。任务终态为 `completed`，宿主另外执行 pytest 验证产物；没有把 Agent 的完成消息当作测试结果。这不是速度或模型能力基准测试。

## 调用链与来源

正式 CLI 创建 Profile 和 Local 环境、导出 endpoint、启动 Agent，并通过 `agents.native.request` 提交任务；新的 CLI 进程调用 `query` 和 `events`。原生协议分别为 `codex-app-server/1`、`pi-rpc/1`。事件中观察到读取文件、运行测试及编辑源码。

源码 main 为 `90653d2359476251535c2bb939d704b8964ce469`。使用已验收的 Foundation 安装环境，其源码提交 `726cd2c18602513e155ae87de0f7787d58b3ae59` 与该 main 的跟踪文件树相同。本次没有改动 Ordessa 产品代码，没有安装依赖。

[脱敏回执](receipts.json)保留时间、测试结果、源码与测试摘要、受理时间和原始回执 SHA256。原始日志、账户材料和个人主机路径不发布；该摘要不是能够独立重放原运行的完整归档。

## 清理与边界

两次任务的 Server 和 Agent 进程均经宿主核查已退出，process-release 与 environment release 完成。Local provider 不提供目录删除操作，成果目录保留；本轮凭据副本和生成的 HTTP token 已清理。驱动退出时对已释放实例再次调用 stop 得到 unknown，未用该回执证明进程退出。

本次验证小型单轮开发任务，不覆盖组件化 Profile、动态记忆、自动选派、审批回调或 Pi 并发任务。Local 不提供安全隔离。OpenShell 四组合及其他 Foundation 能力见 [Foundation 1.0 验收](../foundation-1.0-20261022/README.md)。
