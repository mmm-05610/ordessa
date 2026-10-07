# 032 基线整合检查点

日期：2026-10-07。状态：`BASELINE_INTEGRATED`，不是 `STRUCTURE_CLEAN`。

## 已完成

- 从 Agent Tools 固定提交建独立实施树，纳入 026 的 3 个独立提交及 Jev 固定交付。
- Jev 的四处文本冲突按能力并集处理：原配置贡献发现、生命周期、输入、材料操作与新增只读 offer/assessment 共用同一个 Environment 和 Registry；两个问题登记区都保留。
- Codex 自动合并复查保留 termination、channel binding 与只读编译路径；未增第二执行器、状态仓库或 apply 入口。
- 新增 9 个自包含真实 core 组合测试，native effect 全用失败哨兵，证明配置路由和 pure-read 在同一 provider 共存、非法声明拒绝、原授权类身份及服务单实例。
- 更新当前离线评估计划的三个源码摘要字段。保留完整 digest、授权和 unknown 断言；未改历史证据。
- 从当前前端源码重构建产品后仅同步两个 bundle 摘要，extension id 和用户数据标识不变。
- 三名子代理分别完成接缝审查/组合测试、目录审计/指纹重钉、退役方案审查；主会话拥有唯一 Git 写入和串行测试槽。工具没有提供可核实的费用数字，费用不作推测。

## 实测验证

Python：独立 `.venv-cleanup`，CPython 3.12.14。核心、Decision、Codex、environment-api 的 `__file__` 均核实位于本实施树，没有沿用其他工作树的 editable 来源。

| 命令/集合 | 结果 |
| --- | --- |
| pytest tests/boundaries/test_integrated_agent_capabilities.py -q | 9 passed，exit 0 |
| pytest plugins/harness/codex/tests -q | 278 passed，exit 0；含隔离脚本进程测试，不是实际 Codex 模型验证 |
| decision/checks/offline_acceptance.py --scenario T64 | T64 passed；固定 baseline/current 核心测试各 57 passed，exit 0 |
| pytest packages/backend/decision/tests -q | 359 passed，exit 0 |
| Agent Tools integration runtime_admission/configuration_provider_admission/configuration_provider_contract/invocation_authority/node_publication/core_method_lifecycle | 220 passed，exit 0 |
| host 目录 package-local vitest run --maxWorkers=1 | 122 passed，exit 0 |
| npm test --workspace @ordessa/ui-components | 114 passed，exit 0 |
| Workbench vitest + node tests | 86 + 8 passed |
| npm test --workspace @ordessa/workbench-interactions | 1 passed，exit 0 |
| npm test --workspace @ordessa/native-bridge | 16 passed，exit 0 |
| git diff --check、旧夜批 shell bash -n | exit 0 |

最初错误如实保留：Decision 的 importlib 收集模式与原套件裸 import 不兼容（2 collection errors）；改用原 runner 模式后 355P/4F，分别为缺 wheel/回执与旧 Codex 源码指纹。原验收脚本准备 wheel/回执并更新当前计划后全套 359P。Host 不是注册 npm 子 workspace，最初 workspace 选择无效；随后在真实 package 目录执行通过。Workbench 命令额外传了已有的 maxWorkers，引发 interactions CLI 重复参数；按原脚本单独复跑 1P。未改断言或 skip。

证据：decision-suite.xml、agent-core-seams.xml、decision-baseline/receipt.json、codex-plan-repin.md。未把重跑/重叠集合加成一个误导的总数。

## 目录统一

项目内只保留 `worktree/`。原 worktrees 下三项均同名迁入：注册树用 git worktree move，两个归档/证据目录普通同设备移动。迁移前未发现相关进程 cwd、FD、mount；未停服务。

`consolidated-core` HEAD 仍为 `c20ce5853dba682602e1aa52ef6949d5fa190088`，Git status clean，移动后虚拟环境 import 来自新目录。修正其 54 个虚拟环境路径文件与 1 个生成的图标清单路径；保留 ignored 环境/构建数据。两个归档目录仍分别 160 和 86 个文件。只删除了迁空的父目录，没有删除内容或分支；可反向 git worktree move/移动恢复。

主树的 ignore 和两份活跃夜批路径 guard 更新；原有 token ignore 改动保留。`.git/worktrees` 和 Codex 全局托管目录不改。

## 来源覆盖与未纳入成果

consolidated-core 和 021 已提交线都是 Agent Tools 祖先，无需二次合并。早期 i003 的 live wire cell/getter 行为已在当前 host-services 中存在，w019 的 Sessions/错误断言已在当前 test-agent-shell 中存在，不重放旧目录补丁。

Agent Tools 未提交的 Harness/Kilo/dsh/grok-build，026 未提交的 workspace/UI，021 未提交的历史恢复仍在各自原树。没有纳入本基线，也没有删除、stash、reset 或提交这些成果；后续须通过独立提交按新归属整合。

## 明确剩余

- Agent/Profile/Harness 根、runtime/server compat 仍是整合基线里的旧链，本轮尚未删除；plan 和 retirement-map 定义下一步退役，不能报结构完成。
- pure-read callable 的构造验证存在，但 core registration stage/commit 的 shape 复查仍只覆盖原方法；调用入口会拒绝缺 callable。该原有保障间隙登记供迁移时补负例，不冒充已修复。
- 未跑全 Server/Harness、所有 CLI 套件或 GUI；未调用真实模型、读取 Token、安装品牌二进制、迁移真实数据、重启用户服务。
- main HEAD 未合并，其他活跃工作树未改源码；没有 push。
