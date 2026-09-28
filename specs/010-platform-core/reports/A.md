# A — Pacthold

Status: IMPLEMENTATION_REVIEW_READY (A line complete; integration pending review)
Branch: codex/010-platform-pacthold
Base (Source baseline): cd7d31f3cf
Worktree HEAD at T001: 42bf446370 (docs commit on top of baseline; tree clean at start)
Contract checkpoint SHA: 28cf9edd72ee66cc37382e872ae24cb001f86851
Implementation checkpoint SHA: b47b6d78038a7ecabda551b43c18735d32bed012 (A-complete; contract checkpoint 28cf9edd72ee66cc37382e872ae24cb001f86851)

本文件仅 A 会话更新。先记录基线命令/版本/ID，再发布 T004 契约 SHA，最后逐项报告任务/反例/证据与迁移映射。未运行的测试不得填历史数字。

## T001 — 基线冻结（完成）

### 安装环境（现场重跑，非历史记录）

- 独立 venv：`.venv`（本树内，未复用根 .venv）；Python 3.12.14。
- 命令（quickstart Backend setup，全部成功，exit 0）：
  `python3.12 -m venv .venv` → `pip install -r apps/server/lockfiles/server-linux-py312.txt` →
  `pip install -e 'packages/pacthold[dev]' -e packages/server-plugin-api -e 'apps/server[dev]' -e 'plugins/harness[dev]' -e plugins/workspace -e plugins/server-compat -e products/server`
- installed distributions 清单：`packages/pacthold/tests/platform/baselines/t001_installed_dists.txt`
  （pacthold 2.0.0a1 editable、pytest 9.1.1；plugins/runtime-compat 尚不存在，属 T009 产物。）

### 基线测试（pacthold 门，A 线强制项）

- 命令：`.venv/bin/python -m pytest packages/pacthold -q --junitxml=/tmp/ordessa-core-A-baseline-junit.xml`（repo 根目录运行）
- 结果：**238 passed / 0 failed / 0 skipped，exit 0**，verdict 输出 `GREEN_NO_SKIPS`。与 docs/baseline.md 记录的 238 相符（现场验证，非引用）。
- 逐 ID 冻结表（238 行，排序稳定）：`packages/pacthold/tests/platform/baselines/t001_baseline_ids.txt`（sha256 前 16 位 a7c3717c22a1a493）
- junit 原件：`packages/pacthold/tests/platform/baselines/t001_baseline_junit.xml`
- 每文件计数：capability 138、test_work_core_resource_observations 18、test_work_core_input_dispatch 17、test_extensions 14、test_presence_verdict_lnx002 8、test_work_core_repository 8、test_resource_contracts 7、test_work_core_finalization 7、test_brand_rename 5、test_work_core_contracts 5、test_runtime_composition_protocol 4、test_work_core_responsibility 4、test_plugins_cli 3。
- 已知环境性产物缺失登记：worker/sidecar 等二进制 ARTIFACT_*=ABSENT（不入 git，属基线既定状态，不影响 238 全绿）。

### 旧模块 → runtime-compat → 最终领域归属映射（T009 依据）

判定盘点（证据为文件行号，来源为本线只读调研 + 主代理复核）：

