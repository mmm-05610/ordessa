# CMP-SK-report · skills 存量甄别补完(q1 账本 23 项)016 夜批交付

状态:**REVIEW_READY(zcode 代打;纯甄别包,零代码改动)**。分支
`codex/plugin-skills`,工作树 `worktrees/overnight-2/son-cmp-skills`。qoder 按环境级
裁定不可用(证据链见父会话 `worktrees/overnight-2/reports/qoder-unavailable-record.md`;
三父会话独立复现),按 spec.md 红线 5 代打并标注**「qoder 失败、zcode 代打」**。

## R0 甄别表(以 main 版账本 specs/011-q1-skills/tasks.md 为准,23 项)

三档口径:已实现已验(附证据指针)/已实现未验(受控补验后可勾)/未做(今晚补做或
注明卡点)。**甄别结论:在 `plugins/assets/skills` 写入面内,账本各事项的域内实现
已完备且有测试证据;本包零代码改动——没有需要补做的域内缺口,剩余未勾项全部是
跨域/线级卡点或上游断链,如实登记。**

**R 行(线级过程门)**

| 项 | 档 | 依据/卡点 |
| --- | --- | --- |
| R0 | 已实现已验 | 本报告即 R0 产物(SHA 冻结:son 树 @ `ab402f4f7b`;环境=venv 记录于父报告) |
| R1 | 已实现已验 | 接口请求账在案:specs/011-q1-skills/api-requests.md(main@`b6d2748134`) |
| R2 | 已实现未验 | "生产假接口为零"有树内证据(tests/test_no_execution.py、test_dependency_direction.py、G01 纯度);"全部任务有归属"的完整性核验属线级动作,今晚不代判 |
| R3 | 未做(卡点) | 检查点/接线清单在案(harness-api checkpoint `d3f026904e` 被树内消费),但"定向及相关全链门通过"需跨域集成,今晚不可验 |
| R4 | 未做(卡点) | "clean ready commit"与夜批 git 纪律冲突(父会话只读 git,不提交);留用户验收后执行 |

**T 行(域内实现;勾选强度口径=该 item 所列测试文件存在于套件且套件实跑绿
(427 passed),文件名与 item 的 G 门对应关系按上表列明;「逐条断言级」审计未做,
此处不冒称。实测:433 collected,其中 427 passed,6 项在 setup/fixture 期 error
(导入 profile 失败,被测断言未执行)——两项计数均来自 pytest 原始输出)**

| 项 | 档 | 证据指针(树内测试/仓库工件) |
| --- | --- | --- |
| T00 | 已实现已验 | specs/011-q1-skills/implementation-baseline.md(main@`b6d2748134`);pins 由 packaging 锁在案 |
| T01 | 已实现已验 | specs/011-q1-skills/evidence/(main@`b6d2748134`;SHA256SUMS.txt + junit)+ research/legacy-inventory.md |
| T02 | 已实现已验 | specs/011-q1-skills/research/brand-matrix.md(main@`b6d2748134`;被树内 capabilities.py 逐格引用);research/probe-results.md |
| T03 (G01/G02) | 已实现已验 | tests/test_g01_legacy_fidelity.py、test_library_g02_refusals.py、test_frontmatter_spec.py、test_tree_bounds.py |
| T04 (G03/G04) | 已实现已验 | tests/test_import_session.py、test_library_g03_import_states.py、test_library_revisions.py、test_records_pinning.py、test_store_atomic.py |
| T05 (G05/G06) | 已实现已验 | tests/test_assignments_resolution_g05.py、test_assignments_tristate_g06.py、test_assignments_store_cas.py、test_binding_cas.py |
| T06 (G07) | 已实现已验 | tests/test_assignments_authorization_g07.py、test_library_kind_isolation.py |
| T07 (G08/G09) | 已实现已验(facet 注册半=已实现未验,上游阻塞) | 勾选证据=tests/test_migration_profile_bindings_g08.py、test_migration_rollback_g09.py、test_migration_restore_demo.py(实跑绿);facet 经 profile-api 注册面的 6+2 项测试 setup 期 error(上游断链),见下节排除性映射 |
| T08 (G10–G13) | 已实现已验 | tests/test_g10_capability_pins.py、test_g11_native_discovery.py、test_g12_name_conflicts.py、test_g13_update_decisions.py、test_harness_api_registration.py、test_harness_adapters_boundaries.py、test_harness_intent_boundaries.py |
| T09 (G14 Settings UI) | 未做(卡点) | 桌面前端,写入面外(desktop 线) |
| T10 (G15 Profile editor) | 未做(卡点) | 同上,Profile 前端 |
| T11 (G16) | 已实现已验(域内半;跨域另一半归 Harness 消费,不计入本档) | tests/test_g16_evidence_verify.py(stored/selected/projected/loaded/used 分证据,不冒称 loaded);Harness 应用半属跨域消费 |
| T12 (G17 Chat 贡献) | 已实现未验 | 树内 createChatContributions 注册在案(q1 报告 §提交账 `54763b34e6`,G17 反例 18 例);Chat 侧消费归 chat 域,CMP-chat(overnight-3)甄别 |
| T13 (G18) | 已实现已验 | tests/test_apply_chain_t13.py、test_assignments_snapshot_g18.py |
| T14 (G19) | 已实现未验 | tests/test_skill_delivery_producer_t14.py(受控 producer 面已验);**真实原生装载格=unknown**——brand-matrix 各品牌 loaded_evidence 均无在库一手证据,adapter verify 天花板=projected,不冒称(q1 报告 §5 亦如实登记 PARTIAL) |
| T15 (G20 产品装配) | 未做(卡点) | products 装配归 C0/产品线 |
| T16 (G21/G22 wheel/干净检出) | 未做(卡点) | 发布线 |
| T17 (报告) | 已实现已验 | specs/011-q1-skills/report.md(main@`b6d2748134` 版,REVIEW_READY/整线 PARTIAL,2026-09-28)。注:本 CMP 报告是甄别补充,不充当 T17 的勾选依据(避免自证) |

