# Z1 R0 盘点（冻结于 2026-09-28）

## 起点
- 树 `011-z1-profile`，分支 `codex/011-z1-profile`，起点 HEAD `96fef2db47`（干净）。
- 本树 `.venv`（Python 3.12.14）：pacthold 2.0.0a1 editable、pytest 已装。node_modules 未装（TS 阶段再装，仅本树）。

## 旧实现基线（b77f9f23cb，只读）
- 包 `plugins/profile`（`ordessa-profile` 2.0.0a1，模块 `ordessa_profile`），28 个文件。
- 模块：core(208)/errors(39)/facets(147)/ids(18)/migration(84)/plugin(35)/profiles(332)/repository(226)/resolution(173)/sensitive(64)/sessions(581)/storage(150) 行。
- **实测基线：70 passed**（/tmp/old-profile-baseline 隔离检出，本树 venv，pacthold 用本树 editable）。
- v1 语义要点：ProfileService（create/get/list/rename/archive/clone/save-revision CAS idempotency）、
  SessionService（open/select/apply-switch/set-overlay/clear-overlay/session-config/turns/verify_recovery）、
  FacetRegistry（重复 facetId 拒绝、卸载幂等）、Resolution（逐 item 合并、provider absent 不遮盖）。
- v1 缺口（v2 必须补）：session_id 单字段（非 canonical SessionRef）、无 MechanismPolicy、
  无 journal/receipt/operationKey、`_prove_application` 用 DB readback 冒充运行证明（v2 拆分为
  storage 证据与 Harness 运行证据）、无 item schema/sensitivity/effect、无 compile/reset intent、
  无名称唯一规则（NFC+trim+casefold）、无第三方 provider proof、plugin.build 返回空注册。

## 依赖检查点状态（R0 时点）
- foundation / harness-api / chat-api：**均未发布**（无 ready 分支、checkpoints 目录空）。
  C0 树有未提交在制文件（plugins/harness/api/ 等），按协议不读不消费。
- Z1 先发 profile-api（本线职责）；其余按检查点协议消费。

## 本线包格局（按 profile-v2 plan.md §1）
- Python：`plugins/profile/src/ordessa_profile/`（保留既有路径），新增 policy、application_journal、contracts 公共面。
- TS：`plugins/profile/api/`（轻量贡献契约，先发）；`plugins/profile/frontend/`、`integrations/chat/`（后续阶段）。
- 测试：`plugins/profile/tests/`（Python）、各 TS 包自带。

## Harness 旧 profile-store（plugins/harness/generic/profile_store.py 等）
v1 时代 harness 内文件式 profile 存储与 harness-profile-store entrypoint。v2 唯一 owner 是本包；
列 integration-request.md 由 C0 集成时裁决退出，本线不改 plugins/harness。

## 环境命令（已验证）
- `.venv/bin/pip install -e packages/pacthold` → import OK
- 旧包隔离跑：`.venv/bin/python -m pytest /tmp/old-profile-baseline/plugins/profile/tests -q` → 70 passed
