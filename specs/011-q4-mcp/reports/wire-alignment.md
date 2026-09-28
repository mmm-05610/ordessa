# Q4 wire 对齐调和账（016 CMP-mcp 补做完成）

日期：2026-09-29 凌晨。执行：zcode 代打（qoder 两次派工均被无人值守写权限墙
阻断，见 CMP-mcp-report.md §0）。本文件是 `wire.ts` 头部注释引用的调和报告
（整固提交引用了它但从未写出），与 `contract-guard.md`、守护账本三件同动。

## 一、背景（谁留下什么）

1. **q4 线收口态**（`1e7f3733c7`）：wire.ts 为 T08 拟定值（长 id
   `mcp.listDefinitions` 等），后端注册短 id（`mcp.list/get/archive`，
   contracts.md §1 权威）。contract-guard 守护把这份**真实漂移**冻结成账本
   钉住，修复建议登记于 contract-guard.md §四（前端 owner/C0 裁定）。
2. **012 并支整固**（`ba891aff05`"Consolidate plugin mcp; incomplete work
   retained"）：按 §四建议把 `wire.ts` 重写到注册面——方法 id 换短、新增
   `MCP_WIRE_IDENTITY_INJECTION`（serverScope/principal 请求注入，G7）、
   `MCP_WIRE_RESULT_PATH` 解包表、scopeKind 对齐后端值域——但**停在半路**：
   dto.ts 未动（仍是 T08 旧形状、缺 wire.ts 引用的 4 个接口）、守护账本未
   更新（17 格全红）、`wire-alignment.md` 未写、UI/fakes/测试未迁移、tsc 红
   （12+ 错）。合并进 `e1f426570d` 后无人复跑（归并≠验收的实况样本）。

## 二、016 CMP 补做范围（本批完成，全部实测）

**做（守护+dto+Python 全链）**：
0. **契约交叉核对**（回应"调和是否合法化漂移"；引文可复核）：
   `docs/design/mcp/contracts.md` §1 操作表逐字行：
   "list/get/saveRevision/archive | scope、principal、definitionId、
   expectedVersion、operationKey → 版本摘要"——注册操作名与对齐面逐一相符；
   "probe … → probe facts/typed refusal"、"assign/unassign … → assignment"、
   "resolvePreview | target + scope revisions → effective snapshot preview"、
   "inspectConnection/listTools | sessionRef + generation → lease/catalog
   facts"、"planForSubmission/apply/reconcile"（后三者为契约表行内操作；
   本插件注册面含 planForSubmission，apply/reconcile 走 Harness C4 闸门，
   即守护账本的 BACKEND_UNFRONTED 行）——应答承诺均为**种类级**
   措辞，未承诺字段级 schema；canonical 文档不在任何应答承诺里（"版本摘要"
   恰与 latestRevision 摘要行吻合）。§1 逐字："每项 shape/auth/availability
   随原子描述符注册"——**字段级真值源=活注册描述符**。对齐来源的精确表述：
   守护的 round-trip fixture 激活的正是真实 `McpAssetServerPlugin`（同一注册
   面）并经真实 `WireService.dispatch` 采集应答——fixture 应答是注册面行为
   的采样，不是平行真值源；WCG-01/02 直接对着 `RegisteredSurface`（激活插件
   实读的描述符）比对，WCG-03 把 dto 字段钉在该注册面被采样的应答上。两者
   同源，故"按 fixture 校形"与"真值源=注册面"无矛盾。（复核锚点：
   `plugins/assets/mcp/tests/contract/contract_helpers.py` 的
   `RegisteredSurface`/`Stack` 与 `test_wire_contract_guard.py` 的
   WCG-01/02/03 三格。）
