# 基线核查与第一批工单建议 · 2026-10-04

## 建议与确认门

推荐固定提交 **adce734db21945181bf93da9720158d05e957654** 为本实施树依赖基线；尚未批准，未切换。它是026工作分支上的固定安全检查点，**不是主树已整合或全量验收完成的提交**。消费028 Agent装配V2.1设计（六份主体材料摘要见evidence/baseline-inspection.json）；按用户本轮明确架构要求补齐设计已定缺口，旧028冲突工单不得执行。公开wire/schema等设计未决项先报告，不自创新协议。

| 树/快照 | SHA | 本次事实 |
| --- | --- | --- |
| 本树 | 6a3f24456130b5caad82682d692d2d198721f0a8 | 当前HEAD；只有未跟踪设计/准备资产 |
| 主树 | b4bf7cd90951d0fa9bcf3a3de2e66b7db6a62aa0 | .gitignore修改及022–028未跟踪设计；没有026实现 |
| 026受控发行源码 | 4ad3d670358ce1cca226511526653f56a61804f3 | 引用完整DEB受控验收，非本轮重跑 |
| 推荐起点 | adce734db21945181bf93da9720158d05e957654 | 4ad后生产raw facade拒绝守卫；尚无该SHA完整发行重证 |
| 026观察HEAD | b12296ad4444c1cf0c1cdb891be2ca55cc850536 | 已提交UI CAS/commands增量，另有在途workspace/UI文件 |

主会话实测6a→adce祖先检查退出0；adce→b122在packages/backend、apps/server、plugins/agent、plugins/harness、products/server差异为空（退出0），全部差异42文件为前端UI及证据。不直接跟随026移动branch，不摘取dirty代码。baseline/cp-monorepo-0解引用commit为6a3f244；13edd5f2是annotated tag对象，不是另一实施commit。

## 准确切换方式（待用户确认）

当前本分支没有自己的产品提交，允许快速前进，无需cherry-pick或重放设计提交。建议批准后：

1. 在本树准备记录内归档全部现有specs与docs/implementation材料，记录每文件SHA256和归档SHA256；保留6a准备点与本次回执。
2. 重核HEAD、暂存区、工作区、目标固定commit可用性；核对目标tracked路径与本树untracked材料无冲突。目前目标adce不含specs/029-agent-tools-product或docs/implementation/agent-tools（ls-tree退出0、零路径）。若出现冲突停止，不覆盖/自动清理材料。
3. 仅在本树执行 `git merge --ff-only adce734db21945181bf93da9720158d05e957654`。这是把本产品分支推进到固定提交，不生成合并提交，不修改main，不访问移动branch。
4. 重核HEAD等于批准SHA、设计摘要不变，重读新AGENTS及实际包组指令，安装本树隔离依赖并建立本次实测基线。拒绝失败后reset/强制覆盖。

本轮未执行上述切换或任何Git写操作。确认必要性来自用户明确要求“向用户确认准确的实施基线及切换方式后，再开始依赖该基线的实现”。

## 验收引用与风险

026固定status原账109/129，20项开放。4ad完整非editable DEB SHA2566718c82a25a7b32d7f1cfd5d79b0d98032b74531cd9fec4344d4d8e80ccb2306；报告受控11场景、前端2kill窗口、公开Chat有/无Profile两轮/冷查询、跨侧5双进程SIGKILL通过。此产物不含adce守卫，真实品牌/模型、完整替代Desktop UI未验。adce守卫记录AgentSessions47P/0skip，但原T010-09 aliases/runs/interactions/firstSend持久provenance缺口仍在。

引用位置（026树、固定adce版本）：specs/026-open-environment-migration/status.md、evidence/closeout-20261004/production-raw-facade-checkpoint.md、artifact-build-4ad3-receipt.json。旧overnight报告审查0887b95，不能当当前源码验收结果。所有上述数字是文档引用，本次产品测试0。

## 公开接缝与缺口

| 接缝 | 源码/设计证据 | 本轮处置 |
| --- | --- | --- |
| 唯一Environment/StorePort | packages/backend/pacthold/src/pacthold/public.py、environment.py；persistence-sqlite/store.py | 复用单次claim/结果/unknown机制；多step、核心持久节点身份、发布与Usage原子换代需实测补齐，不能大内存handler |
| Agent核心 | 028 contracts首句为拟议契约；固定树无pacthold.agents.public | 按V2.1实现小模块，不复制第二核心，不导入插件 |
| Profile | plugins/profile旧清单/独立协调链 | 双revision迁入唯一权威；关闭冲突旧写入口，用户DB不迁移 |
| Harness | 公开RuntimeAdapter/ConfigurationService已有 | Harness侧实现InvocationContext、unit/session目标分型、作用前correlation、唯一owner和实际运输fence |
| 目录绑定 | plugins/workspace路径/可访问性投影 | 补公开DirectoryBinding实际宿主授权重核；不把normalizedPath当许可 |
| 输入消费 | 026已有DurableSubmissionClient/IndexedDB、生产持久gateway和Agent域提交owner；受控两轮/冷查询引用 | 继续盘点并复用其公开持久输入接缝；028 DraftCapture/session reservation/InputAttempt关联不可从旧gate或测试名推断齐备，不在CLI造新账 |
| CLI wire | 028/029仅逻辑契约，没有完整具体消费wire冻结 | 001固定版本、认证/发现/局部configure、input capture/证据/query/watch/result合同；未决项报告 |

## 首批顺序与并行

work-orders/001–005均prepared-blocked-on-baseline，结构验证不等于可执行。001固定消费合同→002持久核心接缝→003双revision清单与叶子→004目录/节点管理闭环→005独立CLI消费。客户端源码、Skill、产品测试与分发统一products/agent-tools；核心基础测试归其原模块。

基线/合同由主会话串行；三子代理本轮分别只读基线、公开接缝和工单反例。合同冻结后才能按工单声明的独立文件切片并行；子代理不写合同/status、不操作Git，主会话复跑验收。后续006原生客户端/持久任务→007三Skill/打包→008隔离安装验收，MCP另阶段。

每阶段分账单测、契约、真实SQLite并发/崩溃、隔离服务、原生进程、模型；保存失败原记录、exit、数量、资源/费用/清理与剩余范围。缺资源保持PARTIAL/untested，不算绿。
