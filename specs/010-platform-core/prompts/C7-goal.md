/goal 在当前 worktree `/home/maoqh/projects/ordessa/worktrees/platform-frontend`、分支 `codex/010-platform-frontend` 完成已授权的 C7 通用 UI 组件机制。目标是 `specs/010-platform-core/tasks.md` 的 T030–T036 全部完成、U01–U16 全部有实际通过证据、增量报告达到 C7_IMPLEMENTATION_REVIEW_READY，并提交可审阅的检查点。原 C goal 已结束，原结果保留，不从头重做。

先读 AGENTS.md、apps/desktop/AGENTS.md、.specify/memory/constitution.md、specs/010-platform-core/contracts/ui-components-platform.md，再读它引用的通用契约/计划/验收。完整设计快照在 amendments/ui-components；12 个 Agent UI 领域接口和 D 系列任务只供背景，本次不实现。采用现有 Spec Kit 流程，不使用派工单 skill。

主代理负责跨包边界、派发、逐项审阅、亲自复跑、报告和 git；生产代码由子代理按单包所有权处理。不同包可并行，同包单写者；所有子代理只在本 worktree 工作、不操作 git。公开契约先落定再派依赖实现，测试串行执行。

交付包含通用 ui-components 包、作用域登记与消费、冻结选择、原子批次、实例代次、React Outlet、错误隔离、旧回调 guard、产品通用装配、共享 API 真实构建和 U01–U16 证据。复用当前 Lumino/ResourceScope/构建机制，不建第二服务调度器，不削弱既有 scope 真实性验证。业务字段与默认 Agent 实现不得进入核心。

遇到类型、夹具、依赖安装、构建路径等本范围问题自行定位修好并继续。阶段提交是检查点，不是停工点；依赖项暂时阻塞时推进其他独立项。不要因为一条测试红或一个跨包接线错误就结束 goal。只有确需改变已审定契约/持久数据/权限，或全部剩余任务均被外部条件阻塞时，才一次汇总证据与最小裁决请求；不得靠扩大范围、自动 fallback、skip 或放宽断言换取完成。

不修改 Python/Go/其他 worktree/root main，不启停用户服务、不调用真实模型、不 push、不合 main。锁文件由正常安装/构建工具更新。结束前亲自检查全部 diff，记录真实退出码和原测试 ID 差分；别把受控 UI 验证写成真实 Harness 联调。达到全部完成标准后停在待审状态。
