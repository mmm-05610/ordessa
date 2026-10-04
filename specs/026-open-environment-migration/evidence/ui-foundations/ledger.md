# UI01 增量任务及场景账

接收状态：IN_PROGRESS（UI-T01公共接口冻结中）；用户已批准兼容版本化CAS增量，原历史验收仍不算本增量覆盖。

## Tasks

- [ ] UI-T01 接收、盘点、冻结接口归属 — IN_PROGRESS；版本化F5 CAS已批准/冻结并补机制，Workbench/Commands/页面实例完整接口尚未冻结；不勾完成。
- [ ] UI-T02 导航/工作区/页面贡献 — QUEUED；未冻结接口，未实施。
- [ ] UI-T03 标签分屏/窄窗/安全恢复 — QUEUED；未冻结接口，未实施。
- [ ] UI-T04 单一弹层/焦点/菜单/快捷键 — QUEUED；未冻结接口，未实施。
- [ ] UI-T05 基础控件/tokens/呈现替换 — QUEUED；未冻结接口，未实施。
- [ ] UI-T06 设置容器/搜索/F5编辑 — QUEUED；未冻结接口，未实施。
- [ ] UI-T07 两个中性消费者/生命周期/装配 — QUEUED；未冻结接口，未实施。
- [ ] UI-T08 逐场景实测/回归/干净发行 — QUEUED；未冻结接口，未实施。

## Acceptance

| Case | Status | Evidence |
| --- | --- | --- |
| UI-A01 | NOT_RUN | 无新增证据；不引用原case替代 |
| UI-A02 | NOT_RUN | 无新增证据；不引用原case替代 |
| UI-A03 | NOT_RUN | 无新增证据；不引用原case替代 |
| UI-A04 | NOT_RUN | 无新增证据；不引用原case替代 |
| UI-A05 | NOT_RUN | 无新增证据；不引用原case替代 |
| UI-A06 | NOT_RUN | 无新增证据；不引用原case替代 |
| UI-A07 | NOT_RUN | 无新增证据；不引用原case替代 |
| UI-A08 | NOT_RUN | 无新增证据；不引用原case替代 |
| UI-A09 | NOT_RUN | 无新增证据；不引用原case替代 |
| UI-A10 | NOT_RUN | 无新增证据；不引用原case替代 |
| UI-A11 | NOT_RUN | 无新增证据；不引用原case替代 |
| UI-A12 | NOT_RUN | 无新增证据；不引用原case替代 |

## 兼容CAS接口子切片（不抵UI产品场景）

批准见cas-delta-approval.md；原UiStoreContract原样保留，VersionedUiStoreContract增量带版本读取和null仅缺席创建，同一native锁/版本分配器。公共红首5F1P、真实双进程首次竞争1F1P；root额外漏版本/坏版本反例2F6P，均修实现而不改断言。当前原公共套件113P、native3P（含独立OS竞争）、实际两个公共factory+native集成1P、typecheck0。首次typecheck JS capability被推断boolean，与严格true类型不合；源JSDoc明确literal后通过。UI-A01–12仍NOT_RUN，尚无Workbench布局接线/GUI或包含新能力的发行证据。
