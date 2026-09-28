# MIGRATION — `plugins/assets/model-provider/server`

来源树：`/home/maoqh/projects/ordessa/worktrees/plugin-model-provider-impl`
分支 `feature/plugin-model-provider-impl` @ `9305563719d25e04076b9221a7284660bd8f8642`（clean，只读）。
每个迁移文件首行带 `# migrated from ...` 头；下表为差分核对结论（2026-09-28 实测，
`diff <(tail -n +2 新文件) 旧文件`）。

## 逐文件来源表

| 新文件 | 旧文件 | 保真性 |
| --- | --- | --- |
| `src/ordessa_model_provider/__init__.py` | 同名 | 逐字（0 diff） |
| `src/ordessa_model_provider/records.py` | 同名 | 逐字（0 diff） |
| `src/ordessa_model_provider/protocols.py` | 同名 | 逐字（0 diff） |
| `src/ordessa_model_provider/probe.py` | 同名 | 逐字（0 diff） |
| `src/ordessa_model_provider/catalog.py` | 同名 | 逐字（0 diff） |
| `src/ordessa_model_provider/next_turn.py` | 同名 | 逐字（0 diff） |
| `src/ordessa_model_provider/ports.py` | 同名 | 逐字（0 diff） |
| `src/ordessa_model_provider/testing.py` | 同名 | 逐字（0 diff） |
| `tests/conftest.py` + 10 个迁移测试 | 同名 | 逐字（0 diff） |
| `tests/test_plugin_registration.py` | 同名 | **一处规格驱动修改**（下述） |
| `src/ordessa_model_provider/plugin.py` | 同名 | 迁移体 + Z3 增量（下述） |
| `src/ordessa_model_provider/choices.py` | — | 本线新写 |
| `tests/test_next_choice_wire.py` | — | 本线新写 |

## test_plugin_registration.py 的唯一修改（规格驱动，非掩饰）

`assert len(host.methods) == 6 + 0` → `== 6 + 7`，附注释指向 `t00-freeze.md` §8。
原因：设计 contracts.md 明确授权新版本化方法，t00 冻结新增七个 `modelProvider.*` 方法；
旧六行形状断言原样保留并通过。修改先红（新方法缺席时新测试先红）后绿，非删断言。

## plugin.py 增量

1. ctor 新增 `harness_config_port`（C2 消费视图注入点；缺席→unknown/unknown-outcome，永不 ready）。
2. `_METHODS` 追加七行 `modelProvider.*`（命名冻结 t00-freeze §8），宿主端口名与 legacy 六个一致。
3. `_Handlers` 增加七个 handler；`provided_ports` 增加 `model_provider.choices`。
4. 新增 import：`choices`（CONFIG_REVISION_CONFLICT/PROVIDER_ARCHIVED/PROVIDER_NOT_FOUND/ModelChoiceService）。

## choices.py 语义要点

- 目录查询失败 → `OPERATION_UNKNOWN`（typed，绝不空列表，MP-03）。
- `chooseForSession` 只排队（outcome=pending-next-turn，apply 计数为零）；unsupported/端口缺席
  拒绝 `SELECTION_UNSUPPORTED`；显式 `expectedOverlayRevision` 而无 overlay 端口 →
  `REFERENCE_STATE_UNKNOWN`（fail-closed）；同 operationKey 不同 payload → `IDEMPOTENCY_CONFLICT`（宿主码）。
- `saveProviderConfig`：CAS 冲突映射为 `CONFIG_REVISION_CONFLICT`（error.current 带当前投影）。
- `probeProvider`：先 CAS（stale→conflict）、archived→`PROVIDER_ARCHIVED`、无 endpoint fact→
  `PROFILE_CONFIGURATION_INVALID`；探测走 legacy 有界单次栈（含 secret 仅调用内解析）；结果不写记录。
- `reconcileChoice`：端口缺席→`unknown-outcome/ADAPTER_MISSING`；read-back 匹配→confirmed；
  不匹配→refused/`VERIFICATION_MISMATCH`；无索引→`unknown-outcome/OPERATION_UNKNOWN`；绝不重发。
- 冻结失败码常量全表在 choices.py 头注（含 submit-gate 侧码：VERSION_UNVERIFIED/TARGET_STALE 等）。

## 验证（2026-09-28，从仓库根）

- 先红：`pytest plugins/assets/model-provider/server/tests/test_next_choice_wire.py`
  → `15 failed, 2 errors`（实现前）。
- 后绿：`.venv/bin/python -m pytest plugins/assets/model-provider/server -q`
  → **87 passed**（70 迁移 + 17 新增），退出码 0。

## 限制与待接线（不冒充完成）

- `modelProvider.*` 新码到 wire family 的映射未注册（host `_BY_CODE` 属 C0）：现走
  `details.internalCode` 精确码 + 暂映射 UNAVAILABLE family；已登记 api-requests.md REQ-Z3-7。
- overlay 端口注入点存在但生产实现属 Z1（REQ-Z3-3）；submit permit 生产闸门属 C0（REQ-Z3-2）；
  `resolve_next_turn` 为闸门预留入口，wire 不暴露。
- pending/confirmed 状态为进程内；持久化属会话域集成（integration-request.md）。

## foundation@8844c475bc 消费适配（2026-09-28，固定 SHA merge 后）

foundation 将产品 Database facade 迁至 `plugins/runtime-compat`（010 FR-011）、参数形状助手迁至
`server_plugin_api.wire_shape` + `ordessa_server_compat.wire_validators`（T014-S2c，宿主
handlers.py 文档字符串指定）。本包最小机械适配（先红 2 collection errors + 2 boundary 红，后绿 137）：

1. `tests/conftest.py`、profile-contribution `tests/conftest.py`：`Database` 改自
   `pacthold_runtime_compat.storage`；`ObjectStore` 仍自 `pacthold.storage`。
2. `src/ordessa_model_provider/records.py`：类型注解改宿主结构化端口 `ordessa_server.storage_port.DatabasePort`。
3. `src/ordessa_model_provider/plugin.py`：五个形状助手按宿主文档改新位置
   （`wire_shape.bounded/request_id/version` + `wire_validators.assignments/models`）。
4. `tests/test_dependency_boundary.py`：`ALLOWED_ORDENSSA_SERVER_LEAVES` 增 `storage_port`；
   compat 封禁增白名单叶 `wire_validators`（宿主指定的共享词汇，非 legacy 业务线）——规格驱动修改，
   非掩饰（失败原因即上述基础包搬迁）。
5. 环境：venv 增装 `plugins/runtime-compat` 与 `plugins/server-compat`（`--no-deps`，仅取校验器模块）。

MP-12 复证：以 AST 提取现行 compat `_PARAM_SHAPES` 与本包六方法形状逐项比对 → **全部一致**。
