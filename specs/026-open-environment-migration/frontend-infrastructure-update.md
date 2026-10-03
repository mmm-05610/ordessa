# R7前端基础设施 — 实施中更新说明
2026-10-03，用户批准M14。唯一设计来源：
/home/maoqh/projects/ordessa/specs/026-open-environment-migration/
实施位置：
/home/maoqh/projects/ordessa/worktree/026-open-environment-migration/

## 变化及不变项
补全平台开发工具而非再做业务核心；完整F5在contracts/frontend-infrastructure.md。
12工单不增加；任务114→129，验收95→111。旧ID/结果/原来源快照不改。
008新增T008-11–20，010新增T010-12–14，012新增T012-12–13；A96–A111逐项必需。
保持单Pacthold/Lumino、领域唯一owner、品牌差异归Harness、Profile可选、按字段覆盖、unknown不重发和所有旧安全约束。
不自动新增npm包、不强制使用Zustand/TanStack；先沿用现有工具，候选采用须固定版本/许可及实际验证。

## 安全导入
1. 当前007或其他在写切片先到安全边界，不reset、不打断子代理同文件写入。
2. 核当前HEAD和status，记录修订接收时工单/阶段。主树只读；不要cherry-pick不存在的设计提交。
3. 新文件frontend-infrastructure.md和本文件可导入；已有文件做内容级合并，不整目录覆盖。
4. contracts/frontend、architecture、spec(R18)、execution-detail、plan、decisions(M14)保本树既有冻结/裁决，新增F5而不抹历史。
5. task-registry保所有旧ID/描述/完成证据，将新增15任务按ID合并到所属单；tasks/orders只追加新任务，不取消旧勾选。cases/acceptance保旧95，新增16。
6. README/handoff更新指针及当前计数；status只追加接收回执，不复制主树旧“未开始”正文。已有evidence全部保留，尤其001/002基线与合同摘要。
7. checks/validate-package合并R7数量/合同/任务/验收检查及7个新破坏样本，保本树已有额外守卫。禁止以主树脚本整文件覆盖实施者新增检查。
8. 输出evidence/frontend-infrastructure-r7-receipt.json：designId、源文件摘要、receivedAt、implementationHEAD、currentOrder/stage、mergedFiles、preservedEvidence、newTaskIds/newCaseIds、contractDelta、gate结果及未验项。不伪造设计SHA。
9. 运行合并后的结构检查；下一检查点纳入R7。008先冻结F5接口/错误/Token/缺席清单、编译两个中性消费者，再写机制；旧002不整体重跑，受影响接缝定向复验。
10. 新增008 S/I未过不能报008 codeReady；UI未跑保U待验。此前报告若已按旧范围ready，保历史报告另发R7增量报告，不改旧证据为“已覆盖”。

## 文件差异范围
README.md、architecture.md、spec.md、execution-detail.md、plan.md、decisions.md、status.md、
contracts/frontend.md、contracts/frontend-infrastructure.md、
orders/008.md、orders/010.md、orders/012.md、
tasks.md、task-registry.json、case-registry.json、acceptance.md、
zcode-handoff.md、checks/validate-package.mjs、本文件。
本次只编辑主树方案，不写实施树，不提交/合并/push，不操作服务/数据/系统资产，不新增真实模型授权。

## 给正在执行的Zcode
~~~text
继续当前026迁移，在安全切片边界纳入用户已批准的R7/M14，不reset或重做已完成001–007。
从 /home/maoqh/projects/ordessa/specs/026-open-environment-migration/ 读取 frontend-infrastructure-update.md 和 contracts/frontend-infrastructure.md，按差异合并到本实施树；保留status、evidence、旧合同和完成标记，禁止整目录覆盖。
新增T008-11–20、T010-12–14、T012-12–13及A96–A111；完整12单/129任务/111验收。008先增量冻结F5，再实现工具，010迁消费者，012验产物/UI。
不增加业务核心或全局Store；领域owner持值，平台只给状态/查询/编辑/任务/交互工具，品牌适配仍归Harness。
记录R7接收回执和源摘要，跑结构及新增正反例；S/I齐才codeReady，U未验不报DONE。原授权边界与并行纪律不变，接收后继续推进。
~~~