| pacthold 现模块 | 判定 | 去向 | 后续领域归属 |
| --- | --- | --- | --- |
| `work_core/db.py` 全局 `_conn/configure_database` | 机制但进程级全局（db.py:11-14；repository.py ~30 处 `db.get_conn()`） | 核心留驻，改实例级 Store | CoreRuntime/Store（中性） |
| `work_core/runtime.py` `AGENT_BOX_HOME`/`agent-box.db` 默认 | 品牌残留 (L7,15-21) | 机制中性化，品牌默认外移 | runtime-compat / Server 产品 |
| `work_core/{models,projection,errors,events,finalization,resource_observations,repository,services}.py` | 中性机制 | 核心留驻 | Core |
| `work_core/registry.py:12,146` import `CONTRACT_TYPES` | 核心→业务反向依赖 ① | 种子 catalog 注入化，契约集外移 | runtime-compat.resource_contracts |
| `resource_contracts/{workspace,prompt_fragment,agent_box_profile,credential,agent_skill}_v1.py` | 业务契约（`agent-box.*` id） | runtime-compat | 各资源域（workspace/prompt/profile/credential/skill） |
| `resource_contracts/{harness_capabilities,home_projection,runtime_artifacts}.py` | 业务域（Harness 能力/guest home/产物摘要） | runtime-compat | Harness/运行时产物域（消费方 harness、server-compat） |
| `resource_contracts/__init__.py` CONTRACT_TYPES 注册表 | 机制+内建业务集合 | 注册机制留核心（C1 contributions），内建集合外移 | runtime-compat |
| `extensions/api.py` harness_managers/continuation_routes/credential_materializers/ProfileEnvelope/AgentBoxPlugin | SDK 混合，业务槽位 | 通用贡献机制入 C1；业务槽位外移 | runtime-compat（Server/Harness 域） |
| `extensions/{loader,catalog,conformance,diagnostics,finalization,bootstrap}.py` | 机制（stage/commit 雏形、贡献 kind） | C1 参考/留驻核心；业务 kind 参数化外移 | Core + runtime-compat kind 数据 |
| `extensions/credentials.py:12` import CredentialRefV1 | 核心→业务反向依赖 ② | 契约 id 注入化 | runtime-compat |
| `extensions/profile_envelope.py` | 业务域（Harness profile 归一） | runtime-compat | Harness/Profile 域 |
| `extensions/capability/`（8 测试 138 ID） | 领域 SDK（能力合同） | runtime-compat | 能力/授权域 |
| `extensions/runtime_composition/`（protocol/coordinator/assembler/fake/sandbox_port） | Root Runtime SDK，`agent-box.*` 契约 id、sandbox 全局 `_REGISTERED_FACTORIES`(L48)+`AGENT_BOX_SANDBOX_MODULE` | runtime-compat | Runtime 组合域 |
| `extensions/sandbox/`（re-export shim） | 过渡兼容 | runtime-compat（禁再增长） | 同上 |
| `storage/database.py` PRODUCT_SCHEMA_VERSION=21 + `server_*` 全表 + `_migrate_*` 链 | 核心内产品 schema | runtime-compat | Server 产品持久域（B 消费） |
| `storage/{objects,secrets}.py` | 中性机制 | 核心留驻 | Core |
| `execution/`（contracts/lifecycle/first_run_lock） | 中性；`_GATE` 进程单例 (first_run_lock.py:109) 需实例化 | 核心留驻+去全局 | Core |
| `cli/__init__.py` web/launch 子命令 | 业务启动器 | runtime-compat/产品 | Workbench Host 域 |
| `migrations/001-003`（profiles/sessions/workflow 业务 SQL） | 业务/legacy | runtime-compat 封存（字节/编号不变） | legacy 域 |
| `migrations/004-009`（core_* 表） | 中性 | 原字节保留于旧迁移集；核心新 schema 独立命名空间 | Core |
| `tests/_editor_mock.py` | 死代码（import 不存在的 `pacthold.edit`，全仓无引用） | 迁移时删除登记（不在 T001 动） | — |

主要外部消费者（import 面盘点，供 B/T022 与迁移表用）：
`pacthold.storage`≈58 处（apps/server、server-compat 全系、workspace、~35 个 server 测试）；
`pacthold.resource_contracts`≈27 处（harness 全 provider、server-compat execution、server 测试）；
`pacthold.work_core`≈56 处（harness、server-compat/sidecar_backend 最重、apps/server bootstrap/测试）；
`pacthold.extensions(.runtime_composition)`≈35+28 处（harness、server-compat、workspace、server 测试）。
A 线跨产品调用破损（B 消费面）在 T009 后于本表按"导入迁移表"发布，由 B 适配闭环（quickstart 规定）。

### 起点验证

- `git log`：HEAD 42bf446370 直接基于 cd7d31f3cf（plan.md 指定起点），工作树开始时 clean。未切换分支。

### 一致性检查（speckit-analyze，A 线范围）结论登记

- CRITICAL=0；A 相关需求覆盖 100%（FR-001/002/003/004/007/011/012/014、SC-001/004/005 的 A 面）。
- 登记两条不阻塞发现（在 T004 实施内消化，不改只读规格）：
  - I1：C1 的 `CoreStore` 类型在 data-model 无定义映射 → T004 将其定义为实例级 Store 中性类型并出具命名映射表。
  - I2：T004 "对应中性模块" 未逐文件指定 DTO 落点 → 契约检查点提交内附 public.py→模块落点表。

## T004 — C1 公共契约检查点（完成）

