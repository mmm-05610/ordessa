# T09（迁移面）— Q4 侧 legacy→MCP 域数据迁移与查询等价互证

日期：2026-09-28。范围裁定：**compat 删除执行归 C0（integration-request 条目 4），本批只做 Q4 迁移面**——`scan_legacy` / `migrate` / 查询等价互证，全部用真实 DB、真实 store、真实旧件，零假接口；不修改任何既有文件。

对应：`docs/design/mcp/spec.md` FR-12（旧 `server_assets` mcp kind 与 `server_profile_assets` 绑定按 ID/摘要保全迁移，不删未迁移内容，不修改磁盘标识）；`docs/design/mcp/data-model.md`「旧 `server_assets` digest 保持可验证，迁移时…存旧摘要与迁移映射，不无声重算」；`specs/011-q4-mcp/t00-interface-bindings.md` 旧实现盘点 rows/records 行；`reports/t01-t02.md` §V01 诚实声明「DB 侧互证在 T09 报告补」——本报告的 DB 侧互证即该补账。

## 交付符号（file:line）

`plugins/assets/mcp/backend/migration.py`（新文件，仅依赖域件，**不 import compat**；digest 用 `backend/definition.py` 的 legacy 字节保真移植，V01 互证钉死与 `SC/assets/mcp.py definition_digest` 逐字节一致）

- `LEGACY_SERVER_SCOPE`（:56）、`MIGRATION_SOURCE`/`MIGRATION_APPROVER`（:60/:61）、`profile_principal`（:64，`"profile:<id>"` = principal 归 profile scope）、`binding_operation_key`（:70，确定性 CAS 键）
- `snapshot_tree`（:80，sha256 全树快照，回滚安全断言面）
- `_readonly_database`（:101，**旧库经私有临时副本只读**：SQLite WAL 只读打开也会动目录，复制使「legacy 字节不变」成为结构性保证而非尽力而为；AGENTS 规则 7——本函数由操作者指向真实数据根，测试永不指真实根）
- `_asset_rows`/`_binding_rows`（:131/:139，`kind='mcp'` 行 + 与 `AssetRecords.bindings` 同款 JOIN）
- `_revision_entries`/`_classify_asset`（:161/:193，逐 revision 文件 `definition_digest(read)` 对 `digest` 列核对；列只证明 `latest_revision`，其余标 `unattested` 不诬报；不一致→`digest-mismatch` 单列，如实报、不修）
- `scan_legacy`（:246）、`migrate`（:315）、`assignment_equivalence`（:545）、`verify_migrated_digests`（:607）

`migrate` 语义：每 (asset_id,revision) 文件**字节原样**复制到 `<target_root>/mcp/<id>/<rev>/server.json`（同相对路径，经 store staging+rename 写入，不重序列化），再 `adopt_legacy_revision` 按**旧摘要**登记（`canonical_shape="legacy"`、`migration.legacy_digest` 在案、零重算零改写）；绑定→`McpAssignment`：enabled→`decision=enable`+`approvedRevision=绑定 revision`+`toolSelection=allObserved(names=[], catalogDigest=旧视图 digest)`+先落 `approve_revision(actor=legacy-migration)` 批准记录（旧绑定即批准证据）；enabled=0→`decision=disable`（新模型 disable 是遮盖、不携修订——revision/digest 如实标 `masked`，**绝不冒领成 enable**）。幂等（重跑 changed=0、目标树 sha 不变）；`dry_run` 产完整 diff 计划、目标根零创建；`target_root == assets_root` 直接 ValueError。

`plugins/assets/mcp/tests/migration/legacy_sample.py`：合成样本生成器全用旧件真实路径——`pacthold_runtime_compat.storage.Database`（迁移链至当前版，`server_assets`/`server_profile_assets` 即 12→13 DDL）+ `AssetRecords.publish/bind` + `McpAssetStore.install`；stdio（`fs-local`，含 rev2 使旧绑定指向非 latest——legacy 视图原貌）/ env-credentialRef（`env-ref-srv`）/ remote-https（`remote-weather`）各≥1；两 Profile、enabled/disabled 绑定齐。`settle()`（:54）见下文红账 R3。反例构造器：`build_dangling_binding_dataset`（:143）、`build_digest_mismatch_dataset`（:153）。

## 查询等价映射表（FR-12，钉于 test_equivalence.py）

对同一 legacy DB、每 Profile：左列 = 真实 `AssetRecords.bindings(profile_id)` 输出字段，右列 = 迁移后新 store 视图。

| legacy 字段 | 迁移后视图 | 规则（测试钉） |
| --- | --- | --- |
| `assetId` | `McpAssignment.definition_id` | 值相等 |
| `kind`（'mcp'） | `McpDefinition` 存在且未归档（scope=legacy） | 等值推导 |
| `name` | `McpDefinition.native_name`（源自修订文件 canonical.name） | 值相等 |
| `revision` | `approvedRevision`（enabled） | 值相等；disabled → `masked`（模型语义，显式标注不假装相等） |
| `digest` | `toolSelection.catalogDigest`（allObserved） | 值相等；disabled → `masked` |
| `enabled` | `decision ∈ {enable,disable}` | 布尔相等 |

