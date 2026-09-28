# 原生子代理定义：Spec Kit 实施方案

日期：2026-09-28。状态：**DESIGN_REVIEW_READY**，仅设计、未实施、未验收。本包不改变本地 `main`、核心或运行服务。实施须先记录平台/Profile/Harness 的最终集成 SHA，并另获实施授权。

目标业务位置是 `plugins/assets/subagents/`（目录为资产插件族分类，不是新的 Assets 宿主）；本文档目录以 `native-subagents` 命名，以免与 Ordessa 将来跨 Harness 的派工基础设施混淆。插件只拥有**可复用子代理定义、不可变版本、选择/分配及对各 Harness 定义入口的适配**。运行中的代理、通信、恢复、审批、进程/工作树生命周期归现有 Harness/执行治理设施。定义内容绝不能作为权限授予书。

## 已定裁决

- 一份定义可在公共库、项目专用或 Profile 专用范围存在；“保存”不等于“启用”。用户全局/项目默认及 Profile 选择只保存引用和版本，不复制正文。普通 Profile 显式切换在下一次输入才应用，不中断输出，成功后按 Profile 规则清会话临时覆盖。
- 对同 Harness 的原生定义载入，只走 Harness v2 `harness.configuration-adapters`；适配器在本业务域内部按品牌组织。Harness 负责隔离配置根、装载/重启恢复、核验，插件不直接覆写用户 HOME/项目原生目录。
- Claude Code、Codex 官方有自定义子代理定义入口；Pi 官方仓给的是**可选扩展示例**，不是内建能力。Pi 只有在 Harness 明确提供经过审核的 extension-backed 入口并通过同一产品链后才能显示可用；不能以“Pi 内建”或模型口头描述冒充。
- Profile 旧实现里的 `list_subagents`/`run_subagent` 工具、授权边、递归与超时是派工/策略功能，不整体迁入本插件。此插件绝不注册第二套派工工具。

## 阅读顺序

1. [spec.md](spec.md)：用户故事、边界与 FR。
2. [data-model.md](data-model.md)：版本、引用、分配、快照。
3. [contracts.md](contracts.md)：服务、注册、授权和失败语义。
4. [harness-adapters.md](harness-adapters.md)：品牌能力与运行装载。
5. [ux.md](ux.md)：管理、Profile 和会话可见入口。
6. [research-and-reuse.md](research-and-reuse.md)：官方机制与精确复用位置。
7. [plan.md](plan.md)、[tasks.md](tasks.md)、[verification.md](verification.md)：阶段、追踪、门禁。

这里的接口名称是**目标契约**，不是已发布的符号。不能以本方案存在推断三品牌现已可用。当前 `plugins/assets/`、Profile/Harness v2 交付状态均需以 T00 的代码事实为准。
