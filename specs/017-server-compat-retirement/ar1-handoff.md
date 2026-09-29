# AR-1 断言交接清单（W-1 同批；回复 core 2026-09-29 的索要）

W-1 我们拆的范围（server-compat 目录内两件）：`model_configs` writer（W1-W15 的
server-compat 部分）＋ `server_profiles` writer（R10）。harness 侧的 profile 旧
writer（R1-R6）不在 W-1，归后续波次（届时 harness 断言随那批走，见文末）。

## core 侧（apps/server，随 W-1 同批改）

| # | 文件:行 | 现断言 | W-1 后新期望 |
| --- | --- | --- | --- |
| 1 | `apps/server/tests/test_server_compat_boundary.py:35-36,159,196,223` | providerModels 六方法属 compat 面；`ordessa_server.model_configs` leaf 白名单 | 断言红→删/改：新 owner=model-provider adapters 的等价 13 方法声明；不删则边界门把新 owner 拦在门外 |
| 2 | 兼容回归四件：`test_provenance_wire_098.py`、`test_union_semantics_126.py`、`test_provider_compatibility_092.py`、`test_config_describe_slots_125.py` | 语义冻结（provenance/CAS/形状） | 由新 owner 等价测试接账（`test_next_choice_wire.py`/`test_plugin_registration.py`），逐条核对归同窗；本行为其入口清单 |
| 3 | `apps/server/src/ordessa_server/wire/handlers.py:14` | docstring 引 core_wire 冻结清单 | 文档性引用，随 W1/W2 删除自然失效，host 代码零改动 |
| 4 | R10 受影响套件：`test_stage_a_server.py`、`test_posture_config_write.py`、`test_execution_inventory.py`、`test_delegation_*` 等 | 读/写 `server_profiles` 表的既有账 | 随 R10 执行逐套核对：迁新 owner（profile-api）或退役；表格式与 id 不变（规则 5） |

## plugin 侧（我们，同批自改，无需 core 动手）

- W-1 本体：server-compat 两 writer 拆除 + 其兼容回归退役（断言删除逐条留名）。
- 后续 harness 波次（非 W-1）：R5 摘 `harness-profile-store` entrypoint 时同波改
  `plugins/harness/tests/test_core_boundaries.py:15-16` 集合断言；R6 同波改
  PA-5 矩阵测试 face import（断言形状不变）。

## 已随本回复完成的另外三件

① `codex/plugin-connector-acp` @ `5abd6e684d`：7 处测试 import + 2 处注释路径
归位（目标路径随 core 落 main 生效，验证归同窗）；③ 根治包见
`specs/019-controlled-peer-decouple/`（内容摘要锁 + 装配注入端口，harness
access-entry 白名单解耦路径依赖）。
