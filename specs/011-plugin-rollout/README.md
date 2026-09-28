# 今晚插件实施入口

日期：2026-09-28。用户已授权准备并启动今天审定的实施包。分工为 **1 Codex + 3 ZCode + 5 Qoder**。本目录采用 Spec Kit 的 spec/plan/contracts/tasks/checklists；不使用派工单流程。

根工作树保持 main。九个新树从同一设计快照创建；该快照父提交为 main `cd7d31f3cfba6a0e1ec65f9a13014c6b9751540b`，**尚不包含未合入的平台实现**。C0 先收口并发布 foundation，其余树先做独立工作，取得真实检查点后接线。

**正在运行的 platform-server 会话保留原收尾所有权。** 本批不等它才开树，但任何新会话都不得修改原树、未提交文件、任务状态或进程。C0 先推进其他平台审核与 Harness 独立工作，等 B 发布最终提交后再固定 SHA 集成；不接管或重复派做 B 正在进行的收尾。

## 会话与入口

| ID | 执行者 | 范围 | 工作目录 | 启动提示词 |
| --- | --- | --- | --- | --- |
| C0 | Codex | 公共基线、Harness 与总集成 | `/home/maoqh/projects/ordessa/worktrees/011-c0-foundation-harness` | [复制](../011-c0-foundation-harness/prompt.md) |
| Z1 | ZCode | Profile v2 | `/home/maoqh/projects/ordessa/worktrees/011-z1-profile` | [复制](../011-z1-profile/prompt.md) |
| Z2 | ZCode | Chat 展示、创建与输入扩展 | `/home/maoqh/projects/ordessa/worktrees/011-z2-chat` | [复制](../011-z2-chat/prompt.md) |
| Z3 | ZCode | Model-provider v2 | `/home/maoqh/projects/ordessa/worktrees/011-z3-model-provider` | [复制](../011-z3-model-provider/prompt.md) |
| Q1 | Qoder | Skills v2 | `/home/maoqh/projects/ordessa/worktrees/011-q1-skills` | [复制](../011-q1-skills/prompt.md) |
| Q2 | Qoder | Prompts 与命令模板 | `/home/maoqh/projects/ordessa/worktrees/011-q2-prompts-commands` | [复制](../011-q2-prompts-commands/prompt.md) |
| Q3 | Qoder | 原生子代理定义 | `/home/maoqh/projects/ordessa/worktrees/011-q3-subagents` | [复制](../011-q3-subagents/prompt.md) |
| Q4 | Qoder | MCP 定义与托管 | `/home/maoqh/projects/ordessa/worktrees/011-q4-mcp` | [复制](../011-q4-mcp/prompt.md) |
| Q5 | Qoder | Permissions 与原生 Sandbox | `/home/maoqh/projects/ordessa/worktrees/011-q5-safety` | [复制](../011-q5-safety/prompt.md) |

每份 prompt 仅作为短入口；边界在 [spec](spec.md)、[实施与所有权](plan.md)、[检查点协议](contracts/checkpoints.md)。各线在自己的 feature 目录勾任务和写报告，公共设计只读。发布不是合并 main；用户另行决定主线合并和推送。

## 三个先发契约

- C0：foundation → harness-api（含 ACP 准入/附件/命令/权限前置接缝的真实类型与 proof）。
- Z1：profile-api；Z2：chat-api。二者先发布公开类型与受控调用 proof，再完善各自页面/存储。
- Q5：permissions-api。MCP 定义阶段可先做，真实工具转发等待它与 C0 接通。

发布这些契约不等待业务插件全量完成，避免“父实现等消费者、消费者等父实现”的死等。它们只是可消费里程碑，生产完工仍须真实全链证据。

## 已有成果与撤销项

平台 UI foundations 和 Workbench 侧栏已有提交，由 C0 集成审核；不新开重复实施线。`agent-ui-implementation` 整包及统一 12 项 Agent UI 组件实施已撤销；C7 通用机制保留，业务展示按 Chat 等实际所有者实现。`harness-configuration` 是调研输入，不是八品牌全部适配任务。

Model-provider、Profile、Skills 的旧实现必须先做沿用/修订/删除表。共享文档仍写“未授权/待派发”时，以本次实施授权和本目录的责任分配为准；功能语义仍按对应包，不自行改产品要求。
