# 016 · PE2 harness-native-evidence 报告

- 分支/工作树：`codex/plugin-harness` @ ef554ac63d 直推；代码提交 `63b3aaa84d`（23 files，+717/−337，全部在 `plugins/harness/**`）。
- 执行时间：2026-09-28（UTC）。
- 纪律对照：零真实模型调用、零外网实测（全部为受控替身/假端点）；未 merge/rebase/切分支；未 push。

## 1. 任务勾选对照

任务行原文见 `specs/016-overnight-batch/tasks.md` §PE2 与 §并入（不删任务行；因写入面不含该文件，勾选在本报告侧完成）。

- [x] **PE2-1** native_evidence 模型：观测事实 = native owner receipt、原生会话身份、launch 溯源；DTO 冻结 → `api/src/ordessa_harness_api/native_evidence.py`（五型，§7.1 全字段）；读侧服务 → `src/ordessa_harness/application/native_evidence.py::NativeEvidenceService`；journal 只读投影 → `operation_journal.py::read_native_evidence`（复用既有 `native_evidence`/`native_verifications` 表，零新表）。
- [x] **PE2-2** 三品牌供给：`EVIDENCE_SUPPORTED_BRANDS = ("pi","codex","claude-code")` 经 `ControlledNativeStandIn` 走真实 journal C4 序列产 evidence；`EVIDENCE_UNSUPPORTED_BRANDS` 登记 hermes/opencode/dsh/kilo = "no owner-side activation receipt surface in the brand adapter; 016 brand ruling defers this brand to phase-two design"（不硬凑；测试钉注册表本身）。
- [x] **PE2-3** 与 C4 对齐（51c7905108 口径）：receipt 必须 operation 绑定、readback evidence_ref 与 receipt evidence_ref 必须不同源且一致，才投影 `complete`；未另造协议——DTO 字段镜像 `NativeActivationReceipt`，三态判定完全由 journal 既有表驱动。
- [x] **PE2-4** 三态受控测试 → §2 逐格表，12/12 绿（含缺席=诚实 None）。
- [x] **PE2-5** 边界测试 → `tests/test_native_evidence_boundaries.py` 3/3 绿：全插件 AST 扫描无 `ordessa_permissions/permissions` import；api DTO 模块主机无关（仅 stdlib+包内）；native_evidence 两模块 import 根封闭在 harness 内。改动全部落在 `plugins/harness/**`（见 `git show --stat 63b3aaa84d`）。
- [x] **PE2-6** 本报告 + §7 api-requests 回填（DTO 全字段+失败反例，与 PE1-2 同表口径）。
- [x] **PE2-7** c0 账本 24 项甄别 → §8。
- [x] **PE2-8** qwen 摘除 → §9（含"用户裁定除名，数据兼容无存量用户则零迁移"注记与保留面登记）。

## 2. 三态逐格表（evidence 在场 / 缺席 / readback 不一致）

受控测试文件：`tests/test_native_evidence_controlled.py`；隔离运行 verbatim：`15 passed in 0.36s`（12 controlled + 3 boundaries）。

| 格 | 语义 | 判定 | 测试节点（全部 PASSED） |
| --- | --- | --- | --- |
| pi 在场 | receipt+distinct readback+确认一致 | complete | `test_supported_brands_supply_complete_evidence_from_durable_state[pi]`（含 reopen 后持久相等） |
| codex 在场 | 同上 | complete | `...[codex]` |
| claude-code 在场 | 同上 | complete | `...[claude-code]` |
| 缺席：无操作/裸预约/仅 manifest/跨 principal | 不合成 bundle | **None**（诚实缺席） | `test_absent_operation_and_bare_reservation_read_as_none` |
| 在场缺 readback | receipt 已落、独立回读未落 | partial+reason | `test_receipt_without_independent_readback_is_partial`；`test_readback_recorded_before_confirmation_is_partial` |
| readback 复用 activation ref | 两证同源=不独立 | inconsistent+reason | `test_readback_reusing_activation_ref_is_inconsistent`（sqlite 注错 `native_verifications.readback_evidence_ref`） |
| Confirmed 身份与 receipt 冲突 | 持久事实互斥 | inconsistent+reason | `test_confirmed_identity_conflicting_with_receipt_is_inconsistent` |
| DTO 冻结反例 | 缺字段/类型伪装/bool 伪装 int | ContractError | `test_receipt_facts_dto_is_frozen_to_the_c4_receipt_shape` |
| 品牌注册表 | unsupported 四品牌+原因逐字 | 拒绝伪造 | `test_unsupported_brands_are_registered_with_reasons_not_fabrication` |
| 原生会话身份 | server_acp `NativeSessionObservation` 投影 | facts/None | `test_session_identity_maps_agent_confirmed_observation` |
| launch 溯源 | registry+launch-descriptors 声明事实 | facts/None | `test_launch_provenance_reads_declared_registry_facts`（pi 有；未知品牌 None；opencode canonical route=null → None 诚实缺席） |

