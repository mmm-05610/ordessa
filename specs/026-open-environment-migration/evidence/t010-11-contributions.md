# T010-11 公开贡献/无私有 serializer → 钉面映射

| 子项 | 钉面 | 状态 |
| --- | --- | --- |
| 资源选择控件与 Profile facet 走公开贡献及 Agent 操作 | facet 策略经公开 policy store（`profile/frontend/tests/policy-store.test.ts`）；选择控件经 ChatContributions/SettingsContribution 面；Agent 操作走 agent.owners@1 五 owner 面（T010-10） | 既有 |
| 无私有 binding/serializer | 静态核验：全部 serializer 提及均为 §6c F1.2 公开投影缝（`serializeRegistration` 经 picker props 投影，缺位即 null 直发）；新钉 `click-order-composition.test.tsx`（T010-11）：无 Profile glue 时 seam 为 null 且 chooseForSession 直发、路径无 Profile 私有环节 | 新钉 |
| Profile 字段覆盖 | `policy-store.test.ts`（allowUserOverrideWrites 全局/逐项）+ settings-view facet 行为 | 既有 |
| 同预设重选 | T010-02/04 钉（同值重选=新操作新 opId） | 既有 |
| 无 Profile 模型切换 | 新钉（同上）：缺 seam 直发；turn-application M06/unbound 钉（无绑定即模型侧提交） | 新钉+既有 |
| 无 Chat 资源管理 | 资源面不依赖 Chat 贡献（ui-components/workbench 独立资源测试）；Chat 缺位时 Profile glue 即缺席（contracts.md §4 optional entry） | 既有 |

复核：`npx vitest run --root plugins/model-provider/chat-contribution` → 120F；
`npx vitest run --root plugins/profile/frontend` → 21F。
