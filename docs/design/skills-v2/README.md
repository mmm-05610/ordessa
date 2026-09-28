# Skills 插件完整方案

日期：2026-09-28。状态：**DESIGN_REVIEW_READY**；尚未实施或验收。本包采用 Spec Kit 的 spec、research、data model、contracts、plan、tasks、verification 组织方式，未声称运行其生成命令。

## 这次定下的边界

Skills 是 `plugins/assets/skills/` 中一个独立业务插件：保存 Skill 包、来源、版本和启用分配，并提供 Settings、项目、Profile 与 Chat 的贡献。它内部按品牌实现配置适配器，注册到 [Harness v2](../harness-v2/README.md)。Profile 保存选择和覆盖，Harness 负责运行实例中的装载、重载及恢复。

**内容存放、默认分配、会话有效集合是三件事**。将 Skill 导入公共库并不自动启用；“项目级”指 Ordessa 按项目身份分配，不等于写入项目的原生 `.claude/skills` 等目录；“全局”指当前服务域内该用户的默认分配，不是管理员对所有用户的强制策略。

范围解析：用户全局通用 → 用户全局某 Harness → 项目通用 → 项目某 Harness → Profile → 会话临时覆盖。同一 Skill 后层明确启用/禁用覆盖前层；未声明则继承。上级强制策略另外校验，不能被 Profile 覆盖。

内容修订与使用修订采用**显式批准固定版**：安装新版不会自动更新分配；用户批准更新某范围绑定时，该绑定才指向新版。一次会话提交另冻结有效集合。此语义保留现有 Skills 实现 `server_profile_assets` 的固定修订，不套用 Prompts“跟随最新正文”的规则。

## 阅读顺序

1. [spec.md](spec.md)：用户故事、FR 与范围。
2. [data-model.md](data-model.md)：内容、分配层、有效集合及版本。
3. [contracts.md](contracts.md)：服务、贡献、原生发现和执行接口。
4. [harness-adapters.md](harness-adapters.md)：品牌装载、冲突、应用证据。
5. [ux.md](ux.md)：设置、项目、Profile 与 Chat 的入口。
6. [research-and-reuse.md](research-and-reuse.md)：官方机制与现有代码复用。
7. [plan.md](plan.md)、[tasks.md](tasks.md)、[verification.md](verification.md)：落地顺序与验收。

本包是完整设计，不是已有功能的完成证明。当前实现参考树为 `worktrees/plugin-assets-skills-impl @ 752f148b1b`；main 尚无 `plugins/assets/`。落地需等平台/Profile/Harness 接口的已验收集成 SHA，不能从相邻脏树直接复制发布。
