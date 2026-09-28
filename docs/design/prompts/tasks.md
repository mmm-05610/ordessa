# Tasks and traceability

所有任务尚未执行。按 Spec Kit 的依赖任务划分，不是派工单；未授权创建工作树/会话。[P] 仅表示接口冻结后可独立并行。

## Phase 0 — 依赖与基线

- [ ] T00 冻结平台/Profile/Harness 集成 SHA、公开符号、数据根/授权/文件对话框接缝，记录 implementation-baseline.md；禁止引用工作树未提交实现。
- [ ] T01 固定三品牌 native/adapter 版本，核验 instruction 路线；persona/system-replacement 逐格裁定，保留项目加载机制和 reset 证据计划。
- [ ] T02 保存当前各影响套件的全文/JUnit、失败 ID/原因；核查已有 Prompts ID/代码/数据，没有就明确新增，无臆造迁移。

## Phase 1 — 内容与公共 API（US1/US5）

- [ ] T03 实现 DTO/schema/errors、纯 TS/Python 公共出口，独立导入与边界反例（G01）。
- [ ] T04 SQLite records/revisions、CAS/幂等、clone/archive/restore，单事务 latest/正文；失败注入与并发测试（G02/G03）。
- [ ] T05 UTF-8 导入/导出、容量限制、授权/scope、正文隐私及快照一致性（G04–G07）。
- [ ] T06 注册 Server 方法与公共服务，不导入 host internals；无 Profile/Harness 的裸业务管理测试（G08）。

## Phase 2 — 贡献与适配（US2/US4）

- [ ] T07 [P] 三品牌 Harness adapter 的 assess/compile/verify、claims、组合/reset、隐式 include 拒绝和版本矩阵（G09–G12）；依赖 T01/T03/T05。
- [ ] T08 [P] Profile facet/引用校验/专用内容授权、scope dispose 和覆盖联动（G13/G14）；依赖 T03/T05/T06。
- [ ] T09 [P] Settings 管理页、编辑/预览/历史/导入导出/冲突保稿，按复用单用平台基础件（G15/G16）；依赖 T03/T06。
- [ ] T10 Profile editor，多选排序、单选、高级替换、明确两步保存与异步代次保护（G17）；依赖 T08/T09。

## Phase 3 — 生产应用与交付（US3）

- [ ] T11 接既有 Profile→Harness→ACP 提交路径；选择不应用、下次输入冻结、confirmed 才发消息，失败不清覆盖（G18）。
- [ ] T12 三品牌 instruction 启用/更新/排序/移除、双会话隔离、重启恢复与实际装载受控证据（G19）；不能只有 fake service。
- [ ] T13 产品 manifest/锁与真实构建，前端几何/键盘/空/错误/卸载验证（G20）。
- [ ] T14 wheel 隔离安装、干净检出与完整受影响套件逐 ID/原因差分；权限/泄漏扫描（G21/G22）。
- [ ] T15 汇总实施报告、来源许可、能力矩阵、未测/阻塞、数据回退与原始证据位置；所有必需门通过后报 REVIEW_READY，未获授权不合并/push。

## 需求映射

| 需求 | 任务 | 验收 |
| --- | --- | --- |
| FR01/FR10/FR11/FR13 | T01/T07 | G09–G12 |
| FR02/FR04/FR06 | T04/T05 | G02/G03/G07 |
| FR03/FR05 | T05/T08/T10 | G06/G13/G17 |
| FR07/FR08 | T03/T06/T08/T09 | G01/G08/G14/G15 |
| FR09/FR14/FR15 | T05/T07/T09 | G04/G05/G10/G16 |
| FR12/FR16 | T11/T12 | G18/G19 |
| FR17 | T13/T14/T15 | G20–G22 |

小实现错误自行修复并复跑；改变原生语义、扩大 host 范围、修改用户数据或真实模型调用属于新的授权边界，不能为了无人值守绕过。