1. `dto.ts` 重写为实测对齐版：以守护 round-trip fixture 的真实 dispatch 应答
   逐字段校形（`McpRevisionView`=latestRevision 行、`McpDefinitionSummary`=
   list 行、`McpAssignmentView`/`McpUnassignView`、`McpSaveRevisionResult`、
   `McpPreviewResult`+`McpEffectiveSnapshot`+快照三行类型、
   `McpNativePermissionPosture`（posture_view 源码取证）、`McpListToolsResult`
   （service.list_tools 源码取证）、`McpProbeFacts.negotiation` 补齐、
   `McpCatalogFacts`=catalog_view 实形）。
2. 守护调和（tests/contract/）：`TS_RENAMES={}`（绑定表 id 即注册 id）、
   `PARAM_EXTRA_GAPS/PARAM_MISSING_REQUIRED={}`（请求体=调用点∪身份注入，
   注入表从 wire.ts 源码解析）、`RESPONSE_LEDGER` 全行对齐（解包路径从
   `MCP_WIRE_RESULT_PATH` 源码解析互证，新增 WCG-03b 格）、WCG-04 改钉对齐
   值域对、WCG-04b 改为后端值域墙的活线见证（TS 已拼不出 'user'）、WCG-05
   反空转孪生同步。**契约测试 17 passed**。
3. `harness_wiring/test_controlled_chain.py`：C4 native-receipt 协议
   （51c7905108，并入 main 时带来）下受控 fake 升级——`activate_generation`
   回 `NativeActivationReceipt`（绑 operation/generation/manifest）、
   `observe` 回读携带同一 receipt；corrupt 反例透传 receipt 使断言隔离在
   内容失配。**harness_wiring 55 passed**。
4. 全量：`pytest plugins/assets/mcp` = **525 passed / 0 failed**（接手时
   4 failed + 2 errors）。

**不做（登记卡点 C-mcp-fe，不伪造）**：UI 层迁移（settings.tsx / status.ts /
chat.tsx / entry.tsx / fakes.ts / 4 个 vitest 文件）。tsc 现红 75 行
（文件分布：fakes 20、settings 14、status 12、wire.test 6、其余若干——精确
清单见 CMP-mcp-report.md §4）。三个语义裁定缺一不可，无人值守不能编：
(a) `mcp.get` 新面**不回传 canonical 文档**，settings 编辑器"编辑预填"数据源
消失——需裁定 wire 面补 canonical 或 UI 改重建式编辑；
(b) status 六阶梯的 approved/enabled 档在新面上失去定义行证据源
（approvedRevision 移到 assignment 视图、preview 不再有 entries）——需裁定
阶梯语义的证据映射；
(c) `createFetchMcpWireClient` 强制 identity，entry.tsx 无身份来源——
即 wire.ts 注释所言 G7/T09 装配点。

## 三、实测账（真实退出码）

| 采集 | 命令（仓根） | 结果 |
| --- | --- | --- |
| 接手时 | `.venv/bin/python -m pytest plugins/assets/mcp -q` | 4 failed, 518 passed, 2 errors |
| 完成后全量 | 同上 | **525 passed**（41.7s） |
| 契约目录 | `pytest plugins/assets/mcp/tests/contract -q` | 17 passed |
| harness_wiring | `pytest plugins/assets/mcp/tests/harness_wiring -q` | 55 passed |
| 前端 tsc（卡点取证） | `node_modules/.bin/tsc --noEmit`（frontend/） | 75 行错误（清单已登记） |

## 四、诚实边界

- 本批未跑 vitest/build（UI 语义未裁定前跑不出有意义的绿）；未触碰
  `apps/server`/`packages/*`/其他插件；全部写入在 `plugins/assets/mcp/**`
  与 specs 报告内。
- `McpEffectiveSnapshot.laneByDefinition` 值类型按 `resolve.py`
  `Mapping[str, Mapping[str, str]]` 取证；`McpListToolsResult` 按源码取证，
  守卫对两行维持 NOT_SAMPLED（活 lease 面归 T10-INT-01/05）。
