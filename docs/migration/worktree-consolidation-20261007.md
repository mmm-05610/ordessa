# 单一开发树整合 · 2026-10-07

用户授权：暂停现有工作，更新并整合所有工作树，最终保留一条干净的最新树供今晚开发。此次不推送，不改变 main 分支，不开展下一轮业务设计或补全所有功能。

## 唯一开发入口

目录：`/home/maoqh/projects/ordessa`。
分支：`codex/nightly-development-20261007`。
结构基线：`386b64080e43b506e65f74ac3b2e662c1b1ed31c`（032 暂停检查点，含 server-compat 和品牌 legacy 执行路径退役；仍非 PRODUCT_READY）。

加入软件工程 Harness 方向文档、原根目录规划材料、未提交前端工作区成果、DSH/Grok/Kilo 成果。保留较新的状态权威和路径，不把旧副本覆盖回去。

## 原始成果与恢复

仓库外恢复档案：`/home/maoqh/projects/ordessa-worktree-archive-20261007-LrStzx`。该目录为私有本地档案，不进入 Git，不上传。旧目录及其中环境、忽略文件、截图和运行数据整体保存。分支和提交保留，不删除历史。

未提交源码先固定为：
- `/home/maoqh/projects/ordessa` → `72590649e7670d76aa4de7384f260271b427f948`
- `/home/maoqh/.codex/worktrees/agent-tools-product/ordessa` → `3aab4996e23c8cefac0d646a426f883759490034`
- `/home/maoqh/projects/ordessa/worktree/021-ordessa-product-closeout` → `a3de71292efb5d3142fa6b1d01b98191a2be7e10`
- `/home/maoqh/projects/ordessa/worktree/026-open-environment-migration` → `4d381b5b44b909ee19a82f19eda0699e7989e1a0`
- `/home/maoqh/projects/ordessa/worktree/tasks/i003-wire-timing` → `3bb904cf9c625a3a64603ddeea40b0f1e87724c3`

其他源码来源：031 `3bbf68b41b01988b644934e5b436885b213eaecf`、consolidated-core `c20ce5853dba682602e1aa52ef6949d5fa190088`、w019 `2b050e24674132e88dd381e47bed149aa7fa0b44` 已在整合祖先中。026 的三个独有提交在新路径核对后，代码已存在；仅旧状态记录和旧平台路径不同，不复活旧目录。

恢复源码可根据上述 SHA 创建新的 worktree；忽略环境和本地资料从私有档案按需取回。档案中的原 .git 链接保存为 .git-worktree-link，它是历史定位信息，不是可直接使用的 Git 工作树注册。不要用旧档案覆盖根目录或把密钥/数据加入提交。

## 冲突处置

- 主树未提交规划材料中与 026/031/032 实施记录冲突者，以最新实施记录为准，原稿在快照分支保留；原树独有设计资料纳入。
- 026 前端控件和命令生命周期负例按新 extension-host/workbench 路径纳入；旧 extensions.lock 的构建摘要不覆盖较新锁记录，实际构建仍须重新生成并核验。
- DSH/Grok 独立 ACP 包纳入；将已退役 ordessa_harness_api 导入改为 pacthold.harness_contracts，发行依赖不再要求旧 API 包；invocation 测试导入改到 agents/access。DSH 新公开 provider 入口不再使用旧的惰性聚合导出；现存 native/production 模块保留原有直接消费方式。
- 021 恢复与重选源码绝大部分在最新结构中已存在。保留新 profile 单一配置权威、包依赖和测试；不把旧 draft glue 测试覆盖新设计。
- 旧 Pi 离线历史导入脚本及对应新增测试依赖已退役 server-compat SessionRecords，没有新归属，**未纳入正常源码**；完整保存于 `a3de71292e` 与旧树档案。相关功能不是“迁移完毕”。
- i003 的旧 bundle 构建时间/摘要不覆盖较新构建记录；原生成物快照保留。

## 本次验证

在整合源码上使用既有 Python 测试解释器，PYTHONPATH 指向整合树的包源码；未安装二进制，未调用真实模型或重启服务。

- 首次跨品牌同时收集产生同名 test_provider/test_configuration 冲突；importlib 模式又暴露测试按短名导入辅助模块的限制。后续按品牌串行单独运行，没有改断言。
- DSH 全套：230 passed，1 failed。失败为 test_independent_dsh_model_wheel_without_server_monolith_product。
- Grok 全套 + 核心文件/AST 边界：237 passed，1 failed。失败为 test_independent_grok_build_model_wheel_without_server_monolith_product。
- 两项失败都在 pip check：Pacthold 引入 pydantic-graph==2.54.0 后，现有离线 wheel 测试只安装四个内部包、未带第三方闭包。源码测试通过不代表隔离发行通过，不能跳过或删除失败。

全量产品、真实 Harness、GUI、持久数据恢复和 wheel 第三方闭包未在此轮验收。Git clean 只表示代码有固定检查点，不表示产品全部完成。

## 范围裁剪

按 incremental-work-order 的固定 SHA、来源保留、合并后核验原则执行；这次是用户明确要求的暂停成果整合，不另建任务队列或派 Agent。保留已登记失败，不以“全部绿”作为整合声明，不把局部源码整合说成旧链清理完成。

## 根目录开发环境与最终复验

- 九棵子树完整移出仓库，原 Git 注册注销；最终只登记根目录。旧分支与源码快照仍可恢复。
- 原根目录未跟踪的两份接入 ZIP、新架构 ZIP/DOCX 移入私有档案 root-local-materials；其他工作树遗留证据/历史目录完整移动为 worktree-remainders。凭据和注册运行例外不读取、不删除。
- 根目录 node_modules 由 npm ci --ignore-scripts --offline 重建（553 packages），没有把旧树的 workspace 链接用于开发。
- 根目录 .venv 从既有测试环境复制，再把 42 个当前 Python 项目重新 editable 绑定到根目录。补装产品声明缺失的 SecretStorage 闭包；pip check：No broken requirements found。Pacthold/Server/DSH/Grok 导入实际指向根目录源码。旧环境原件保存在档案中。
- Assets 归位后的 6 个 build.mjs 仍指向 plugins/tooling，已修正为根 tooling；旧忽略 dist 内的 preview-electron.cjs 触发真实发行卫生门，完整归档旧 dist 后重新构建，未放宽门。
- UI 工作区控件的键盘焦点判断改为使用事件目标与局部菜单项，不读取全局 document；未改断言。此前 bare-root 守卫 1 红，修正后全套通过。
- 最终 Workbench：14 个 Vitest 文件，89 tests passed；实际 Desktop 构建与 DI/connection-kind 身份正反例 8 tests passed，完整 npm test exit 0。产品 21 个启用扩展成功构建，extensions.lock 随构建更新。
- 最终 @ordessa/ui：7 files / 36 tests passed；jsdom requestSubmit 警告仍显示，不隐藏。
- 最终 extension-host ui-command-lifecycle：1 file / 5 tests passed。
- 两项独立 wheel 闭包失败保留在 known-issues；本轮未变更其断言或宣称已修复。

今晚执行命令使用根目录的 .venv/bin/python 与 npm，不要继续使用档案中的旧 editable 环境，也不要在已归档目录恢复实施。
