# Z1 移植账（reuse ledger，PV-02）

格式按 reuse-map.md：target / disposition / sourceRepo / commit / path / symbols /
license / retained / removed / tests。随实施推进回填“落地 SHA/测试”列。
**Hermes 许可未核实：本线禁止复制其任何代码，只允许交互模式参考（reference-only）。**

| # | target | disposition | source | commit | path/symbols | license | retained | removed | tests | 状态 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 存储与 CRUD（storage/repository/profiles 服务） | direct-import + adapted | 本仓 plugin-profile-impl | b77f9f23cb | `plugins/profile/src/ordessa_profile/{storage,repository,profiles}.py`：ProfileDatabase/ProfileService/idempotency/CAS/归档 | MIT（本仓） | 稳定 ID、修订不可变、BEGIN IMMEDIATE、幂等键、归档 | 单字段 session key 主键语义（升 canonical ref）；read-back 冒充证明 | 旧 70 测试保真 + 迁移幂等/碰撞门禁 | 完成（f5435be938；test_migration_v2.py） |
| 2 | 逐项解析（resolution） | adapted-copy | 本仓 plugin-profile-impl | b77f9f23cb | `resolution.py`：resolve_profile_items/resolve_session_items/apply_overlays | MIT（本仓） | 逐 (facet,item) 合并、provider absent 不遮盖、来源携带 | 无 | 新增 reset 差异/四值状态/target-default 指纹投影；数组不深合并 | G06/G08/G13 新反例 | 完成（f5435be938；test_sessions_v2.py） |
| 3 | 会话切换/选择/覆盖（sessions） | adapted-copy | 本仓 plugin-profile-impl | b77f9f23cb | `sessions.py`：open/select/overlay/needs_recovery 状态机 | MIT（本仓） | 选择登记、pending seq、覆盖语义、需求校验先于状态变更 | `_prove_application` DB read-back 证明路径（v2 拆分为 journal/receipt/Harness 端口证据） | G07/G09–G12 Profile 侧反例 | 完成（f5435be938；真实端口半边待 harness-api） |
| 4 | 页面基础控件 | direct-import（计划） | 本仓前端平台 | foundation 检查点待发布 | `@ordessa/ui`：Panel/Toolbar/ScrollArea/Button/Input/Select/Checkbox/Field | 待 foundation 发布时核 | 平台主题/公共出口 import | 不复制 CSS 控件、不引第二设计系统 | G18 | 未开始（等 foundation） |
| 5 | 配置区装载 | direct-import（计划） | 本仓前端平台 | foundation 检查点待发布 | `@ordessa/ui-components/react`：ComponentOutlet/useUiBinding | 待 foundation 发布时核 | 绑定/代次/错误隔离交平台 | 不造第二组件 registry | G16/G19 | 未开始（等 foundation） |
| 6 | 能力勾选表单 | reference-only | Hermes (NousResearch/hermes-agent) | 8c9fe964 | `apps/desktop/src/plugins/hermes-bots/profile-config.tsx`：CheckList/CapabilityEntry 布局思路 | **未核实——禁止复制** | 交互参考：名称/说明/勾选层次 | 不搬 SDK/bot store/dirty* 品牌字段；未复制任何代码 | 用平台 Field/Checkbox 薄组合（G13/G18） | 裁决维持：许可未过 |
| 7 | 创建表单 | reference-only | Hermes | 8c9fe964 | `create-profile-dialog.tsx` 聚焦/验证/提交交互 | **未核实——禁止复制** | 交互参考 | 不搬目录 slug/home 创建/SOUL 写入 | PM03/PM04 测试 | 裁决维持 |
| 8 | 管理导航（Harness→Profile） | original | — | — | 平台控件 + 本域薄组合 | — | — | 不移植 VS Code 编辑器/DI；不加平台业务树 API | G02/G18 | 未开始（等 foundation） |
| 9 | Chat 选择器 | original（薄组合） | — | — | 两级选择/键盘/所选名称；消费 chat-api 公开槽位 | — | — | 不 import model-provider 私有组件 | G20 | 未开始（等 chat-api） |
| 10 | 字段与设置贡献（facet v2 契约） | original（本仓 facet 语义 + 新契约） | 本仓 plugin-profile-impl（facets.py 语义） + Roo 校验思路 | b77f9f23cb / b867ec91 | FacetRegistry 唯一性；Roo `packages/types/src/mode.ts` 分组重复校验模式（思路） | MIT（本仓）/Apache-2.0（Roo，仅参考未复制） | 重复 facetId 拒绝、卸载幂等 | v1 session_apply 字符串协议（升级 v2 descriptor/compile） | G01/G16/G19 + 受控第三 facet proof | 完成（f5435be938；test_v2_extension.py） |
| 11 | 敏感值防线（sensitive） | direct-import + adapted | 本仓 plugin-profile-impl | b77f9f23cb | `sensitive.py` regex 兜底 + digest | MIT（本仓） | regex 作为附加防线 | 不再作为唯一安全边界（声明式 sensitivity 为主） | G15 | 完成（test_contracts.py::receipt_public_projection + 旧 secrets_allowed 门） |
| 12 | 模型/Skill/MCP glue | 不属本线 | Z3/Q1/Q4 | — | — | — | — | — | — | 归各域 |

诚实声明（2026-09-28 回填）：已落地行回填真实 SHA 与测试 ID；disposition 与
reuse-map.md 裁决一致，无“复用 Hermes”式整包宣称。
