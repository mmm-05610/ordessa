# Reuse Map：按模块执行，不自由拼上游产品

2026-09-27。本表为实施取材裁决，不是完成声明。优先级：已有领域实现 → 已审平台公开包 → 许可明确的小型移植 → 本产品特有薄实现。没有源码/许可证据的候选不计入直接复用成果。

## 固定来源

- 本仓 Profile：`b77f9f23cb`，`plugins/profile/src/ordessa_profile/`。只迁入该领域及必要测试，不整合旧分支宿主改动。
- 前端平台观察点：`54c2ef4110`，`packages/desktop-platform/ui`、`ui-components`。本轮读过出口与组件装载实现；尚不是已批准集成基线。
- Hermes：`8c9fe964009096e46f44292d036c1e0ac33c3026`，具体链接见 [research](research.md)。本轮固定源码/根 LICENSE 请求再次失败（web cache miss，直接请求 HTTP 429）。停止重试；只能列有条件候选，不能宣称许可已核实。
- Roo：`b867ec9145750d0ae1ff7f02d35406e9bf2a0b16`，本轮再次取得根 Apache-2.0 LICENSE。只参考配置保存/唯一性验证模式，不引入 VS Code 服务。复制具体符号仍需读取完整文件及 notices。
- ZCode：`29628c9acdb81b703bbd4080c207a0e7ce5e276e`，已有 [Chat 取材单](../chat-zcode-reuse/research-plan.md)。本批不重复移植聊天组件、不将未核实的模型选择器当作已指定代码源。

## 强制模块决策

| 目标模块 | 复用源/符号 | 保留、适配 | 明确不搬 / 必须新写 | 验收 |
| --- | --- | --- | --- | --- |
| 存储与 CRUD | 本仓 `storage.ProfileDatabase`、`profiles.ProfileService`、`repository.py` | 原 ID/修订/事务/CAS；增量迁移 | 不重建数据库、不照搬单字段 session key | G05/G17，旧库副本升级两次 |
| 逐项解析 | `resolution.resolve_profile_items/resolve_session_items/apply_overlays` | 稳定 facet/item 粒度、覆盖来源 | 新补 reset/缺席校验；不深合并未知数组 | G06/G08/G13 |
| 会话切换 | 旧 `sessions.py` 仅选择与覆盖逻辑 | 保存原产品语义和测试 | 实际应用 journal/fence/receipt 必须改造；不得复用 DB readback 作为证明 | G07/G09–G12 |
| 页面基础 | `@ordessa/ui` 的 Panel、Toolbar、ScrollArea、Button、Input、Select、Checkbox、Field | 直接 import 公共出口，沿平台主题 | 不复制 CSS 控件、不拉另一套设计系统；现有 Select 是基础 select，不假定有完整两级树 | G18 |
| 配置区装载 | `@ordessa/ui-components/react` 的 ComponentOutlet/useUiBinding | 绑定、代次、错误隔离交给平台 | Profile 仅写 editor/settings 两个业务目录；不造第二组件 registry | G01/G16/G19 |
| 能力勾选表单 | Hermes `profile-config.tsx` 的 CheckList/CapabilityEntry（候选） | 名称/说明/勾选层次，适配平台 Field/Checkbox | 不搬 Hermes SDK、bot store、dirtyModel/dirtySkills 品牌字段 | G13/G18；许可未过则用平台基础件薄组合，记录未复制 |
| 创建表单 | Hermes `create-profile-dialog.tsx`（交互参考） | 聚焦、验证、提交/取消 | 中文 displayName 用本规格；不搬目录 slug、home 创建或 SOUL 写入 | PM03/PM04 |
| 管理导航 | 平台控件 + 本领域薄组合 | Harness→Profile 搜索/展开/选择 | 不移植 VS Code 整套 Profile 编辑器/DI；不新增平台业务树 API | G02/G18 |
| Chat 选择器 | 平台 overlay 与基础控件；若集成基线已有可复用选择器壳则直接消费其公开 API | 两级选择、键盘、所选名称 | 不 import model-provider 私有组件；没有公共壳就本域薄组合，不为两个控件新造平台框架 | G20 |
| 字段与设置贡献 | 本仓 facet 语义 + 新轻量契约 | schema/范围/所有权 | 自写 Ordessa 的 scoped 目录、CAS 绑定；Roo 只作校验思路参考，不搬整类 | G01/G16/G19 |
| 模型/Skill glue | 各现有业务插件公开目录、选择器 key、服务 | 用资源引用与自己的 UI 实现 | 不复制它们的仓库/凭据/资源正文；无公开接口时列接缝，不绕进私有 store | G15/G16 |

“新写”不是失败：产品特有的所有权、应用证据和覆盖规则没有可等价搬入的上游。禁止以复用为名引入 Hermes home 模型、Roo 全局 active provider 或另一套会话权威。

## 移植账格式

每个目标模块记录 `target / disposition(direct-import, adapted-copy, reference-only, original) / sourceRepo / commit / path / symbols / license / retained / removed / tests`。直接复制另保存原版权、许可证、NOTICE 和修改说明；本仓直接复用记保真 diff，不制造上游移植数量。

远端不可读时按本表已批准的候选回退，不无限搜索、不安装一套相似应用顶替。先完成有确定来源的模块；最终明确哪些只参考、哪些真正复制，禁止把整个 Profile 标为“复用 Hermes”。