## 3. qoder 调用记录

本包未调用 `bin/run-qoder` 封装（0 次；无退出码可报）。全部执行由会话内子代理以受控命令完成，命令与逐字计数见 §4，无失败封装需要处置。

## 4. 执行记录（命令 + 逐字计数）

环境：解释器 `/home/maoqh/projects/ordessa/.venv/bin/python`（3.12.14，pytest 9.1.1）——裸 `python3`/`python3.12` 均无 pytest；venv 的 editable 安装指向**主树**，故所有运行以 `PYTHONPATH="$WT/plugins/harness/src:$WT/plugins/harness/api/src:$WT/packages/pacthold/src:$WT/apps/server/src:$WT/packages/server-plugin-api/src"` 前置本工作树源码并先行验证 `ordessa_harness.__file__` 解析到 worktree（防假证）。node v22.22.1。

| # | 命令（cwd=`plugins/harness`） | 结果（逐字） | 判定 |
| --- | --- | --- | --- |
| E1 | `… -m pytest tests/test_native_evidence_controlled.py tests/test_native_evidence_boundaries.py tests/test_operation_journal.py -q`（首轮） | `1 failed, 23 passed in 0.52s` | 唯一红 = 本包新边界测试 allowed 集漏 `json/math`（api/schema.py 既有 stdlib import），修白名单非修断言 |
| E2 | `… -m pytest tests -q`（首轮全量） | `5 failed, 442 passed, 3 skipped in 8.99s` | 5 红分解：2=继承（known-issues.md:13）+3=本包在修（E1 项、`test_launch_descriptors` 8→7、packaging qwen 记账） |
| E3 | 修复三项后 `… -m pytest tests -q`（复跑全量） | `2 failed, 445 passed, 3 skipped in 8.44s`（exit 1） | 两红逐 ID = `tests/install/test_acp_schema_drift_target.py::test_the_acp_schema_a_closure_carries_satisfies_the_adapter_that_needs_it` 与 `…::test_a_root_override_of_the_schema_does_not_violate_a_declaration_in_the_closure`——与 known-issues.md:13 登记的继承红逐 ID 一致（pi sdk 1.4.0/1.3.0 drift），非本包引入 |
| E4 | `… -m pytest tests/test_native_evidence_controlled.py tests/test_native_evidence_boundaries.py -v`（隔离） | `15 passed in 0.36s`，15 个节点逐条 PASSED | §2 表的直接证据 |
| E5 | `node --test tests/launch_descriptors.test.mjs` | exit 0；`# pass 3 # fail 0` | qwen 摘除后 JS 描述符断言绿（含 seven brands/8 routes 计数） |
| E6 | `node --test tests/access/access_entry_behavior.test.mjs` | exit 0；`# pass 26 # fail 0` | E6 系该文件全量 26 子测试（E1–E25 编号为测试内名），全绿 |
| E7 | `node --test tests/**/*.test.mjs`（广域） | exit 1；`# tests 121 # pass 120 # fail 1` | 唯一红：`G05: the orchestration fixture needs an explicit controlled entry mode`（`tests/access/access_launch_route.test.mjs:40`，`CONTROLLED_PEER_MISMATCH`） |
| E8 | 单独复跑 E7 红文件 ×2（worktree） | 两次均 `# pass 6 # fail 1`，同节点同错 | 确定性失败，非并发串扰 |
| E9 | 同一命令在**主树** `/home/maoqh/projects/ordessa/plugins/harness`（HEAD b6d2748134，未含本包改动） | exit 1；`# tests 7 # pass 6 # fail 1`，同节点同错逐字复现 | 判该红为**继承红**（本包未触碰该文件；git status 佐证）。建议登记 known-issues（docs/ 在本包写入面外，报回父编排） |

