# 派单 T01 — server 包（`plugins/assets/model-provider/server/**`）

状态：**QUOTA_REFUSED**（2026-09-28，子代理派发 4 次均被环境即时拒绝 "exceed quota limit"——
3 并行 + 1 单发；与旧树 `plugin-model-provider-impl` DELIVERY §5 同一先例）。按检查点协议
「普通阻塞自行解决并继续独立任务」改由 lead 亲自实现，本文件降级为工作单 + 审阅清单；
单包所有权纪律不变（串行实施，一次只动本包）。

## 唯一写入域
`plugins/assets/model-provider/server/**`

## 任务
旧 Python 核心包保真迁移 + 新裁决增量。

### 只读输入
- 旧源 `plugin-model-provider-impl` @ `9305563`：`plugins/model-provider/src/ordessa_model_provider/*.py`、
  `tests/`（77 例）、`pyproject.toml`、`specs/002-model-provider/contracts/{backend-wire,domain-ports}.md`
- oracle：本树 `plugins/server-compat/src/ordessa_server_compat/model_configs/`
- 冻结：本线 `t00-freeze.md` §4/§8、`api-requests.md`
- 设计：`docs/design/model-provider/{spec,contracts,data-model}.md`

### 布局
- `server/pyproject.toml`：dist `ordessa-model-provider`，import 包 `ordessa_model_provider`，src 布局；
  依赖按本树实况（`.venv` 已装 `server_plugin_api`/`ordessa_server` editable）。
- 每个迁移文件头：`# migrated from plugins/model-provider@9305563...`；逻辑增量用普通注释写约束。
- `server/MIGRATION.md`：逐文件来源表 + 增量清单。

### 保真（MP-12）
六方法 id/参数集/错误码/投影字段与 compat 一致；`test_plugin_registration.py` 形状门原样通过；
表 `providerModels`、opaque_id("provider")、CAS、幂等 scope、KEEP/null（omitted=KEEP，显式 null=clear）逐字保留。

### 增量（先红后绿，保留两轮输出）
1. 七个新方法（命名冻结 §8）：`modelProvider.catalogue/saveProviderConfig/probeProvider/inspectChoice/chooseForSession/queryChoice/reconcileChoice`，同插件 id `ordessa.model-provider`。语义=设计 contracts.md Port 签名；chooseForSession 只排队不 applied；queryChoice→desired/lastConfirmed/unknown+revision；reconcile→Confirmed|Refused|Unknown。
2. 新 typed 失败码映射既有 wire error family：`PROVIDER_NOT_FOUND, PROVIDER_ARCHIVED, MODEL_NOT_FOUND, CREDENTIAL_UNRESOLVED, PROTOCOL_UNSUPPORTED, ADAPTER_MISSING, VERSION_UNVERIFIED, SELECTION_UNSUPPORTED, CONFIG_REVISION_CONFLICT, TARGET_STALE, RESUME_UNAVAILABLE, VERIFICATION_MISMATCH, OPERATION_UNKNOWN`；旧码全保留。
3. 目录查询失败 typed error ≠ 空列表（MP-03）。

### 必备测试（先红后绿）
catalogue 失败≠空列表；chooseForSession 排队 pending 零 prompt 副作用；save CAS 冲突→CONFIG_REVISION_CONFLICT
（error.current 带投影）；同 key 不同 payload 拒绝；归档保护（非空→REFERENCE_CONFLICT；端口缺席→
REFERENCE_STATE_UNKNOWN）；secret 哨兵零命中；双 owner DuplicateMethodError（扩到 13 方法）；
依赖边界（不 import Chat/Profile/desktop）。

### 审阅清单（lead 验收门）
- [ ] 六方法形状门绿（旧测试原样）
- [ ] 新方法先红后绿证据齐
- [ ] MIGRATION.md 逐文件来源
- [ ] secret 哨兵 + 归档 fail-closed 反例
- [ ] pytest 全绿命令/退出码记录
