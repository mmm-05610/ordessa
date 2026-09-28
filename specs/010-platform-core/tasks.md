# Tasks: 平台核心收敛

Input: spec.md、plan.md、research.md、data-model.md、contracts/platform-api.md。
Tests: 本规格要求测试先行、故障反例及真实构建，不是可选项。
Format: Txxx [P] [USn]；[P] 仅表示独立文件/无前置依赖。每线只勾自己的行，其余保留。

## Phase 1 — Setup

- [x] T001 [P] A 在 reports/A.md 冻结 packages/pacthold 的测试 ID/安装环境，列旧模块→runtime-compat→最终业务域映射，验证 main 起点。
- [x] T002 [P] B 在 reports/B.md 冻结 apps/server、harness、acp_orchestration 的 ID/失败原因与既有协议 golden 样例；盘点测试直接读 runtime 门面处。
- [x] T003 [P] C 在 reports/C.md 冻结 apps/desktop、Workbench、connectors 相关测试 ID/构建与消费路径，检查 apps/desktop/AGENTS.md。

## Phase 2 — Foundational

- [x] T004 A 在 packages/pacthold/src/pacthold/public.py 及对应中性模块建立 C1 完整 DTO/签名；packages/pacthold/tests/platform/test_public_contract.py 写正反契约测试；独立提交并在 reports/A.md 发布契约 exact SHA。依赖 T001。
- [x] T005 [P] B 在 packages/server-plugin-api/src/server_plugin_api/ 增 C2 贡献协议与明确错误；包内契约测试证明零依赖、非法声明拒绝。依赖 T002，不依赖 A 实现。
- [x] T006 [P] C 设计并实现 packages/workbench/api 与业务 API 归属、共享模块构建映射；先补真实构建 Token 灵敏度反例。依赖 T003。

## Phase 3 — US1 核心自然接入（A）

- [x] T007 [US1] packages/pacthold/tests/platform/ 先红后绿覆盖两个实例、依赖环、缺 provider、借用、自有、多依赖失败、启动丢回执、同键不同摘要、并发同键、清理双异常。覆盖 FR-001/002/003/004/007，依赖 T004。
- [x] T008 [US1] packages/pacthold/src/pacthold/work_core/ 改为实例注入 Store，通用 provider/lease/operation 调度，无全局连接切换。完成 T007 所有反例。
- [x] T009 [US1] packages/pacthold/ 与 plugins/runtime-compat/ 完成业务 SDK/组合/历史迁移外移、领域测试迁移和中性新 schema；无反向 shim，原 IDs/SQL 摘要保持。依赖 T008，覆盖 FR-011。
- [x] T010 [US1] packages/pacthold/tests/platform/ 覆盖终态不可恢复、Session resume 新执行、transport 与 execution 不互推、关闭时未解决租约持久化、重启仅对账不 spawn。覆盖 FR-004/014。
- [x] T011 [US1] packages/pacthold/tests/platform/ 独立 wheel 环境仅核心+受控 provider 运行；新接入核心零修改、移除业务发行版仍可导入全部核心模块。发布 A 完整 SHA 和导入迁移表。覆盖 SC-001/004，依赖 T009/T010。

## Phase 4 — US2 后端宿主（B）

- [x] T012 [US2] apps/server/tests/platform/ 先写贡献事务/依赖授权/清理异常/同 App 路由反例；保留既有 lifecycle 门禁。依赖 T005，覆盖 FR-005/007。
- [x] T013 [US2] apps/server/src/ordessa_server/plugin_host/ 实现 C2 staging/publish/rollback 与 draining/busy，关闭接纳窗口，禁止半批可见；完成 T012。
- [ ] T014 [US2] apps/server/bootstrap、wire、transport 删除业务门面、专用停机和投影/helpers；将所需实现移 plugins/server-compat、workspace、harness 的公开面，更新产品与对应测试。保留 golden 行为。覆盖 FR-006/010。
- [ ] T015 [US2] 按 plan.md 在 B merge A 契约固定 SHA，apps/server/src/ordessa_server/core_binding.py 实现唯一 Pacthold 接缝；禁止复制 C1 类型。先用忠实替身验证，报告尚未真实组合。
- [ ] T016 [US2] apps/server/tests/platform/ 裸 wheel 安装、无产品 typed refusal、受控 service 新接入零宿主修改；同 App auth/签名/owner/挂载时序/双异常全测。覆盖 SC-002/004。

## Phase 5 — US3 前端平台（C）

- [x] T017 [US3] plugins/workbench → packages/workbench，保留 extension ID、贡献点与行为，测试随包迁；根 workspace、build discovery、产品清单更新，锁由工具生成。依赖 T006，覆盖 FR-008。
- [x] T018 [US3] packages/desktop-platform/contracts 业务类型迁 connectors/agent/chat/connections 的领域 API，修改消费者和共享映射；无平台反向 re-export，未启用实现仍能导入 API。覆盖 FR-009。
- [x] T019 [US3] apps/desktop/renderer 与 electron/main.ts 的业务测试/smoke 迁插件或 products/desktop/tests；只留启动/窗口/IPC/宿主测试；保留源→目标 ID 表。覆盖 FR-010/012。
- [x] T020 [US3] packages/workbench/tests 与产品 tests 验证空 Host/空 Workbench、独立贡献者卸载、焦点/handle/标签页、API 单实例真实构建及复制 Token 反例。覆盖 SC-003/004。
- [x] T021 [US3] 根 JS 测试脚本真正聚合各 workspace；类型检查/build/临时 Electron smoke，失败收集不假绿，不启动真后端。覆盖 FR-012/014。

