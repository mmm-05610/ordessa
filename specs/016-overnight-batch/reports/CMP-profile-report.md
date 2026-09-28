# CMP-profile-report · 016 夜批（son-cmp-profile，支 codex/plugin-profile）

日期：2026-09-29 凌晨。执行者：**zcode 代打**（qoder 不可用，同夜系统性写
权限墙；本包派工 log
`…/logs/son-cmp-profile-qoder-20260929-011316.log`，只读阶段即被墙，与
son-lsp/son-cmp-mcp 同因，详见各自 §0）。甄别清单：main 版
`specs/011-z1-profile/tasks.md`（R0–R4 + PV-01..12 共 17 项；树内=main）。
写入面自查：本批零代码改动（甄别=复验+归档），仅本报告与新 venv（gitignored）。

## 0. 受控复验环境（树内独立 venv，杜绝跨树污染）

z1 线依赖一串本地包（pacthold/runtime-compat/server-plugin-api/harness-api/
harness/server/server-compat/workspace/permissions 三件/sandbox 三件/
products/server）与 profile 自身（entry-point 发现测试要求 dist 已安装）。
**主仓 venv 不装**（editable 指进儿子树会向其他会话泄漏 entry point）——
在树内建 `.venv` 按依赖序 editable 安装后复验。前两轮安装失败均为顺序问题
（pip 链式安装先解析全部依赖），按序逐个解决。

## 1. 复验门（真实退出码）

| 门 | 线报告（收口时） | 本批复验 |
| --- | --- | --- |
| `pytest plugins/profile/tests -q` | 140 passed | **152 passed / 0 failed**（含 entry-point 发现、5 项真实 C4 服务、PA-5 品牌矩阵 golden——分支较收口点净增 12 测） |
| `run_counterexamples.sh` | 12/12 | **12/12**（反例全部被门判别） |
| `boundary_check.sh` | 0 violations | **0 violations** |
| 三包 vitest | 28 passed（9+10+9） | **28 passed**（api 9 + frontend 9 + chat-glue 10，与线报告逐包吻合） |
| 三包 tsc | ×3 全 0 错 | **未复现**（见 §3 环境登记） |

## 2. R0–R4 + PV-01..12 甄别表（三档：A=已实现已验 / B=已实现未验→补验 / C=未做）

| ID | 三档 | 证据与结论 |
| --- | --- | --- |
| R0 | **A** | z1 report 冻结账（树/分支/起点）+ 检查点消费五笔固定 SHA（foundation 8844c475bc、chat-api 54ad26c15d/r2 31fb2db46d/r3 3d8c3fa410、harness-api d3f026904e） |
| R1 | **A** | 阶段提交链 12+ 笔在分支可达；integration-request.md 在树；消费账含锁冲突 owner 处理注记 |
| R2 | **A**（本批复验） | PV 全表有实现/验收/归属；复验 152 绿。生产假接口：受控 fixture 全部显式标注 controlled-fixture（测试文件头声明），真服务测试走真 ConfigurationApplicationService |
| R3 | **A**（本批复验） | checkpoint/接线/许可迁移账齐备；三门+vitest 复验绿；"全链门"按线内口径 |
| R4 | **A** | `b9dd4896fd` G01–G20/test-scenarios 逐条对照（§查漏提交）；report §未测边界如实；ready 支 `codex/011-z1-ready` 布点、profile-api-ready 检查点支未动（协议遵守） |
| PV-01/02/03 | **A** | platform-bindings/inventory/reuse-ledger 在树（Hermes 许可未核实→reference-only 零复制）；contracts.py 冻结类型+正反例（套件内） |
| PV-04/05 | **A** | v1→v2 迁移幂等/碰撞拒绝/legacy settled 永不升 confirmed（test_migration.py 等，复验绿）；plugin.build 真实注册（entry-point 测试本次在装定环境实测通过） |
| PV-06 | **A**（本线半边按归属） | facet v2 descriptor/schema/compile/reset 门禁 + 受控第三方 facet 全链（核心零改动断言在套件）；两业务域 glue 归 Z3/Q1（非本线） |
| PV-07 | **A'**（Profile 侧完成；真实端口半边已随 harness-api 消费补齐） | journal 幂等/fence/unknown→reconcile/跨 realm 反例（12 反例门）；harness-api 消费后 `test_harness_real_service.py` 5 项真实服务测试**本批复验绿**（confirmed 出证/permit 拒可重试/丢 ack Unknown/corrupt readback 不假证/reset 不支持诚实阻塞） |
| PV-08/09 | **A**（组件级；真实浏览器几何=登记未测） | 设置页 CAS+dry-run+禁用保留数据；管理器两级导航/冲突保留/未保存询问（vitest 9 格）；真实浏览器几何验收需产品装配（report §未测，维持） |
| PV-10 | **A** | chat 选择器状态机（chat-glue vitest 10 复验绿）：立即显示/无徽标/连续选择最后生效/失败保留草稿/不触端口计数断言 |
| PV-11 | **A'**（G18 真实浏览器与真实品牌矩阵=登记未测，非虚勾） | G01–G08/G13/G15–G17 Python 侧 + G20 glue 侧测试 ID 逐项（复验绿）；未测两项如实维持登记 |
| PV-12 | **A** | 每阶段提交+报告+原失败 ID 对照（evidence-backend-stage1.md）在树 |

结论：**17 项全部 A/A'；其中 PA-7/014-A r2 已验项按派工口径直接归档
（品牌矩阵 golden 等在复验套件内）。无 C 档。** 线报告的 PARTIAL 口径
（真实浏览器几何、真实品牌矩阵、组合 2/3）维持为**登记未测**，不虚勾。

## 3. 环境登记（非缺陷）

1. **tsc ×3 未复现**：三包 vitest 别名（vitest.config.ts）可解析
   `@ordessa/plugin-profile-api`（28/28 绿），tsc 依赖 npm workspaces
   node_modules——树内 `npm ci` 失败：根 package-lock 与 branch package.json
   脱同步，**即 z1 线自记遗留「根锁采 incoming，本线增量保持未提交」**。
   锁和解归 C0（integration-request），本批不私改根锁。
2. 主仓 venv 污染规避：profile dist 只装进树内 `.venv`（gitignored），
   不进共享 venv（entry-point 组会跨树泄漏）。

## 4. 复用与自建清单（红线 7）

本批零代码：纯甄别+复验+归档。复用=z1 全部交付物与测试门、harness 自家
受控运行时（真服务测试）、树内 venv 安装法（可复用的环境复现路径，已写入
本报告 §0 供后续包复用）。

## 5. 审阅

（待后备审阅后回填）