过程红账（不 fake green 的反向纪律也如实记）：首轮 5 红中本包自产 3 红，逐项修复且**未删任何断言**（launch_descriptors 计数 8→7 是品牌除名的同步事实；packaging 记账以显式 `RETIRED_NPM_ROOTS` 登记替代删数据；E1 为测试白名单补 stdlib 两项）。

完整性记录：本轮曾有一个写入子代理虚报三处编辑"已应用"，主代理磁盘复查证伪（文件原样）后重派并用 grep/Read 逐项复核；§4 全部计数取自复核后的磁盘状态与提交 `63b3aaa84d`。

## 5. 审阅记录（父编排执行后回填，2026-09-29 02:1x）

1. **封装审阅（`run-review.sh`）失败 + 原因**：exit 126，`/usr/bin/timeout: 参数列表过长`——分支相对 main 的 diff（146KB）以 argv 传给 pi 超出内核单参数上限。属脚本自身无法运行（环境约束），按父文档降级条款改裸调。
2. **裸调审阅（pi + mimo-v2.6-pro，模型白名单遵守；留痕 `主仓 reports/son-pe2-harness-review-fallback-20260929-020133.md`）**：审夜批增量 `git diff ef554ac63d..HEAD`（102KB，未截断；014 存量 diff 已有 20260928-231239 号审阅覆盖）。**结论：有保留**。三条发现：①qwen 测试文件整体退役为 docstring 而生产模块留存，构成覆盖空洞（摘除口径矛盾点）；②`operation_evidence` 的 readback 独立性判定仅凭 evidence_ref 字符串不等，complete 证明强度受 C4 journal 既有语义约束；③下游 server 侧 2 个 qwen 红未入 known-issues（docs/ 在写入面外，§10 已转 core）。
3. **父编排处置注记**：①qwen 生产模块去留为显式登记的待裁项（§9/§10.2），保守保留待用户裁定，本包不擅自删码；②readback 证明强度属 C4 协议边界，读侧投影只能如实报告 journal 所存，强化需动 C4 协议（超本包范围，转 core）；③known-issues 落册归父编排/维护者（本报告移交项照搬）。三条均不构成 fake green；无断言删除系为掩盖失败（qwen 删除断言皆有除名裁定背书并逐项登记）。

## 6. 卡点清单

| 卡点 | 内容 | 处置 |
| --- | --- | --- |
| C-PE2-1 | `docs/known-issues.md` 不在写入面：两条应登记项未入册——①G05 继承红（E7–E9 实证）②qwen 运行数据目录兼容疑点（§9） | 本报告登记全文，移交父编排/维护者落册 |
| C-PE2-2 | 下游 qwen 同步面（apps/server、server-compat、permissions、sandbox 共 11 文件）在写入面外 | 逐文件清单转 core，见 §10 |
| C-PE2-3 | 真模型审阅不可用（§5） | 移交父编排 |
| C-PE2-4 | 干净安装/全链门（c0 T17 类）不在本包复验面 | §8 甄别表按静态证据定档，未跑者标"未测" |

## 7. api-requests 回填（DTO 全字段，core 一次对齐）

对应台账 `specs/016-overnight-batch/api-requests.md` AR-1（core 消费 DTO 对齐）与 AR-5。冻结于 `ordessa_harness_api.native_evidence`，全部 frozen dataclass，`kind` 判别字面量 init=False。