- 契约 exact SHA（供 B/T015 消费，含且仅含 A 路径 packages/pacthold/**）：
  **28cf9edd72ee66cc37382e872ae24cb001f86851**（父提交 7ac2685835 = T001）。
  B 在本树 merge 该 SHA 前可用 `git show --stat` 验证只含 A 写入范围。
- 交付面：`pacthold.public` 稳定门面（纯 re-export）+ 中性子包 `pacthold/core/`
  （store/registration/runtime/protocols/dtos/plan/enums/descriptors/errors）。
  符号→定义模块落点表写在 public.py docstring（I2 关闭）。
- I1 关闭：`CoreStore` = 实例级 store（自持 sqlite 连接，`__slots__`，零进程全局），
  docstring 注明其替代 work_core/db.py 全局 `_conn` 的语义映射。
- 检查点诚实边界：stage/commit/rollback/unregister/owner_busy/close 为**真实进程内实现**
  （冲突双 owner 拒绝零泄漏、依赖缺引用拒绝、rollback 幂等、已提交批次回滚 typed 拒绝、
  busy 拒 unregister、close 列未解决且 store 关闭异常记入 cleanup_failures）；
  `submit/query/request_stop` 签名冻结、行为 raise `ContractWiringPending`（T007/T008 接线），
  无任何返回假成功的空桩。
- 契约测试：`packages/pacthold/tests/platform/test_public_contract.py`，34 ID、0 skip，
  含签名逐参 inspect 对齐、frozen 反例、三态判别不混同反例、门面 sys.modules 无反向业务引入守卫。
- 门禁复跑（主代理亲自）：`pytest packages/pacthold -q` → 272 passed / 0 failed / 0 skipped
  （基线 238 全保留 missing=0 + 新增 34），独立 python 进程复核边界导入泄漏 = []。

## T007+T008 — US1 核心自然接入（完成）

- T007 先红证据：提交 e2ba767edf（tests/platform/test_us1_* 3 文件 + us1_doubles.py；18 红全部因
  ContractWiringPending 未接线，日志 /tmp/ordessa-core-A-t007-red.log；6 形状守卫当场绿）。
- T008 转绿：`core/dispatch.py` 实例级调度机（schema core_execution/core_operation、request_key UNIQUE、
  先意图后副作用、并发单派发者、UNKNOWN 冻结不重试不 unsafe release、借还不销毁、
  主因+cleanup_failures 双保留、stop ack 不造 cancelled、close 前事实落 store）；
  `work_core/repository.py` 改为可选 store 注入（默认仍走旧全局 db，公开面行为不变，B 消费面无破坏）。
- 主代理亲验：`.venv/bin/python -m pytest packages/pacthold -q` → **296 passed / 0 failed / 0 skipped，
  真实退出码 0**；逐 ID 对照 T001 冻结表 missing=0；新增 58 ID（34 契约 + 24 US1）。
- 夹具修复登记：test_us1_resource_lifecycle.py 缺 `ExecutionState` 导入（属主文件缺陷，1 行 import，
  非降断言）；test_public_contract.py 仅按授权改写
  `test_execution_entries_raise_contract_wiring_pending` 函数体为"真实 typed 拒绝且非占位"断言，ID 不变。
- 契约解释决定（供 T009/T010/B 对齐）：start 操作键 = plan.request_key；acquire 键空间
  `{request_key}#acquire#{slot}`；ContractWiringPending 保留为 deprecated 词汇（反守卫引用）。

## T010 — 生命周期/恢复反例（完成）

- 新 ID 32（test_us1_lifecycle_negatives 14 + test_us1_recovery_negatives 18），主代理亲验：
  `pytest packages/pacthold -q` → 328 passed / 0 failed / 0 skipped，真实 EXIT=0；T001 基线 missing=0。
- 覆盖：终态不可改写（含直接 SQL 伪造 cancelled 行仍不可覆写、摘要探针防瞎断言）、
  Session resume 新 Execution+previous_execution_ref、transport↔execution 不互推、
  close 前未解决事实落 store（重开文件 SQL 比对 ShutdownReport）、重启零 provider 接触、
  unknown 仅凭 reconcile 证据推进、六路 spawn tripwire 反假绿自测。
- src 真缺口补全（最小）：重启 ledger 从 store 重建（store 权威合并）、
  ExecutionPlan.previous_execution_ref、CoreRuntime.reconcile() 证据缝口（只吃 SUCCESS；
  REFUSED/UNKNOWN 零写入；UNSUPPORTED/无句柄 typed 拒）；core_execution/core_operation
  两列 additive ALTER（守卫式，旧库文件可升级）。public.py 仅 docstring 同步，无新导出符号。
- **登记缺口（待主控/集成裁决，未自行扩权）**：FR-004 张力——request_stop 中 provider.stop 抛异常
  （回执未知）后仍执行本轮 OWN lease 释放；该行为被 T007 冻结测试
  test_primary_and_cleanup_exceptions_both_preserved 锁定（其规格来源是本线自己），
  execution 状态轴全程保持 stop_requested、无伪造终态、未解决清单如实，
  但"未知停止回执下释放自有租约"是否违反"unknown 禁不安全释放"需集成评审裁决。
  新测试 test_stop_failure_over_dead_transport_never_fabricates_cancelled 已把现状完整刻画，
  将来修正会显式变红而非静默。

## T009 — 业务域外移 plugins/runtime-compat（完成）

- 结构：新包 plugins/runtime-compat（dist pacthold-runtime-compat，import pacthold_runtime_compat，
  依赖 pacthold；本树 venv 已 -e 安装）。核心 203 ID / compat 163 ID 双门禁全绿（主代理亲验，
  真实 EXIT=0，junit /tmp/ordessa-core-A-t009{v-core,v-compat}.xml）。
- WIP 检查点 683d67f96b（前一执行代理到达轮限，迁移主体已绿但未收尾）；收尾代理完成审计
  7 项验收面 + 38 个守卫 ID（方向 tripwire、SQL 逐文件 sha256 封存 9/9、裸核心 41 模块
  封禁-import 扫描、core_schema_versions 独立命名空间不被旧 MAX 跳过、双路径 7 表结构等价、
  产品装配正反例）。发现并兑现前一代理注释中**虚假声称**存在的双路径等价测试（A.3 GAP→补测）。
- 忠实性：迁移测试逐文件 diff 仅 import 路径变化、零断言删改；328 旧 ID 去向 missing=0
  （178 核心保留 + 150 迁 compat，_editor_mock 死代码删除登记于 T001）。
- B 消费材料（随本提交入库）：plugins/runtime-compat/docs/IMPORT-MIGRATION.md（符号级导入迁移表）、
  TEST-DESTINATIONS.md、BOUNDARY-BREAKS-FOR-B.md（222 条 import 破损 + 9 类行为级破损聚合清单，
  按 C5 由 B/T022 闭环，A 未修）。
- 持久兼容：001-009 原字节/编号封存；旧 schema_versions 不删不重编号；ENTRY_POINT_GROUP 与
  AGENT_BOX_HOME 等字面值未动。work_core/runtime.py 的 AGENT_BOX_HOME 默认仍在核心
  （T001 映射远期项，本任务范围外，登记不擅动）。

## T011 — 裸 wheel 隔离验证 + A 完整 SHA（完成）

- **A 实现完整 SHA（供 B/T022 merge 消费）：b47b6d78038a7ecabda551b43c18735d32bed012**（含 T001–T011 全部 A 路径交付）。
- 真隔离证据（第二个全新 venv /tmp/a-t011-venv，仅 wheel+pytest）：
  installed distributions /tmp/a-t011-installed.txt（无 pacthold-runtime-compat、无 ordessa_*）；
  全模块导入 /tmp/a-t011-imports.txt（pacthold 41/41 OK，且 import compat 必须 ModuleNotFoundError）；
  wheel 由 HEAD 构建 sha256=70dccab0…，pacthold.__file__ 解析 site-packages 非 repo src。
- 裸跑：pytest packages/pacthold → 207 passed / 0 skipped（真实 EXIT=0，/tmp/a-t011-junit.xml）；
  唯一登记排除 1 文件 test_t009_bare_core_imports.py（editable 布局专属 tripwire 在 wheel 布局不可自证，
  首次裸跑该 ID 真红如实保留于报告；其裸语义由 import_scan 证据覆盖；README 登记；.venv 环境该文件 3 passed）。
- SC-001：wheel_check/example_new_provider.py 仅 import pacthold.public+stdlib（AST 自守卫），
  stage/commit/submit/同键重放/request_stop/close 全流程绿（/tmp/a-t011-sc001.txt），git diff src 为空——
  新受控资源+执行 provider 零核心修改接入。
- SC-004（裸环境）：同键重发不二次启动 / unknown 不重试不释放 / restart spawn tripwire 三反例在 venv#2 绿。
- 主代理亲验复跑：仓库门禁 210 passed EXIT=0；裸环境复跑 207 passed EXIT=0。
- 导入迁移表：plugins/runtime-compat/docs/IMPORT-MIGRATION.md（B/T022 逐符号依据），
  测试去向 TEST-DESTINATIONS.md、边界破损登记 BOUNDARY-BREAKS-FOR-B.md 同目录。

## T024（A 部分）— 本线交付报告（完成；T024 行三方共用，勾选留待三线齐）

### 任务覆盖
T001 ✓ T004 ✓ T007 ✓ T008 ✓ T009 ✓ T010 ✓ T011 ✓ T024(A) ✓。
分支 codex/010-platform-pacthold（base cd7d31f3cf，起点 docs 42bf446370 未切换）。
契约 SHA 28cf9edd72…；A 完整 SHA b47b6d7803…（阶段链：7ac2685835→28cf9edd72→88c8c4cb56→
e2ba767edf(先红)→cea2af9b1e(转绿)→4ac08661f0→14cdb563e5→683d67f96b(WIP)→7267bb9ed1→6e7da6af10→
b47b6d7803→报告提交）。

### 最终门禁（主代理 HEAD 复跑，真实退出码）
- G1 `pytest packages/pacthold -q` → 210 passed / 0 failed / 0 skipped，EXIT=0
  （junit /tmp/ordessa-core-A-final-core.xml；quickstart A 强制门 + platform 全量）。
- G2 `pytest plugins/runtime-compat -q` → 163 passed / 0 / 0，EXIT=0
  （/tmp/ordessa-core-A-final-compat.xml）。
- 逐 ID 差分：T001 冻结 238 ID 在 G1∪G2 去向 missing=0（G3 迁移映射另见 T009 节，
  TEST-DESTINATIONS.md）；新增 135 ID（34 契约 + 24 US1 + 32 恢复 + 38 布局守卫 + 4 T011 守卫 + 3 SC-004 裸镜像，
  扣除跨阶段计数重叠后以最终 junit 373 总数为准）。无 skip、无降断言；
  先红证据 /tmp/ordessa-core-A-t007-red.log 与 WIP 红记录（T011 首跑 1 failed）如实保留。
- 隔离安装证据：venv#1（本树 .venv，quickstart 全命令）/venv#2 裸 wheel（/tmp/a-t011-{installed,imports,sc001}.txt，
  wheel sha256=70dccab0…，41/41 模块 OK、业务发行缺席）；裸跑 207 passed EXIT=0。
- 新功能不修改核心证明（SC-001）：wheel_check/example_new_provider.py 仅经 pacthold.public
  接入新资源+执行 provider，git diff src 为空。
- 写入边界审计：cd7d31f3cf..HEAD 中本线触碰仅 packages/pacthold/**（46 文件）、
  plugins/runtime-compat/**（61）、reports/A.md、tasks.md 本行勾选；未碰 apps/、其他插件、根 JS、兄弟树。

### 反例/守卫总账（节选代表）
重复 spawn tripwire（会炸才可信）、伪造终态 SQL 行不可改写、unknown 冻结无证据不推进、
借用在失败回收中零销毁、清理双异常全保留、门面反向 import 植入即红、SQL 篡改/缺失/多余三重钉、
旧 schema_versions MAX 不跳新命名空间、裸库事后装配 fail-closed。

### 未测范围（如实登记）
- 真模型、真用户数据/服务、Windows：本批禁止/未做（基线既定）。
- apps/server / harness / acp_orchestration 套件：B 线门禁；A 完整 SHA 合入后其 222 条 import
  破损由 B/T022 依 IMPORT-MIGRATION.md 闭环（BOUNDARY-BREAKS-FOR-B.md 为登记清单，含 9 类行为级）。
- 真旧产品库（非夹具）的双路径验证在 B/T023 夹具面；A 已证 core_* 结构等价（合成临时库）。
- FR-004 张力项（stop 回执未知仍释放 OWN lease）：见 T010 登记，待集成评审，修正会显式变红。
- test_t009_bare_core_imports 的 tripwire 文件在裸 wheel 布局不可自证（登记排除，语义由 import_scan 覆盖）。
- work_core/runtime.py AGENT_BOX_HOME 默认值仍在核心（T001 远期项，本任务范围外）。

A 线到此停止：待审，不再新增提交（除评审意见）。不合并 main、不推送、不动兄弟树。
