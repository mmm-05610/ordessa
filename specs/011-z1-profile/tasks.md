# Z1 任务与原包追踪

本线副本，允许勾选并追加查漏任务。共同 plan 的 owner 分配优先；原表范围外步骤登记依赖/C0 集成，不由本线偷改。原包更晚变更须有明确裁定，不自行缩需求。

- [x] R0：读完整输入，冻结实际 SHA/包/红 ID/环境，盘点复用。（inventory.md / evidence/platform-bindings.md；旧基线实测 70 passed @ b77f9f23cb）
- [x] R1：独立工作与接口请求完成；消费必需 checkpoint 并留精确 SHA。
  - [x] profile-api 检查点已发布：codex/011-profile-api-ready @ 4943628f47（impl f5435be938）
  - [x] api-requests.md 登记 foundation/harness-api/chat-api 缺口
  - [x] 消费 foundation @ 8844c475bc、chat-api @ 54ad26c15d、chat-api-r2 @ 31fb2db46d（api-requests.md 消费记录）
  - [x] harness-api：已发布并消费（d3f026904e；impl 61966e3118 祖先已核）。等待期累计 ~155 分钟 60+ 次有上限轮询，期间完成 r3 消费与载体适配器。缺口登记 report.md
- [x] R2：本线全部原包任务有实现/验收/依赖归属，生产假接口为零。
  - [x] PV-01–PV-06、PV-08–PV-10 组件/服务级完成（见 report.md 对照）
  - [x] PV-07 Profile 侧完成；真实 Harness 端口半边归属 C0（typed-blocked 边界有反例）
  - [x] 载体适配器就绪并接真实服务：HarnessApiConfigPort→C0 ConfigurationApplicationService，G09–G12 全链在真实服务类上复跑（test_harness_real_service.py 5 项）
  - [ ] PV-11 真实浏览器几何验收 + 真实品牌矩阵（依赖产品装配与授权；发布切片自身声明生产 ACP admission 未接线、无真实模型调用——未测清单见 report.md）
- [x] R3：检查点/接线清单/许可迁移账/报告齐备，定向及相关全链门通过。
  - [x] 140 py + 28 ts 测试、boundary 0 violations、12/12 反例（harness-api 消费后复跑）
  - [x] reuse-ledger.md / integration-request.md / report.md 齐备
- [x] R4：Spec Kit analyze 查漏完成（report.md §查漏），未完成项如实；本线 clean ready commit 发布。

## 原包：profile-v2

来源：docs/design/profile-v2/tasks.md，2026-09-28 派发快照。以下保留原条目便于追踪；过程授权与 owner 由共同 plan 更新。

# Tasks：Profile v2（审核后再派发）

- [ ] PV-01 审核 spec 新决策、绑定正式平台与旧 Profile 起点，读写边界/ID/测试映射完整。
- [ ] PV-02 按 reuse-map 逐模块登记 direct-import/adapted-copy/reference-only/original；Hermes 许可未核实用指定平台组合回退，不搬 SDK；保留来源/许可/修改说明。
- [ ] PV-03 冻结 facet descriptor/item schema/reset/校验、UI editor/settings context、SessionRef、intent/receipt 的实际公共类型；拒绝未知字段/重复 key/越权 context 正反例。依 quickstart 形成实际 import/signature 绑定表。
- [ ] PV-04 增量迁移 stable ID/旧 revision/命名空间/journal/policy；旧 DB settled 不能升级为 Harness confirmed；副本迁移/重复运行/碰撞门禁。
- [ ] PV-05 Profile 存储/CAS/归档恢复/逐item解析/policy 实现与 wire registry 注册；裸宿主不改，零facet管理可用。
- [ ] PV-06 提供者 schema/编译/reset/缺席/migration/generation 门禁，集成两个配置面，无任何业务名 if 分支。
- [ ] PV-07 Harness 接缝：完整差异计划/互斥fence/应用证明/未知恢复；跨会话隔离、外部成功DB失败、部分应用失败、无reset支持全部反例。
- [ ] PV-08 设置页的机制控制、影响提示、服务域、disabled/未加载区分；提供者独立设置区注册/装载/CAS/卸载保留，第三提供者接入无需改页面；首版不出现 Agent 自动切换假开关。
- [ ] PV-09 两级导航/分类编辑/搜索/复制/归档/显式保存/并发冲突/未保存离开/离线状态；提供者卸载数据保留。
- [ ] PV-10 Chat 可选 Harness→Profile 两级选择器，所选名称立即更新、不展示状态标记；已有会话不跨Harness，选择不打断输出、仅下次提交应用、连续选择最后生效；实际失败保留草稿。UI卸载不清配置/不结束运行，无Profile时Chat原能力正常。
- [ ] PV-11 全部 G01–G20 与 test-scenarios 逐项证据，浏览器/受控真实服务调用链/许可与边界审阅；只读记录真实品牌未测项。
- [ ] PV-12 最终 diff 与每阶段提交、report、原失败 ID 对照；待审，不自动 merge/push。

任务勾选必须对应实测 evidence；本轮文档齐全不意味着任何实现项已完成。错误修复不删断言、不跳门；来源兼容性/权限能力不足时诚实拒绝，不降级偷偷写全局配置。