### 7.1 NativeOwnerReceiptFacts（kind=`native-owner-receipt`；镜像 C4 `NativeActivationReceipt`，只读）
| 字段 | 类型 | 冻结校验 |
| --- | --- | --- |
| operation_id | str | 非空、无空白边 |
| target | ApplicationTarget | 类型强制 |
| manifest_digest | str | `^[0-9a-f]{64}\Z$` |
| native_session_identity | str | 非空 |
| applied_revision | str | 非空 |
| evidence_ref | str | 非空 |

### 7.2 NativeReadbackVerificationFacts（kind=`native-readback-verification`）
| 字段 | 类型 | 冻结校验 |
| --- | --- | --- |
| operation_id | str | 非空 |
| readback_evidence_ref | str | 非空 |
| distinct_from_receipt | bool | `type is bool`（int 伪装拒绝，沿 c0 G11 口径） |
| consistent_with_receipt | bool | 同上 |

### 7.3 NativeSessionIdentityFacts（kind=`native-session-identity`；源 = server_acp `NativeSessionObservation`）
| 字段 | 类型 | 冻结校验 |
| --- | --- | --- |
| harness_id | str | 非空 |
| connection_id / execution_id / ledger_session_id / native_session_id | str | 各非空 |

### 7.4 LaunchProvenanceFacts（kind=`launch-provenance`；源 = harnesses.toml+launch-descriptors.json 声明事实，不触发任何启动）
| 字段 | 类型 | 冻结校验 |
| --- | --- | --- |
| harness_type / driver / registry_version / registry_digest | str | 非空 |
| launch_source | str | ∈ {`upstream`,`agentbox`} |
| launch_profile_id | str | 非空 |
| launch_modes | tuple[(name, argv-tuple, io), …] | 非空、三元组、项非空；argv 强转 tuple |
| controlled | bool | `type is bool` |

### 7.5 NativeEvidence（kind=`native-evidence`；一操作的原生观测束）
| 字段 | 类型 | 冻结校验 |
| --- | --- | --- |
| receipt | NativeOwnerReceiptFacts | 必须；无 receipt 不合成 bundle |
| readback | NativeReadbackVerificationFacts \| None | — |
| status | Literal[`complete`,`partial`,`inconsistent`] | complete ⇔ readback 存在且 distinct∧consistent（构造期强制） |
| reason | str \| None | partial/inconsistent 必须带 reason |

查询面（core 只读消费）：`NativeEvidenceService.operation_evidence(principal, target, operation_key) -> NativeEvidence | None`；`session_identity(connection_id, native_session_id) -> NativeSessionIdentityFacts | None`；`launch_provenance(harness_type) -> LaunchProvenanceFacts | None`。**缺席一律 None，绝不合成**。失败反例：任一冻结字段缺失/类型伪装（bool→int、digest 非 64hex）→ `ContractError`；complete 无独立 readback → 构造拒绝。

### 7.6 复用/自建清单
- 复用（零新协议、零新表）：C4 `NativeActivationReceipt`/`NativeReadback`（51c7905108 口径）；journal `native_evidence`/`native_verifications` SQLite 表；`server_acp.registry.native_session_observation`；registry loader+launch descriptors；`ApplicationTarget/ErrorCode`。
- 自建（仅读侧投影与冻结）：api 五型 DTO；`NativeEvidenceService` 三态判定；`ControlledNativeStandIn` 受控替身；`supply_brand_evidence` 测试驱动序列；journal `read_native_evidence` 只读方法。

## 8. PE2-7 · c0 foundation 账本 24 项甄别（R0–R4 + T00–T18）

方法：静态现证逐格核对（本包另跑的 §4 全量 pytest/node 计数为独立证据源）；A=已完成且有现证，B=部分/存疑/口径被后续裁定改写，C=归属 core 或其他业务线，注明转出不代做。路径省略前缀 `plugins/harness/` 与仓库根。

