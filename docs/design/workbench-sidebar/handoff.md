# Workbench 统一侧栏：执行交接

2026-09-27，用户授权记录方案、创建独立 worktree 并交由其新会话执行。使用 Spec Kit 的 spec/plan/tasks，不另建派工单体系。

## 固定起点

- 工作目录：`/home/maoqh/projects/ordessa/worktrees/workbench-sidebar`
- 分支：`codex/workbench-sidebar`
- 开发基线：`1ea2084dfbbc7e488f085da7e1ad9b2298ccc149`，来自前端平台已提交检查点，含迁移后的 `packages/workbench`。
- 根目录保持 `main @ cd7d31f3cf`；本批不操作根目录的 Git 状态。
- 平台 C8 在另一树仍有未提交修改；没有复制、提交或修改它们。本基线仅为开发起点，不冒充平台已集成验收。执行者先测基线，最后与平台新检查点做只读冲突盘点，不自行合并平台/main。

## 写入边界

生产源码与测试只写 `packages/workbench/**`；执行记录只写本树 `docs/design/workbench-sidebar/**`。公共 API/Token 不改。apps、products、其他 packages、plugins、根 lockfile 均不改；构建若生成这些文件，记录差异并勿提交，不得破坏已有用户改动。不从邻树借 node_modules 或污染其环境。

这棵树的设计文档是执行快照，勾选 tasks 并写 report.md；根目录文档保留设计来源，不要求两个会话双向同步编辑。

## 执行纪律

主代理负责计划、派发、审 diff、复跑门禁和提交；不直接写生产代码。派一个 Workbench 实现子代理，必要时另开只读源码复用/独立审阅子代理；同一文件一写者，子代理不操作 Git。不按文件强行并行拆出互相依赖的实现。

按 WS01–WS10 连续推进。包内编译、测试、样式问题自行修复；阶段提交不是停点。公共接口变化、范围外生产修改、安全/授权变化必须报告，不可自行扩大；先继续不受阻部分。不要为通过门禁删断言、跳过测试或假称浏览器验收。

真实浏览器检查可以用本树构建和临时用户数据、受控插件；不接真实账号或模型，不启停现有用户服务。记录自己创建的进程并自行收尾。按 spec 的尺寸/缩放/长内容/键盘与浮层矩阵交付截图。

ZCode 固定 SHA 与提取边界见 plan.md。本机只读参考当前在 `/tmp/ordessa-module-research-dKxlTo/zcode`；这是可失效的缓存，不是依赖。缺失时按固定上游 SHA 获取到本树忽略的研究目录或临时目录，检查 Apache-2.0 及必要许可声明，绝不把研究仓整个提交。

交付条件：WS01–WS10 逐条有证据；原公共注册 fixture 可用；代码仅落本包；WorkBench/根回归/typecheck/build/适用 Electron 检查实际跑过，失败逐 ID 说明；真实浏览器证据齐全；来源与许可明确；提交实现检查点和 report.md。无法执行的门禁写未验证，不报全绿。不 push、不合 main、不删分支。

## 启动提示词

在本目录以 `/goal` 启动，目标是完成本目录 spec.md、plan.md、tasks.md 的全部 WS01–WS10 并提交可审阅实现，而不是只完成规划或给出建议。先读仓库指令和本交接文件，再执行上述边界、分工与验收规则；全过程不要修改主树或相邻树。
