# CMP-mcp-report · 016 夜批（son-cmp-mcp，支 codex/plugin-mcp）

日期：2026-09-29 凌晨。执行者：**zcode 代打**（qoder 不可用，见 §0）。
甄别清单：main 版 `specs/016-overnight-batch/tasks.md` CMP 节 + main 版
`specs/011-q4-mcp/tasks.md`（R0–R4 共 5 项；树内副本与 main 逐字节一致，
`diff` 复核）。写入面自查：`git status` 仅 `plugins/assets/mcp/**` 与
specs 报告（§3 所列）。

## 0. 执行方式记录（qoder 与代打）

1. **run-qoder.sh 第 1 次**（00:34:57，log `…/logs/son-cmp-mcp-qoder-20260929-003457.log`）：
   qoder 无人值守只读分析 12 分钟后，在**写任何文件**时被
   `--permission-mode default` + `-p` 的写权限墙阻断，自行声明
   "Approve the Write permission prompt… or switch to an edit-accepting
   permission mode" 后以退出码 0 结束（零产出）。与本夜 son-lsp 两连、
   father-1/2 的 son-pe1/son-ext/son-pe2 同一堵墙。
2. **处置**：spec.md 红线 5（qoder 不可用 → 父会话代打）。
   **「qoder 失败、zcode 代打」**。降级条款裸调用同一 permission-mode，
   确定性撞同一墙，未做无意义第三次。

## 1. R0–R4 甄别表（三档口径：A=已实现已验 / B=已实现未验→受控补验 / C=未做→补做或卡点）

| ID | 任务 | 三档 | 甄别结论与证据 |
| --- | --- | --- | --- |
| R0 | 读完整输入，冻结实际 SHA/包/红 ID/环境，盘点复用 | **A** | q4 report.md 头部冻结账（起点 96fef2db47、五个 checkpoint publication SHA→merge 链、环境与红 ID 账）；checkpoint-consumption.md 逐笔。本批复核：账本文件树内=main（diff 空），报告引用的 commit 均在分支历史可达 |
| R1 | 独立工作与接口请求完成；消费必需 checkpoint 并留精确 SHA | **A** | report.md 交付 commit 链 14 笔（e00311dbcd→1e7f3733c7）+ integration-request.md/api-requests.md 在树；五个 checkpoint 消费各有 merge SHA。本批复核：`git log` 可达性抽查通过 |
| R2 | 本线全部原包任务有实现/验收/依赖归属，生产假接口为零 | **B→A'**（受控补验后发现并轨断裂，本批修复） | T00–T14 逐项实现/验收/依赖归属表在 report.md §一（V01–V10、L0–L2 证据格）。受控补验：接手时套件 **4 failed + 2 errors**（520 collected）——断裂源=012 并支整固 `ba891aff05` 半途的 wire 对齐 + 并入 main 带来的 C4 native-receipt 协议演进，合并后无人复跑。**本批补做修复**（§2/§3），修复后 **525 passed / 0 failed**；"生产假接口为零"在修复后的套件上成立 |
| R3 | 检查点/接线清单/许可迁移账/报告齐备，定向及相关全链门通过 | **A'**（同上复验口径） | checkpoint-consumption.md、接线清单（t06-wiring/t013）、许可迁移账（t09-migration）齐备；"全链门"按线内口径=定向套件绿+继承红账无新增。本批复验：定向 `pytest plugins/assets/mcp`=525 绿；`apps/server` 全链门受主会话 INT 管辖（lines 口径不扩到跨域） |
| R4 | Spec Kit analyze/converge 查漏，未完成项如实；发布本线 clean ready commit | **A**（附遗留登记） | `49dfa61522`(converge) 在交付链；report.md §二阻塞 6 项/§三未测边界如实（产品装配 L3、真 CLI 装载、profile facet 组合、compat 迁移执行、SDK 路线、wire principal 注入——均精确到 integration-request 编号）；ready 支 `codex/011-q4-ready` 已布 |

结论：**q4 账本 5 项 = 甄别完成，全部 A（R2/R3 经本批受控补验后恢复 A）**。
无 C 档（未做）项；卡点为**新发现的线外遗留**（§4，非 q4 账本项）。

## 2. 受控补验发现与本批补做（细节见 wire-alignment.md）

1. **012 整固半成品**（`ba891aff05`"incomplete work retained"）：wire.ts 已
   重写到注册面（短 id/身份注入/解包表/scopeKind），但 dto.ts、守护账本、
   `wire-alignment.md`（被引用从未写出）、UI/fakes/测试全部未动 → 守护
   17 格红、tsc 红。**补做**：dto.ts 对齐实测应答、守护账本调和
   （WCG-01..06 + 新增 WCG-03b 解包路径互证格）、wire-alignment.md 补写、
   contract-guard.md 补调和记。
2. **C4 协议演进未跟**（并入 main 带来 51c7905108 native-receipt 口径）：
   harness_wiring 受控 fake 仍旧形（activate 3 参/无 receipt）→ apply 落
   Unknown 且零物化。**补做**：fake 升级为 receipt 协议（对齐 harness 自家
   受控运行时形制），corrupt 反例透传 receipt。
3. 补做后：`pytest plugins/assets/mcp` = **525 passed**（接手 4F+2E；
   契约 17、harness_wiring 55）。

## 3. 写入面清单（本批全部改动）

- `plugins/assets/mcp/frontend/src/dto.ts`（对齐重写）
- `plugins/assets/mcp/tests/contract/contract_helpers.py`（+注入/解包表解析，
  请求体并入注入）
- `plugins/assets/mcp/tests/contract/test_wire_contract_guard.py`（账本调和）
- `plugins/assets/mcp/tests/harness_wiring/test_controlled_chain.py`（receipt 协议）
- `specs/011-q4-mcp/reports/wire-alignment.md`（新）、
  `specs/011-q4-mcp/reports/contract-guard.md`（调和补记）、
  `specs/016-overnight-batch/reports/CMP-mcp-report.md`（本文件）

## 4. 卡点登记（晨裁材料；非 q4 账本项）

**C-mcp-fe（前端 UI 迁移，tsc 红 75 行）**：整固把 wire 层对齐后，UI 消费面
（settings.tsx 14 错 / status.ts 12 / fakes.ts 20 / 测试 9 / entry 1）全部
待迁移。**三个语义裁定缺一不可，无人值守不能编**：
(a) `mcp.get` 新面不回传 canonical 文档 → settings"编辑预填"数据源消失
（wire 补 canonical vs UI 改重建式编辑，需 C0/前端 owner 裁定）；
(b) status 六阶梯 approved/enabled 档的新证据源（approvedRevision 移至
assignment 视图、preview 无 entries）——阶梯语义映射需裁定；
(c) `createFetchMcpWireClient` 强制 identity，entry.tsx 无身份来源
（wire.ts 注释所言 G7/T09 装配点）。
**不伪造**：本批不动 UI 语义；tsc 红清单如实随报告移交。

其余 q4 报告 §二既有阻塞（产品装配、真 CLI、profile facet 组合、compat
迁移、SDK、wire principal）维持原状，归 INT/各 owner，本批未扩权。

## 5. 复用与自建清单（红线 7）

复用：q4 全部交付物（backend/adapters/前端 wire 层/守护方法学）、harness
自家受控运行时形制（receipt fake 照抄协议）、守护 round-trip fixture 方法学。
自建：注入/解包表源码解析（~30 行）、receipt fake 升级、dto 对齐重写
（全部按实测/源码取证，零发明）。自建比例低且均为调和必需。

## 6. 审阅

（待 run-review.sh 执行后回填）