| 项 | 一句意图 | 档 | 现证 / 缺口 |
| --- | --- | --- | --- |
| R0 | 冻结输入 SHA/环境/红 ID/复用盘点 | A | `specs/011-c0-foundation-harness/implementation-baseline.md`（冻结 SHA 表、环境实测、B2 ACP owner 符号对照） |
| R1 | 接口请求+消费 checkpoint 留精确 SHA | A | 同目录 `api-requests.md`/`integration-request.md`；report.md 逐项记录消费 checkpoint 全 SHA，对应代码在树 |
| R2 | 原包任务全有实现/验收/归属，生产假接口为零 | B | 归属与 G 表在（`docs/design/harness-v2/verification.md`、T01 账）；T16–T18 无实现闭环，c0 `tasks.md` 24 格未勾，多条生产缝仍为 controlled fixture |
| R3 | 工件齐备且定向+全链门通过 | B | 工件齐（`T01-MIGRATION-LEDGER.md`、`third_party/harness_remote/PATCHES.md`+`SOURCE.json`、report.md）；"全链门通过"不成立——harness 2 红、server 继承红账、`tests/acp_orchestration` 18 红均为 known-issues.md:12-13 登记的 inherited（登记≠通过） |
| R4 | analyze/converge 查漏+发布 clean ready | B | c0 report.md 首行 "final ready remains unpublished"；无 analyze/converge 产物；状态 IN_PROGRESS |
| T00 | 绑定平台 SHA/carrier/ACP owner 对照 | A | `implementation-baseline.md` 全文（含禁活跃树未提交文件声明） |
| T01 | migration 逐文件账+四套件逐 ID 基线 | A | `T01-MIGRATION-LEDGER.md`；report.md 四套件 per-ID 差异表；原始 JUnit 按该线规则外置 /tmp（易失，不入树） |
| T02 | 三品牌 pin+六格实证+他牌基线 | A | `T02-CAPABILITY-EVIDENCE.md`（六格全 <L3 如实列）；pin 在 `packaging/*/package-lock.json` |
| T03 | 独立 api 包无宿主 import（G01） | A | `api/pyproject.toml`（`dependencies = []`+py.typed）、`api/tests/test_contracts.py`+typing 正反例；wheel 隔离证据外置 /tmp |
| T04 | carrier 两点注册/busy/回滚（G02/G03） | A | `tests/test_contribution_registry.py`（碰撞/claims/owner 伪造/busy 卸载 5 节点在案）；report 自限 "full production open" |
| T05 | 包外受控 adapter 注册+配置+卸载（G04） | A | `test_external_adapter_product.py` + `test_configuration_service_controlled.py::test_external_adapter_c4_controlled_apply_requires_actual_readback`（受控载体非原生进程） |
| T06 | 品牌收敛+统一 launch descriptor+保留旧链（G05/G06） | B | 收敛现证在（`test_launch_descriptors.py`+JS 对偶+`launch-descriptors.json`）；"保留旧运行链"被 `REMOVALS.md`（不双轨裁定）实质作废——台账与现树主要口径漂移点；完整 launch 生命周期未证 |
| T07 | handle/claims/codec/intent 合并/目录安全/秘密边界（G07–G09） | B | `materialization/intent_merge.py`+`private_generation.py` 及反例测试在；缺口：secret_ref 后端解析（G09）、native-default/热切换未实现 |
| T08 | journal/fence/幂等/apply-verify-reconcile+故障注入（G10–G12） | B | `application/operation_journal.py`+`test_operation_journal.py`、外成功/落盘失败注入（本包 §4 复跑仍绿）；缺口：**"取消"故障注入零测试**（tests 内 `test_.*cancel` 零命中）；跨实例双 permit open |
| T09 | 重启/resume/instance generation/回收（G13/G14） | B | `test_server_acp_recovery_view.py::test_restart_lookup_never_reattaches_or_relaunches_a_terminal_run`、stop-hook 在；instance-generation 调解与 wire resume 无——report 自证 G13/G14 open |
| T10 | 迁 Model-provider 三品牌映射（G15） | **C → 转 Z3 model-provider 线** | 交付不在本树（`specs/011-z3-model-provider/report.md` PARTIAL）；harness 侧渲染退役排 `specs/014-plugin-release/seams.md` S-08② |
| T11 | 迁 Skills 三品牌（G16） | **C → 转 Q1 skills 线** | 交付在其分支；本树无 skills 插件包；harness 仅存 `adapters/skill_observation.py` 观察缝 |
| T12 | Profile glue（G17） | **C → 转 Z1 Profile 线** | `implementation-baseline.md` §Scope 明文归 Z1；`specs/011-z1-profile/retirement-request.md` 为现证清单；harness 旧 writer 待 S-08③ |
| T13 | 真实 ACP 提交闸门+控制缝同 owner（G18/G19） | B | 现证齐（connectors/acp TS 测试、`apps/server/.../acp_admission.py`+门测试、harness 绑定测试）；闸门 `ready=False`（S-06 翻转依赖 Q5+native_evidence，排 014 P-E）；legacy relay 可旁路；生产附件 port 缺（S-05） |
| T14 | 旧 profile 运行快照迁移+数据兼容审计（G20） | **C → 转 Z1/Server 存储层** | 审计账在树（`T01-MIGRATION-LEDGER.md` 数据路径条目）；真实记录迁移未执行（AGENTS 规则 5 需用户授权）；双写 hazards 已登记未整改 |
| T15 | 装配/锁/发布路径+旧入口清零（G21） | **C → 转 core 产品装配** | seams.md S-01/S-02/S-03/S-10 归 core；harness 侧删除账现证=`REMOVALS.md`+`test_boundaries.py::test_harness_source_has_no_legacy_or_web_imports` |
| T16 | 三品牌六格完整受控链（G22） | B | 六格全 <L3（T02 账）；report "Untested" 在案；原生 CLI 装载格 unknown |
| T17 | 干净 clone/wheel/全 ID 差分/前端/无模型冒烟（G23/G24） | B | report.md 有中间快照计数，但原始 JUnit 外置 /tmp 树内不可复核，且自述后续须重做逐 ID 差分——静态证据不足 |
| T18 | verification.md+删除账+REVIEW_READY | B | `specs/011-c0-foundation-harness/` **无 verification.md**（本包实测 ls 缺席）；删除账散在 REMOVALS.md/report §untested 未合成；未报 REVIEW_READY |

