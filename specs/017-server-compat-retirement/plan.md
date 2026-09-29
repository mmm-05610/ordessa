# 017 · plan

## 事实（2026-09-29 实测）

- F1 模块清单（plugins/server-compat/src/ordessa_server_compat/，19 项）：
  accounts、approvals、assets、composition.py、core_wire.py、credential_cli、
  error_families、execution、facade、hooks、http、model_configs、persistence、
  plugin、profiles、sessions、usage_aggregate、wire_projection、wire_validators。
  规模：core_wire 2181 行、composition 1364 行、wire_validators 97 行。
- F2 生产消费面（精确）：products/server `composition.py:127` boot
  `ServerCompatPlugin`；`:183/:197` 用 `build_runtime_from_native_adapter/
  build_runtime_from_sidecar_deployment`；apps/server `wire/handlers.py:14/:22`
  引 core_wire 冻结清单与 wire_validators（docstring 级注明）；
  products/server `pyproject.toml:21` 硬依赖 `pacthold-runtime-compat`——
  更正：`ordessa-server-compat==0.1.0`。
- F3 apps/server 为薄宿主（accounts/sessions 相关 .py 数=0），业务域本体在
  server-compat；92 个测试文件消费 `ordessa_server_compat`。
- F4 退役清单已交：`specs/011-z3-model-provider/retirement-request.md`（W1-W15，
  行号以现行树实测）、`specs/011-z1-profile/retirement-request.md`（R1-R10，
  含 server-compat `server_profiles`=R10）。
- F5 锁序（seams S-08 已钉）：先退 compat writer（同批含边界断言更新）→ core
  S-03 装配 model-provider → 两步之间无双写窗口。
- F6 域归宿现状锚点：approvals 与 permissions 域近缘；sessions 与
  plugins/agent/sessions 的服务端记录面对界待核；execution/usage 与 pacthold
  work_core 的账目面近缘；accounts/assets/http/persistence/facade 归宿待裁。

## 逐域映射提案（W-3 用，待用户裁定总方向后逐格定死）

| 域 | 提案归宿 | 依据 |
| --- | --- | --- |
| approvals | permissions 域（毕业或并审批面） | 与 authority/审批同族 |
| sessions | 对界 plugins/agent/sessions 后定（服务端记录并入或独立） | F6 |
| execution / usage_aggregate | pacthold work_core 账目面方向 | F6 |
| accounts / assets / http / persistence / facade / credential_cli / error_families / wire_projection | **总方向裁定项**：apps/server 收编 vs 插件化分域 | 需用户裁 |
| model_configs / profiles | 死亡（W-1） | F4 |
| core_wire / wire_validators / composition | 迁移（W-2；composition 归宿 A=apps/server 或 B=products/server，推荐 A） | F2 |

## 待裁（用户）

1. **业务域总方向**：apps/server 收编（server 业务归 server 进程）vs 插件化
   分域（继续 011 路线，服务端业务也做成插件）。
2. composition 归宿 A/B。
3. W-1 执行时窗（建议=consolidation 后与 pi S-03 同窗锁定）。

## 时序

设计（本包）→ 用户裁定 → W-1 派单（集成窗）→ W-2 core seam 交接 → W-3 逐域
毕业波 → 目录删除 + closeout。runtime-compat 退役排其后（另包，等迁移窗口裁定）。