## 六 errors 说明(非本包缺口)

`tests/test_profile_facet_contribution.py` 6 项 **收集/装配期 error**(被测逻辑与
断言未执行):上游 `ordessa_profile` 导入链断裂——profile/plugin.py 引
`pacthold.resource_contracts.AgentBoxProfileV1`,该符号已迁
`pacthold_runtime_compat.resource_contracts`;错误消息如实命名缺口并声明
"Q1 may not edit plugins/profile"。"登记为已知上游断链"的落点:本报告即登记
(写入面不含 docs/known-issues.md,无法直接写条目);经查 main@`b6d2748134` 的
docs/known-issues.md **尚无**该断链条目——需 profile 线/有权限侧补登记,本包
提请之。收口归 CMP-profile(overnight-3)/014 线。

**六 error 项与已勾项证据集的排除性映射(审阅要求显式声明)**:6 项 error 全部
位于 tests/test_profile_facet_contribution.py(实测 8 项收集 = 2 passed +
6 setup 期 error,名单已冻结于 CMP-SK-pytest-run-20260929.txt;通过的 2 项不依赖
profile 导入)。这 6 项
覆盖的是 **assets.skills facet 经 profile-api 的注册面**(T07 的 facet 半 adjacent
面)。**本表任何已勾项的证据指针均未引用该文件**:T07 的勾选证据=
test_migration_profile_bindings_g08/rollback_g09/restore_demo(已实跑绿)。
因此 6 error 不支撑任何"已实现已验"勾选;facet 注册面的断言级验证被上游
profile 断链阻塞,如实登记为「已实现未验(上游阻塞)」,不在表中冒称。

**pytest 原始输出冻结指针**:specs/016-overnight-batch/reports/
CMP-SK-pytest-run-20260929.txt(427 passed/6 errors + 该文件 8 项收集名单;
本包树内 reports/ 为写入面允许路径)。

## 八家覆盖缺口表(甄别表内列出,任务口径)

| 品牌 | skills adapter | 依据 |
| --- | --- | --- |
| pi / codex / claude | ✅ 配置投影面已实现(harness_adapters/configuration_adapters 三行;与 T14 同口径:真实装载格=unknown 不冒称) | capabilities.py BRAND_STATEMENTS + 测试 |
| hermes / opencode / dsh / kilo | ⛔ 不实施,转阶段二设计(父会话阶段二出可派单方案包) | 品牌优先级裁定 spec.md §品牌优先级 1;harnesses.md 各家 vendor-doc 面 |
| qwen | ⛔ 已除名(用户裁定);harness 侧摘除归 PE2-8 | spec.md §品牌优先级 2 |

实施仅限 E2 可控范围:八家扩展若做,均为配置投影面(假端点可控),但按裁定不入
今晚;缺口如实如上,不冒称覆盖。

## 复用与自建清单(红线 7)

**复用 100% / 自建 0%**:本包为纯甄别补完,全部证据复用 q1 线既有交付(域包、
433 项测试、brand-matrix、evidence 工件、q1 报告)与 main 版账本;无新代码、无新
依赖。理由:甄别结论=域内无缺口可补(见 R0 表),按"复用优先"红线不为凑数造码。

## 测试证据(实跑)

`python -m pytest plugins/assets/skills -q` → **427 passed / 0 failed / 6 errors**
(6 errors=profile-api 上游断链的诚实类型化失败,见上节;433 collected)。
`git -C <son> status --short`:**代码零改动**;唯一新增=本报告
(`?? specs/016-overnight-batch/reports/`,写入面允许的 reports 路径)。

## 审阅

run-review.sh 返回「空 diff」(代打未提交,git 只读);按降级条款同口径裸调
pi+mimo-v2.6-pro 审阅报告伪 diff。**共 3 轮**:首轮(git 证据"零写入"失实/
6 errors "类型化失败"表述过强+known-issues 无条目/T17 自证+指针未冻结)→修复;
二轮(433/6 计数口径自相矛盾→精确化"433 collected/427 passed/6 setup 期 error"
+main 版指针全冻结+T11 档位括注)→修复;三轮(6 error 项与已勾项证据集缺排除性
映射+pytest 原始输出未冻结指针→补排除性声明+输出冻结文件+T07 档位注记)→修复。
**终态:三轮意见全部落实;审阅方三轮一致确认「无谎报勾选、无 fake green、写入面
纪律干净」;末轮两项保留点已补齐,未再起轮。**轮次原文:本目录
CMP-SK-review-round1..3-20260929.md。