计数：**A=8（R0,R1,T00–T05），B=11（R2,R3,R4,T06–T09,T13,T16,T17,T18），C=5（T10,T11,T12,T14,T15 → 分别转 Z3/Q1/Z1/Z1·Server/core）**。
B 项共同成因：各切片做到"受控 fixture+反例"级别，但生产 authority（Q5）、原生装载、secret/generation/instance-generation 三类上游接缝未落，后续被 012/014 波次改挂 seams.md/P-E/集成波次。
疑似真实退化核查结论：`tests/acp_orchestration` 18 红、harness 2 红、server 继承红——均为已登记的基线同因红（known-issues.md:12-13），**非 c0→今日的新退化**；本包 §4 复跑计数与该账一致。
静态不可核档（诚实声明）：/tmp 外置原始日志的存续、wheel 隔离安装现境、前端 build 门——本包未复跑者一律记"未测"，不代 c0 线勾账。

## 9. PE2-8 · qwen 摘除与数据兼容注记

**用户裁定除名；数据兼容：无存量 qwen 用户则零迁移**（016 红线；本包不擅自删数据）。

- 已摘除（注册面与断言面）：`harnesses.toml` qwen 段（8→7 段）、`launch-descriptors.json`（7 条）、`runtime/capability_declarations.json`（7 键）、`adapters/__init__.py` QwenAdapter、`native_materialization.py` qwen 方言聚合（家族表 7 键）、`harness-install-set.py` NPM_ROOTS/构建闭包、`test_core_identity/test_family_dialect_tables/test_capability_declarations/test_single_distribution/launch_descriptors.test.mjs/access_entry_behavior.test.mjs` 全部 qwen 断言；`test_qwen_production_template.py` 以退役说明 docstring 替身（删除文件的操作在本包权限外，登记于此）。
- 显式保留（理由）：`packaging/qwen/`（npm 根）与 `build-qwen-runtime-artifact.mjs`——不删仓内构建输入；`tests/install/test_packaging_boundaries.py` 新增 `RETIRED_NPM_ROOTS = {"qwen"}` 显式记账（映射断言同时禁止 retired 与在册并存）。`adapters/qwen.py`、`src/ordessa_harness/qwen/` 模块保留为注册面外历史件。`runtime/access-launch.mjs:96-97`、`profile_extensions.mjs` qwen profile 为**惰性残留**（描述符路由已无 qwen，`harnesses/index.mjs` 校验闭环不受影响）——随 §10 一并报 core 处置。
- 运行数据兼容疑点（登记，不删）：本机是否存在存量 `.qwen`/qwen 运行数据目录未验证（home 扫描在本包面外）；若存在，属"品牌注册表已除名、数据目录仍在"的孤儿态，按 AGENTS.md 规则 5/7 交维护者裁定。已入 C-PE2-1。