## Phase 6 — US4 后端产品适配（B）与各线交付

- [ ] T022 [US4] B merge A 完整固定 SHA，依 A 导入表更新 plugins/server-compat、harness、workspace 消费者及 products/server 依赖/迁移注册，不在核心恢复旧路径。依赖 T011/T015。
- [ ] T023 [US4] B 在 apps/server/tests/platform/ 加新旧临时库、历史 ID、重复启动、缺历史提供者反例；67 方法基线与 wire/REST/WS 受控回环（数量以 T002 现场为准）。覆盖 FR-011、SC-006。
- [ ] T024 [US4] A/B/C 各自报告定向/回归/逐 ID 差分、隔离安装与未测范围；执行 quickstart 本线全部门禁；记录新功能不修改核心证明。覆盖 FR-012/013、SC-005。

## Phase 7 — Final Integration（主控，本次不授权执行者做）

- [ ] T025 [US4] 主控审核固定 A/B/C SHA，在独立集成树统一集成，跑全部门禁，更新 docs/baseline.md/architecture.md/known-issues.md 的实际结果，再申请合 main。不得把其他线待办写成本线失败，也不得把整项 spec 写成完成。

## C6 Amendment — Connections 平台归属（仅 C，完成后才可申请 T025）

- [x] T026 [US3] C 对照 contracts/connections-platform.md 冻结旧 connection tests/关闭调用链，在 packages/desktop-platform/connections/tests/ 先写 CN-01–CN-06 反例及协议无关 API；依赖 T003，可在当前 Workbench 安全检查点后接入。覆盖 FR-015。
- [x] T027 [US3] C 在 packages/desktop-platform/connections 实现 registry/typed kind/handles/state/late-open/close-settlement，公开 @ordessa/connections/api 与 ordessa.connections 内置扩展；与 native-bridge 不重复所有权，完成 T026。覆盖 FR-009/014/015。
- [x] T028 [US3] C 将 plugins/connections/service 的 Agent workspace/status/facade 迁 plugins/agent/connections，保留 ordessa.agent-connections ID 和 run/approval/release 语义；connectors 通过平台管理通用句柄，产品启用及构建映射更新、旧目录删除；CN-07 原测试不削弱。依赖 T027，与 T018/T019 同一写者协调。
- [x] T029 [US3] C 补 CN-08 真实构建与零业务平台隔离验证；重跑 CN-01–08、原领域测试、平台/根聚合/typecheck/build/Electron，更新 reports/C.md 迁移映射与修订回执。依赖 T028，与 T020/T021 共享验证而非重复伪计数。

## C7 Amendment — 可替换 UI 通用机制（仅 C，2026-09-27 已授权）

原 C goal 已在 `865a6f57fa` 收尾，既有完成勾选及 reports/C.md 保留。本补充接续实施，权威输入见 contracts/ui-components-platform.md；不实施 12 个领域组件。

- [x] T030 [US3] C 冻结 C7 起点与现有 scope/共享 API/产品组合机制，在 reports/C7.md 记录接线和原聚合基线；将设计签名整理为可编译 API，无 Agent 类型。覆盖 UI-01/02/12。
- [x] T031 [US3] C 在 packages/desktop-platform/ui-components 实现 key/UiComponentsToken、props 不变型与异构注册工厂、只读 binding；补错误 props/复制 key/API 不激活实现的类型与构建反例。依赖 T030。
- [x] T032 [US3] C 实现实例 registry、冻结 selection、scope 登记/绑定、原子批次/快照/代次/清理；U01–U08 先红后绿。依赖 T031。
- [x] T033 [US3] C 实现 React Outlet、订阅、必需/可选缺席、逐位置错误边界、同步/异步动作 guard；U09–U13 先红后绿，保存旧动作必须在 DOM 移除前即失效。依赖 T032。
- [x] T034 [US3] C 通过产品通用组合点装配普通 UI service 插件和必需项诊断，保持空清单/空宿主；不切换现有业务 UI；更新共享构建入口、scope 接线和包测试聚合。依赖 T033。
- [x] T035 [US3] C 用独立受控 provider/consumer 完成 U14–U16：真实构建 API/React 单实例、实现未启用仍可导入 API、复制 key 变异、A/B 换提供者不改消费者、临时 Electron 与核心零改动扩展证明。依赖 T034。
- [x] T036 [US3] C 亲自复核 diff 与全部 U01–U16 证据，串行执行新增包定向门禁和当前根聚合，按 ID 解释任何退化，更新 reports/C7.md，检查点提交后报告 C7_IMPLEMENTATION_REVIEW_READY。依赖 T035；不勾 A/B 或 T025。

