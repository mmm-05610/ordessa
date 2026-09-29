# CMP-SA-report · subagents 存量甄别补完(q3 账本 21 项)016 夜批交付

状态:**REVIEW_READY(zcode 代打;纯甄别包,一处测试基建零改动说明见下)**。分支
`codex/plugin-subagents`,工作树 `worktrees/overnight-2/son-cmp-subagents`。qoder 按
环境级裁定不可用(证据链见父会话
`worktrees/overnight-2/reports/qoder-unavailable-record.md`),按 spec.md 红线 5 代打,
标注**「qoder 失败、zcode 代打」**。

## R0 甄别表(以 main@`b6d2748134` 版账本 specs/011-q3-subagents/tasks.md 为准,21 项)

**实测口径(来自 pytest 原始输出,已冻结指针)**:`python -m pytest
plugins/assets/subagents -q --continue-on-collection-errors` →
**862 passed / 0 failed / 1 collection error**(输出冻结:
reports/CMP-SA-pytest-run-20260929.txt)。collection error =
tests/test_profile_facet_t10.py 模块级 `import ordessa_profile` 失败——**Profile 是
monorepo 之外的独立仓**(AGENTS.md 开篇;本环境无其 live tree,docs/
reference-index.md 所列路径不在本机),被测断言未执行,非本域缺口。测试基建零改动:
不改该测试文件、不加 skip、不用 collect_ignore 藏文件——以 runner 旗标让其余
28 个测试文件实跑,error 如实在案(不 fake green 红线)。

**R 行(线级过程门)**

| 项 | 档 | 依据/卡点 |
| --- | --- | --- |
| R0 | 已实现已验 | 本报告即 R0 产物(核对对象=reports/ 下新增文件清单+son 树 @ `e321a966c2`,非自证勾选) |
| R1 | 已实现已验 | specs/011-q3-subagents/api-requests.md(main@`b6d2748134`) |
| R2 | 已实现未验 | "假接口为零"树内有证(test_prohibitions_t03g、test_guards_are_load_bearing_t03、test_boundaries_t03b);"全部任务归属"完整性核验属线级动作 |
| R3 | 未做(卡点) | 线级全链门,跨域 |
| R4 | 未做(卡点) | 夜批 git 纪律:父会话只读 git,不提交;留用户 |

**T 行(勾选强度口径=所列测试文件在套件中实跑绿(862 passed)+文件-item 对应按表
列明;逐条断言级审计未做,不冒称)**

| 项 | 档 | 证据指针(树内 tests/) |
| --- | --- | --- |
| T00 | 已实现已验 | specs/011-q3-subagents/implementation-baseline.md(main@`b6d2748134`) |
| T01 | 已实现已验 | specs/011-q3-subagents/legacy-inventory-matrix.md(main@`b6d2748134`) |
| T02 (G01–G03) | 已实现已验 | specs/011-q3-subagents/capability-matrix.md + pi-extension-audit.md(main@`b6d2748134`) |
| T03 (G04–G06) | 已实现已验 | test_package_shape_t03、test_capacity_retention_t03、test_cas_archive_clone_t03、test_credentials_t03、test_revisions_t03、test_prohibitions_t03g、test_import_preview_t03、test_guards_are_load_bearing_t03、test_boundaries_t03b |
| T04 (G07–G09) | 已实现已验 | test_assignments_t04、test_resolution_t04、test_scopes_t04、test_references_t04、test_permissions_seam_t04、test_ceiling_t04、test_service_gaps_t04 |
| T05 (G10) | 已实现已验 | test_migration_t05 |
| T06 (G11/G13 Claude) | 已实现已验 | test_claude_adapter_t06、test_adapter_intents_t06、test_adapter_seam_mapping_t06、test_contract_migration_guards_t06 |
| T07 (G12/G13 Codex) | 已实现已验 | test_codex_adapter_t07 |
| T08 (G14 Pi 条件) | 已实现已验 | test_pi_adapter_t08(条件 adapter:无受审扩展即 unsupported,不装示例扩展——任务原文语义) |
| T09 (G15 Settings UI) | 未做(卡点) | 桌面前端,写入面外 |
| T10 (G16 Profile facet/editor) | 已实现未验(上游不在本环境;「已实现」的依据=测试文件在树可核,其断言级验证本环境不可执行——档位取保守档,不为凑验升档) | 本域侧:tests/test_profile_facet_t10.py 已落盘(29 测试,覆盖 owner 宿主注入/解析器单一来源/在途快照/失败 apply 保旧覆盖/Unknown 可查/卸载隐藏不删/未知 schema 隔离)。二手指针(非本档勾选依据,仅线索):specs/011-q3-subagents/report.md(main@`b6d2748134`)T10 行记载提交树隔离复测 671 passed/0 failed、本面 28 tests/零 skip(隔离复测含当时 643 基线,与今日 862 口径不同源)。本环境无法复跑——profile 独立仓不在,收集期 error 在案。G16 生产链半格缺(需 SR-2 permit),q3 报告已如实登记 |
| T11 (G17 Chat 菜单) | 未做(卡点) | 跨域接缝(Chat 域),树内无本域侧测试;归 CMP-chat(overnight-3)甄别 |
| T12 (G18–G20) | 已实现未验(受控面已验,真实链未验) | test_apply_t12(受控 apply 面);经 Harness 同一 submit permit 的真实链归 C0 集成 |
| T13 (G21 产品启用) | 未做(卡点) | 产品线 |
| T14 (G22–G24 三品牌分级证据) | 部分实现未验 | L1 受控面已验(上列 adapter 测试);**Pi 无安全 extension-backed L3 → 按任务原文明确:三品牌 L3 未完成,不报三品牌通过**;失败差分归线级 |
| T15 (报告) | 已实现已验 | specs/011-q3-subagents/report.md(main@`b6d2748134`,滚动更新,四态词纪律)+ 本 CMP 甄别补完(不充当 T15 勾选依据,仅补账) |

