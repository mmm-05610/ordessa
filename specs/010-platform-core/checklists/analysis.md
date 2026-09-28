# Cross-artifact Analysis

2026-09-27，主代理依官方 analyze 的覆盖/歧义/一致性维度人工复核；不是独立代理审阅，不是产品测试结果。

## Coverage

| Requirements | Tasks |
| --- | --- |
| FR-001 | T007/T008 |
| FR-002 | T004/T007/T008 |
| FR-003 | T007/T008 |
| FR-004 | T007/T010 |
| FR-005 | T005/T012/T013/T015 |
| FR-006 | T014/T016 |
| FR-007 | T007/T012/T013/T015 |
| FR-008 | T017/T020 |
| FR-009 | T006/T018/T020 |
| FR-010 | T009/T014/T019 |
| FR-011 | T009/T022/T023 |
| FR-012 | T001/T002/T003/T019/T021/T024 |
| FR-013 | T024/T025（权限为全任务约束） |
| FR-014 | T010/T020/T021 |
| FR-015 | T026/T027/T028/T029 |
| SC-001/004 | T011、T007/T010/T012/T020 |
| SC-002 | T016 |
| SC-003 | T020 |
| SC-005 | T001/T002/T003/T024 |
| SC-006 | T023/T024 |

## Findings and resolution

- 已修：旧 SPECKIT_FEATURE 变量与当前官方脚本不符，统一 SPECIFY_FEATURE_DIRECTORY 并预检 exit 0。
- 已定界：A/B 不共写旧业务插件；A 提供 runtime-compat、B 迁消费者。
- 已定界：不把三个旧业务实现树、新 Chat 链强行混入平台批次。
- 阶段依赖：C1 具体 DTO 代码签名由 A 的 T004 检查点交付，B 的 T015 必须等待，不能把整批都标立即可并行。
- 阶段依赖：历史迁移兼容需 T009/T023 临时数据证据；不授权真实用户数据库迁移。
- 风险：开发版 Spec Kit pinned commit 非稳定版本承诺；所有生成文件已本地留存，执行不依赖继续下载最新 CLI。

结论：三线可从本线 Setup 与无依赖任务启动；共享契约门未完成的任务不可提前执行。14/14 FR 与 6/6 SC 有任务覆盖；25 个任务含 setup 和最终集成，全部有阶段/所有者。未发现阻止 Setup 的未决产品选择；这不等价于实现无风险或最后集成已通过。

## C6 amendment review

以上计数为初版记录。C6 后为 15/15 FR、6/6 SC、29 项任务。修订只涉及 C，T025/T024-C 的完成条件增加 T029；A/B 不必同步修改。
已消除旧 C4 “Connections 全部归插件”的冲突。原 Agent workspace/UI 明确迁 plugins/agent/connections，平台不接收 AgentClient/审批/后端释放账。补丁不修改执行者报告，需 C 接收后更新其旧 owner map。