C7 顺序：T030→T031→T032→T033→T034→T035→T036。不同包可派子代理，单包单写者；平台主代理亲自掌握跨包契约/复验/git。已有 C 收尾不重做，最终 C 集成还须覆盖此补充。

## C8 Amendment — 通用 UI 基础件（仅 C，2026-09-27 用户裁决追加）

权威见 contracts/ui-foundations.md；设计快照在 amendments/ui-foundations/。C8 不替换 T030–T036/U01–U16，
只做增量；统一 `plugins/agent-ui`、12 项领域组件总包与统一默认提供者的实施要求已撤销（旧领域草图仅取材）。

- [x] UIB001 [US1] C 冻结接收追加时的 HEAD/脏树与 C7 进度，把主树设计逐字复制为 `amendments/ui-foundations/`，更新权威链（contracts/ui-foundations.md）、本 tasks 与范围说明，历史领域设计标为撤销统一实施、取材留档，不删 C7 通用反例。
- [x] UIB002 [US1] C 在 `packages/desktop-platform/ui` 建显式 exports 与公开最小类型（Card/Panel/Field 组合、原生 ref/事件透传），先落类型正反例，不含任何业务模式。依赖 UIB001。
- [x] UIB003 [US1] C 实现 containers/layout：Card、Panel、Stack、Inline、Toolbar、ScrollArea、Separator；独立 React 根、无服务也可用；先钉键盘顺序与嵌套滚动反例。依赖 UIB002。覆盖 V01/V03。
- [x] UIB004 [US1] C 实现 controls/field/feedback：Button、IconButton、Input、Textarea、Select、Checkbox、Field.*、Badge、Notice、EmptyState；验证 label/description/error 关联、双 Field 不重 ID、disabled/busy 不触发、默认 type=button、受控值、0/空文本、零保存/网络副作用。依赖 UIB002。覆盖 V02。
- [x] UIB005 [US3] C 落显式 scoped CSS（`.ods-ui-*`，无全局 reset）与主题/构建接线；在深浅主题、360/768px、裸根与真实 Workbench `.wb` 宽样式共存环境实测；锁由 npm 更新。依赖 UIB003/UIB004。覆盖 V03/V04。
- [x] UIB006 [US2] C 用现有 C7 provider/consumer 受控夹具新增一种领域 key（独立测试领域载体，不进平台 carrier），消费者在 Card 内放真实 ComponentOutlet，provider 不依赖 Card；并证明普通内部组件不注册也可用。依赖 UIB005 与 C7 T033。覆盖 V05/V06。
- [x] UIB007 [US1] C 串行执行 C7 U01–U16、C8 V01–V08、根聚合/typecheck/build/既有临时 Electron 门禁；用 `tooling/id-diff.mjs` 按原 ID 比对回归，几何/焦点用实际浏览器；未运行项不得记为通过。依赖 UIB006。
- [x] UIB008 [US3] C 主代理逐项复核 diff/依赖/导出/样式，记录 source→reuse 与任务→测试→日志，提交增量检查点并更新 reports/C7.md，报告 `C7_C8_IMPLEMENTATION_REVIEW_READY`；不勾 A/B、T024 或 T025，不合并、不 push。依赖 UIB007。

C8 顺序：UIB001→UIB002→(UIB003∥UIB004)→UIB005→UIB006→UIB007→UIB008；`ui` 与 `ui-components` 各一写者，
共享 lock/carrier/产品接线由主代理串行处理。C7 的 T034–T036 继续按原顺序推进，不因 C8 推翻已合格实现。

## Dependencies & Execution Order

A: T001→T004→T007/008→T009/010→T011→T024。
B: T002→T005→T012/013/014/016 可先行；T015 等 T004，T022 等 T011，随后 T023/T024。
C: T003→T006→T017/018/019→T020/021→T024。
C6 补充：T026→T027→T028→T029；应与 T018/T019 合并安排，T024 的 C 交付与 T025 必须等 T029。不推翻已完成 Workbench 改动，不扩大后端或新版 Chat 范围。
C7 补充：T030→T031→T032→T033→T034→T035→T036（顺序见上），与 C6 已完成实现共享构建/聚合门禁，不重做。
C8 补充：UIB001→UIB002→(UIB003∥UIB004)→UIB005→UIB006→UIB007→UIB008；C8 只做增量，撤销统一 agent-ui 批次，不扩大 host/loader 行为，交付状态为 C7_C8_IMPLEMENTATION_REVIEW_READY。
T025 等三线交付和主控批准。不同包可分子代理，单包一写者；主会话持有任务表/报告/git，亲自复跑不能只引用子代理数字。

## Checkpoints / Blocking

阶段提交后继续；编译、夹具、安装和命令问题在本线修好。依赖未到就做其他任务。只有跨契约/数据/权限裁决或全部本线待办都被依赖阻塞才停，并一次列齐缺口。不得靠 mock、skip、放宽断言或 core 业务 fallback 宣称完成。