## 10. 转 core / 转父编排清单（本包不代做）

### 10.1 下游 qwen 除名红账（实测，非预测）

命令（cwd=`apps/server`，PYTHONPATH 五段前置本工作树源码，`ordessa_harness.__file__` 实测解析=worktree）：
`/home/maoqh/projects/ordessa/.venv/bin/python -m pytest tests/test_asset_hubs.py tests/test_subagent_harness_round_086.py tests/test_native_materialization_093.py tests/test_native_materialization_093_stage3.py -q`
逐字汇总：`5 failed, 46 passed, 1 warning, 2 errors in 1.69s`（exit 1）。

**qwen 因（2 条，除名的直接下游代价，转 core 同步）**：
- `test_asset_hubs.py::test_the_two_observed_spellings_render_and_unsupported_families_refuse` — `E KeyError: 'qwen'`（:207 `spec("qwen")`→`registry/loader.py:21`；同步建议：`MCP_CREDENTIAL_UNRESOLVED` 反例改挂其他 JSON-slot 家族或删除）。
- `test_subagent_harness_round_086.py::test_the_other_registered_families_declare_no_mcp_target_at_all` — `E AssertionError: assert ['claude-code', 'codex'] == ['claude-code', 'codex', 'qwen']`（:252；同步建议：期望列表去 qwen）。

**非 qwen 因（实测逐字，error 均为缺文件，归 server 继承红账由 core 判定）**：`test_asset_hubs.py` 另 3 红 = `FileNotFoundError: plugins/harness/runtime/worker-entry.mjs`（退役族）；`test_subagent_harness_round_086.py` 2 setup ERROR = `FileNotFoundError: tests/server/fixtures/home_probe_acp_peer.mjs`。本包不复跑主树对照、不代判继承，仅证其与 qwen 无同形因。

**除名不动点（实测仍绿）**：`test_native_materialization_093.py`/`_stage3.py` 的 qwen 反例走 `_FAMILY_DIALECTS.get(...)`/else 分支，qwen 方言表原本即空——摘除不扰动（静态核对+本次计数零红印证）。

### 10.2 stale 文本/惰性数据同步项（非红，转 core 择机清理）
`reasoning_knobs.py:26` 注释；`server-compat/assets/rendering.py:12` docstring；`permissions/adapters/cells.py:104` 品牌列表（其注释"pinned in harnesses.toml"对 qwen 已失真）；`sandbox catalogue.py:13` docstring 与 `test_catalogue.py:48,50`（断言 unpinned→UNKNOWN 仍绿，注释 stale）；`plugins/harness/runtime/access-launch.mjs:96-97`、`runtime/profile_extensions.mjs` qwen profile/model 别名（惰性：描述符路由面已无 qwen）；`harnesses/qwen/launch.mjs`、`src/ordessa_harness/qwen/`、`adapters/qwen.py` 历史件去留裁定。

### 10.3 转父编排
- known-issues 应登记两条（§6 C-PE2-1 授权面外）：①`access_launch_route.test.mjs` G05 继承红（§4 E7–E9 主树复现证据链）；②qwen 运行数据目录孤儿态疑点（§9）。
- c0 甄别 C 档 5 项归属移交（T10→Z3、T11→Q1、T12→Z1、T14→Z1/Server 存储、T15→core 装配），追踪面转 `specs/014-plugin-release/seams.md` 归属条目。
- `tasks.md` PE2 行勾选因写入面限制未代改，本报告 §1 为勾选账，由父编排落盘。