行数核对：两 Profile 共 5 绑定 = 5 映射行（`test_equivalence_covers_every_binding_row_of_both_profiles`）。字节侧另钉：`verify_revision_digest` 对 binding.revision==latest_revision 者为 True；`fs-local`（绑定@1、列摘要@2）为 **False 且测试如实钉 False**——这是旧 JOIN 视图的原貌（digest 列只证明 latest），迁移不悄悄纠正，scan 以 `unattested` 如实报。

## 真实运行账（不造绿）

环境 `.venv`（python 3.12.14），命令 `.venv/bin/python -m pytest …`，退出码用 PIPESTATUS 独立测。

- **R1 首轮**：`tests/migration` **4 failed / 15 passed，退出码 1**。红因如实：①②④测试自身错（`McpRevision.shape` 实为 `canonical_shape`；`skip-asset` 整 dict 相等断言漏 `reason` 键；dangling 断言误设 p-alpha 无健康绑定）；③实现缺陷（latest 修订条目状态未升级为 `attested`/`digest-mismatch`）。修复后 19/19。
- **R2 我引入的包级干扰（真红，已修）**：`tests/migration/helpers.py` 与既有 `tests/probe/helpers.py` 在 pytest 扁平模块名下撞名——全包跑 `plugins/assets/mcp` 时 `tests/probe/conftest.py:25 from helpers import FAKE_SERVER` 撞进我的文件，**collection 整体中断**。目录内跑不出这个红，全量跑才暴露。修复：更名 `legacy_sample.py`，清陈旧 `__pycache__`。
- **R3 冻结测试真红×5 连发（根因在样本侧非迁移侧，如实记账）**：`test_legacy_side_is_byte_frozen…` 一度稳定红——`pacthold Database.initialize()` 用 `with sqlite3.connect(...) as conn` **不显式关闭**，该连接被 GC 回收的时机随机，届时 SQLite 做收尾 checkpoint：**重写主 DB 文件并删 -wal/-shm**。快照撞上这个 GC 时机就红。用一次性脚本逐步定位（dry True / real False / after-gc 文件集收敛）证实为样本构建器自身 churn，与迁移无关（迁移只读私有副本）。修复：`settle()`（`gc.collect()`）在建样本后静默，再快照。复测：**5 连跑 19 passed（每次 0 红）**。
- **反空转变异探针（3 枚，逐枚恢复）**：P1 旁路 digest-mismatch 拒adopt → `test_digest_mismatch_asset_is_refused_and_never_adopted` 红；P2 旁路 dangling 拒绝 → `test_dangling_binding_is_refused_without_fabricated_content` 红；P3 旁路目标目录冲突不覆盖 → `test_conflicting_target_revision…` 红（且穿透到 `definition_store.py:281 MCP_REVISION_EXISTS`，证明不覆盖由真实存储层二次兜底）。恢复后 `grep PROBE|MUTATION|if False` 零命中，套件回绿。
- **最终数字**：`tests/migration` **19 collected / 19 passed / 0 failed，退出码 0**（稳定复跑）；整包 `plugins/assets/mcp` **345 passed / 0 failed，退出码 0**（19.8s，含 probe/managed/permissions/service/permission_adapter/managed_client 等并行批次已交付测试，确认本批零回归；本批只新增文件，未动任何既有文件）。

## C0 删除清单核对（integration-request 条目 4 逐项）

| 条目 4 分项 | 归属 | 迁移面状态 |
| --- | --- | --- |
| `SC/assets/mcp.py`/`mcp_probe.py`/`rendering.py` MCP 写入路径删减 | C0 执行 | ✅ 前置完备：`migration.py` 不 import SC 任何符号（backend 依赖纯度保持，pyproject `dependencies=[]` 不破）；样本生成只在 tmp 用旧件建库。删除不再断任何 Q4 路径 |
| `core_wire.py` `assets.publishMcp`/`assets.probe` 注册与 `_COMPAT_METHODS` 冻结表对应项 | C0 执行 | ✅ Q4 面零调用；`mcp.*` 描述符（t09-service）独立成面 |
| `composition.py:995-1166` MCP 段（**保留同段 subagent bridge 勿随删**） | C0 执行 | ✅ 替代消费面就绪：绑定视图 = assignment（等价表钉），装配删段不丢查询语义 |
| `server_assets` mcp kind 写入方 | C0 执行 | ✅ 数据保全达成：全行可 scan、digest 可核对、adopt 幂等、legacy 侧字节冻结断言（R3 修复后） |
| 「数据保全：行经 `adopt_legacy_revision` 按旧摘要迁移；迁移脚本归属 T09 后续提交」 | Q4 | ✅ **本批即该后续提交**：脚本+互证+报告齐；compat 对 mcp kind「只减不增」自此可执行 |

## 未测项 / 边界（如实）

- **真实用户数据根迁移不在本轮**：全部合成样本走 `tmp_path`，绝不指真实 run-data（AGENTS 规则 7）；对真实库执行 `migrate` 属 C0 切换窗口操作。
- 回滚演练（切根后真实回退旧 server）未测——本轮只证 legacy 侧不被触碰 + target_root 独立性。
- `credentialRef` 指向的凭据行有效性迁移后校验属 T07 secret 缝，不在本面（引用按 data-model 原样保留，零改写）。
- 非 mcp kind（skill/command/plugin 绑定）不扫不迁（越域）。
- 迁移工具的 wire/host 编排（谁在何时调 `migrate`）属装配窗口（条目 1/6，C0），本批交付纯函数面。
