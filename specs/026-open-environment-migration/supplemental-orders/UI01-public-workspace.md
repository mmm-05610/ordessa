---
id: "UI01"
slug: public-workspace
batch: ui-foundations-20261004
baseline: "implementation HEAD captured at receipt; source file SHA256 required"
depends_on: [{"order":"current-closeout","condition":"tree /home/maoqh/projects/ordessa/worktree/026-open-environment-migration: current active overlapping slice checkpointed and its sha recorded at receipt; no concurrent writer on affected files; F5 available and inherited failures recorded"}]
write_paths: ["packages/frontend/**", "apps/desktop/**", "products/desktop/**", "tests/**", "specs/026-open-environment-migration/supplemental-orders/**", "specs/026-open-environment-migration/evidence/ui-foundations/**", "specs/026-open-environment-migration/status.md"]
forbidden: ["plugins/** business redesign", "packages/backend/**", "credentials/**", "user-data/**", "/opt/**", "other-worktrees/**"]
ruling: "R-1401"
terminal: ["UI_FOUNDATIONS_DONE", "UI_FOUNDATIONS_PARTIAL", "UI_FOUNDATIONS_BLOCKED"]
waive: []
parallelism: "none"
parallelism_reason: "freeze shared contracts/styles/workbench first; lead may record disjoint leaf-component units after interfaces freeze, within existing authorized concurrency"
serialize_with: ["008", "009", "010", "011", "012", "current-closeout"]
---

# UI01 — 公共工作区与交互基础设施

裁决 R-1401（本增量局部编号，映射设计 ID UI-FOUNDATIONS-20261004）：用户于2026-10-04批准公共包改进方案更新及对执行中Codex的增量提示；不扩大运行/安装/真实模型授权。复用现有唯一队列/status，基线由接收回执记录真实HEAD，不伪造设计提交。

## Objective
执行 ../contracts/ui-foundations.md，不重复实现F5，不全面改造领域插件。主树方案只读，实施树内容合并与证据由牵头者拥有。

## Current state
2026-10-04只读盘点实施树：ui/src/index.ts已有基础容器、布局、控件、字段与反馈；ui-components已有注册/选择/绑定；Workbench已有navigation/layout/overlays。存在入口不证明本增量场景已通过。当前执行树有未提交源码与证据，禁止覆盖；接收时重测HEAD和文件写者。

## Scope
完善已有逻辑包：公共契约、运行生命周期、Workbench布局/弹层/设置容器、ui控件、ui-components呈现替换及默认产品装配。必要原生接线只走Desktop/native-bridge公开边界。
受控两个中性fixture消费者放tests/products测试目录。不新增业务插件、不做会话归档/账号/市场/浏览器实现、不改原生Harness行为或后端语义；不自动启动用户服务。

## Requirements
### Requirement: 公共骨架不是业务核心
#### Scenario: 独立消费者
**WHEN** 无Chat/Profile启用时两个中性插件贡献工作区与设置，**THEN** UI-A01/07通过，且不依赖领域store。
### Requirement: 单一交互与生命周期
#### Scenario: 撤销及迟到事件
**WHEN** 插件退出或菜单目标失效，**THEN** UI-A02/03/10拒绝失效操作并清理视图引用，不残留遮罩。
### Requirement: 可验证呈现
#### Scenario: 窄窗与发行环境
**WHEN** 执行规定尺寸及干净产物操作，**THEN** UI-A05/12记录实测；缺GUI或产物时保PARTIAL而非DONE。

## Stages
- [ ] 1. UI-T01 接收回执、盘点现有接口/实现/写者、冻结增量公开接口与包归属；提交。
- [ ] 2. UI-T02 导航/工作区/页面贡献；UI-T03 沿用布局补标签分屏/窄窗/安全恢复；分别定向验证提交。
- [ ] 3. UI-T04 单一弹层/焦点/菜单操作与快捷键；UI-T05 ui控件/tokens/可替换呈现；分别正反例验证提交。
- [ ] 4. UI-T06 设置容器/搜索与F5编辑接口；UI-T07 两个中性消费者、scope清理及默认产品装配；提交。
- [ ] 5. UI-T08 UI-A01–12逐项实测，受影响回归及干净产物验证；分账、检查点与未验清单。

## Gates
| Gate | Assertion | Counter-example | Absent / unknown ⇒ |
| --- | --- | --- | --- |
| G1 边界 | 无领域writer/重复交互或弹层服务 | 注入WorkBench模型store/插件私有宿主导入，必须发现 | 缺边界检查失败，不报完成 |
| G2 操作生命周期 | 目标失效拒绝，退出清注册 | 晚回调/旧句柄/权限撤销反例必须通过 | 无反例证据失败 |
| G3 呈现 | 四角菜单、键盘、三尺寸、设置和IME实测 | 裁切/遮罩/焦点丢失/红字闪烁不能通过 | GUI缺席记pending，阻DONE |
| G4 发行 | 干净产物中运行中性消费者 | 删除源码依赖/隐式样式后仍工作 | 未运行产物阻DONE |
| G5 回归 | 受影响测试计数/退出码与继承红逐ID比较 | 不得删断言/skip/改fixture伪绿 | 无基线或未复跑阻DONE |

## Validation
```bash
python3 /home/maoqh/.agents/skills/incremental-work-order/scripts/validate_order.py specs/026-open-environment-migration/supplemental-orders --strict
node specs/026-open-environment-migration/checks/validate-package.mjs
git diff --check
```

沿用原项目构建/类型检查/边界与受影响套件，先定位真实命令再执行；每条命令保存退出码和实际计数。工单结构先自查，原026结构检查仍须通过；新增UI case单列，不能把旧检查通过当新增覆盖。静态检查验证至少一个故意违规样本。

## DoD
源码、正反例、受控集成、GUI、产物及回归证据与清理、status分账齐全才DONE。缺授权、GUI或产物证据记PARTIAL及明确case，不缩小标准。证据保存evidence/ui-foundations；不覆盖旧evidence。

## Acceptance
UI-A01–12逐项通过且证据齐：DONE。部分完成：PARTIAL；只有没有任何安全可推进项且需用户裁决时BLOCKED。报告给出用户可操作入口/预期、已知缺陷、未验项及下一步，不说笼统“最后验收”。

## Batch report
执行者完成时填写：HEAD/接收摘要、UI-T01–08状态、UI-A01–12逐项证据、命令计数/退出码、继承失败/新增失败、GUI/产物缺口、清理与检查点。当前为未实施，不能预填绿。
