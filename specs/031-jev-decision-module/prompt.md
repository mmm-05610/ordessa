# 主执行者启动提示词

由用户发送后开始实施；授权解释见 [实施交接](handoff.md)。

```text
goal：在 /home/maoqh/projects/ordessa/worktree/031-jev-decision-module 按 specs/031-jev-decision-module 完整实施多轮决策模块，落点 packages/backend/decision/。源码基线 e4714eba00a78ba04c5b53318830a0d409e76bbe，分支 codex/jev-decision-module。先读 handoff.md 和全部方案、契约、任务、验收与状态，核对 HEAD/status 和仓库规则。
允许本树内实现、隔离本地依赖安装、离线测试及检查点提交；不改 main、其他工作树或共享虚拟环境。记录此次实施授权，保留设计阶段历史，不把 NOT_RUN 批量改绿。
按 JD001–JD010 依赖推进。你持有契约、共享装配、Git、账本和复验；接口冻结后按 plan 的独立切片派最多三个子代理、深度一层，子代理不改契约/账本/共享文件、不做 Git 写操作，测试和安装串行。
复用原版 pydantic-graph 与官方 Jev SDK，不 fork、不写第二执行器或 DSL。业务流程外部定义；Jev 只选择/评分，配置由外部组合器与原 owner 提供，不硬编码 Profile 配置种类。
决策严格只读、只返回提案，不创建、配置或调度 Agent；JD007 在原 Agent 机制补公开纯只读接缝，不建第二 registry、状态权威或调度器，不用私有 DB 或 prepare 试探。
逐场景验证正例、反例、缺席、取消、预算及崩溃窗；真实上游库配假网络验证机制，不冒充真实模型质量。局部阻塞先推进无依赖任务，检查点不停工；全部剩余任务确需授权时报告缺口，不越权、不报全部完成。
真实 Jev/Harness 调用、凭据读取、服务重启、用户数据迁移、merge/push 另行授权。最终交付 SHA、逐场景证据、继承红与未验证项、费用及清理记录，以及可直接运行的离线验收入口。
```