## 品牌覆盖缺口表(甄别表内列出)

| 品牌 | subagents adapter | 依据 |
| --- | --- | --- |
| claude / codex | ✅ 已实现(T06/T07 实跑绿) | 上表 |
| pi | ✅ 条件 adapter(T08:仅 Harness 已登记受审扩展且真实控制端口存在才编译;否则 unsupported——今晚环境无该扩展,按设计 unsupported,不装示例扩展) | test_pi_adapter_t08 |
| hermes / opencode / dsh / kilo | ⛔ 不实施,转阶段二设计 | 品牌优先级裁定(spec.md §品牌优先级 1) |
| qwen | ⛔ 已除名(q3 账本本就只有三品牌,无 qwen 行;harness 侧摘除归 PE2-8) | spec.md §品牌优先级 2 |

## 复用与自建清单(红线 7)

**复用 100% / 自建 0%**:纯甄别补完。全部证据复用 q3 线既有交付(域包 29 个测试文件
中 28 个实跑(862 项绿)+1 个收集 error 在案、capability-matrix/pi-extension-audit/legacy-inventory-matrix、
q3 滚动报告)与 main 版账本。唯一环境动作=runner 旗标
`--continue-on-collection-errors`(不改树内任何文件;理由:上游 profile 仓缺位
导致 test_profile_facet_t10.py 单文件收集 error,该文件 29 项未跑——不得掩盖其余
28 个测试文件 862 项的真实绿,也不得用 skip/删除隐藏该 error)。

## 测试证据(实跑)

`python -m pytest plugins/assets/subagents -q --continue-on-collection-errors` →
**862 passed / 0 failed / 1 collection error**(冻结:
CMP-SA-pytest-run-20260929.txt)。`git -C <son> status --short`:**代码零改动**;
唯一新增=本报告与输出冻结文件(reports/ 写入面允许路径)。

## 审阅

run-review.sh 返回「空 diff」(代打未提交,git 只读);按降级条款同口径裸调
pi+mimo-v2.6-pro 审阅报告伪 diff。**共 2 轮**:首轮(冻结输出件未入 diff/T10
二手 671 passed 无指针且档位混用/33 vs 34 文件口径矛盾+R0 自证)→修复(冻结件入
diff、二手指针标 main@`b6d2748134` 并声明不作勾选依据、改 29 文件中 28 实跑口径、
R0 改核对清单式);二轮(R0 段残留"33 个测试文件"旧口径、T10"已实现"由二手撑起
与声明矛盾、冻结件无命令行与错误原因且 29/28 数字差异未说明)→修复(清残留、T10
档位降为保守档并声明依据口径、冻结件补命令行/环境/错误原因/29-28 演进说明)。
**终态:两轮意见全部落实;审阅方两轮一致确认「无 fake green、写入面仅 reports/
两文件、862 passed 与冻结件自洽」;末轮三项已修,未再起轮。**轮次原文:本目录
CMP-SA-review-round1..2-20260929.md。
