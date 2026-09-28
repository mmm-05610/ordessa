# T06-wiring 实现报告 — Q5 permissions-api 生产接线进 Q4 fail-closed 双门

日期：2026-09-28。执行线：Q4 `codex/011-q4-mcp`，工作树 `/home/maoqh/projects/ordessa/worktrees/011-q4-mcp`。
环境（钉死）：`/home/maoqh/projects/ordessa/worktrees/011-q4-mcp/.venv/bin/python` = Python 3.12.14；
`ordessa-permissions-api` / `ordessa-permissions-backend` 均以 `-e` 装于该 venv（实测 import 路径指向本树
`plugins/permissions/{api,backend}/src/...`）。

定性：**L1（真实 Q5 backend + 真实 pacthold Database，throwaway tmp 目录；零网络、零 spawn、零模型）**。
不是 L2：生产 `tools/call` 转发链（managed client / Harness 提交闸门）尚未组装，见「生产剩余」。

## 消费 SHA

| 项 | 值 |
| --- | --- |
| permissions-api checkpoint publication SHA | `bcd4387bec`（`docs(Q5): publish the permissions-api checkpoint with a controlled real call`） |
| implementation SHA | `a98048216c`（git cat-file 验证为 commit 对象；祖先关系由消费 merge 建立） |
| Q4 消费 merge commit | `8f9f3051e2fb79ce3d000130c8e958bb85d051e1`（本批起点 = 该 HEAD） |
| proof 脚本受控复跑 | `.venv/bin/python specs/011-q5-safety/proof/permissions_api_proof.py` → **exit 1**：part_a（纯 API）5/5 PASS；part_b 在 `import support` 处 `ImportError: cannot import name 'Database' from 'pacthold.storage'` — **既有红**（T009 迁移遗留，见差异表 D6），非本批引入，本批未改任何既有文件 |

## 交付面（全部新文件；零既有文件改动）

`git status --short`（本批新增，排除 `__pycache__`）：

```
?? plugins/assets/mcp/backend/permission_adapter.py
?? plugins/assets/mcp/tests/permission_adapter/
```

`backend/permissions.py`、`service.py`、`plugin.py`、`managed/*`、`resolve.py`、`errors.py` 与 Z1/Z2/C0/Q5 文件一律未动。

## 实现符号清单（file:line）

`plugins/assets/mcp/backend/permission_adapter.py`
- 拒绝类别常量（:76-79）：`CATEGORY_DENIED|PENDING|EXPIRED|UNKNOWN`（dispatch 要求的 denied/pending/expired/unknown 分类）
- `normalize_args_digest`（:85）：Q4 `definition_digest` 的 `sha256:<hex64>` 拼写 → Q5 `ArgumentDigest` 裸 hex64；不合法形状在触 Q5 前拒
- `Q5RequestBinding`（:100）：Q5 `OperationRequest` 必填信任字段（serverInstanceId/nativeSessionId/executionId/nativeGeneration/nativeRequestId/target）的组合期载体
- `Q5AuthorizerPort`（:119）：注入的裁定服务端口（结构上即 `ordessa_permissions_backend.Authorizer.evaluate`；本模块不 import backend 内部，守插件边界）
- `_CATEGORY_BY_CODE`（:138）+ `_category_for_code`（:150）：Q5 稳定码 → Q4 类别映射（`PolicyDenyCode.POLICY_DENY`/`RefusalCode.POLICY_CEILING_VIOLATION`→denied；`APPROVAL_STALE`/`APPROVAL_NOT_ACTIONABLE`→expired；`POLICY_ADAPTER_MISSING`/`POLICY_SCOPE_UNVERIFIED`/`PERMISSION_UNKNOWN_TOOL`/`APPROVAL_RESULT_UNKNOWN`→unknown；未读出的码→unknown）
- `Q5PermissionAuthority`（:173）：实现 `backend/permissions.PermissionAuthority` Protocol（`isinstance` runtime-check 过测）；`authorize_tool_call`（:210）digest 形状先验→`_rule`（:241，binding/ceiling-pin/`ArgumentDigest` 组装，任何 raise 收进 `_Q5Unavailable`）→`_project`（:307，`q5.AllowedOnce`→allowed（expires 取真实 `BoundGrant.expires_at`）、`q5.PendingApproval`→`pending-approval`（绝不因无人值守升 allowed）、`q5.Denied`→refused+类别、union 之外→refused unknown）
- `_Q5Unavailable`（:343）：内部 fail-closed 载体，永不外抛成调用方异常
- `q5_policy_denied_definition_ids`（:360）：resolve.py `policy_denied` 钩子供给函数 — 真实 `intersect_ceilings` 的 hard-deny + `TOOL_EXPOSURE` vs `maximum_exposure` 导出；空/不可信/不可 intersect 的 ceiling 集 → 全拒；`AdminAuthorization` **不是输入**（Q5 rules.py：授权书只能解 intent 内部优先级，永不扩 ceiling）

`plugins/assets/mcp/tests/permission_adapter/`
- `conftest.py`：sys.path 注入 Q5 lane support（:29-30）；T009 `Database` 路径别注（:31-40，进程内绑定真实 `pacthold_runtime_compat.storage.Database`，零 mock）；autouse socket/subprocess 封锁（:57）；`MutableClock`（:70）；`RecordingAuthorizer`（:83，**真实 `q5_backend.Authorizer` 子类**，super() 真跑后留档每次 (inputs, outcome)）；`Q5World`（:142，真实 Database+ApprovalFacts+PolicyRepository+admin ceiling）
- `test_q5_authority_adapter.py`（18 测试）、`test_policy_denied_provider.py`（5 测试）

## 差异表（Q4 Protocol ↔ Q5 真实 API 的语义差与显式薄适配）

| # | 差异 | 薄适配（全部在 permission_adapter.py 内聚） |
| --- | --- | --- |
| D1 | argsDigest 算法拼写：Q4 侧 `managed/session_manager.py:489` 用 `definition_digest`（`sha256:` 前缀 + hex64）；Q5 `ArgumentDigest` 只收裸 64 位小写 hex | `normalize_args_digest` 去前缀 + 形状校验；不合法 → `PERMISSION_ARGS_DIGEST_REQUIRED` 拒在 Q5 之前（测试证明零咨询、且前缀/裸 hex 同一 operation_digest） |
| D2 | revision 概念名：Q4 参数 `policy_revision` 是 MCP 平面标签；Q5 的 `policyRevision`/`ceilingRevision` 是**承重 pin**，由 `build/intersect` 从在场对象**派生**（不可手填） | 适配器用注入的 `ceiling_provider`/`intent_provider`（组合时与 Authorizer 读同一对象）计算 pin；调用方传入的 `policy_revision` 只回显进 `ToolCallDecision`，永不作 pin。若 Authorizer 内部读到不同对象，Q5 自身 `POLICY_CEILING_VIOLATION` 拒 — 漂移 fail-closed |
| D3 | 工具词汇表：Q5 `rules.TOOL_KEYS` 封闭（read/edit/bash/task/external_directory/webfetch/skill）；MCP 工具名任意 | `tool_key_provider` 显式映射；未映射名以原名透传，由 **Q5 自己** 拒 `PERMISSION_UNKNOWN_TOOL`（unknown 类）— 适配器永不发明映射放宽 |
| D4 | 归属字段宽度：Q5 `OperationRequest` 必填 8+ 信任字段；Q4 缝只给 principal/session_ref/lease_id | `binding_provider(session_ref, lease_id, tool_name, args_digest) -> Q5RequestBinding|None`；None/缺字段 → unknown 拒，触 Q5 前 fail-closed（测试 `test_unattributable_call_refused_before_the_authority`） |
| D5 | Q4 树内有**两个** PermissionAuthority 形状：`backend/permissions.py:139`（→`ToolCallDecision`，本批目标）与 `backend/managed/session_manager.py:106`（→`bool`）。二者不互换 | 适配器只实现 permissions.py 的 Protocol（`isinstance` 过测）。建议主代理后续小改点：session_manager 的 bool 缝接到 `check_tool_callable`（decision.status != refused→bool），或收敛为一；本批未动该文件 |
| D6 | Q5 lane 的 `tests/support.py:19` 仍 `from pacthold.storage import Database`；T009 后该类迁至 `pacthold_runtime_compat.storage`（`packages/pacthold/storage/__init__` docstring 明示）——Q5 proof part_b 与 `plugins/permissions/backend/tests`（9 collection errors）在本树本就红 | 本批 conftest 在 `import support` 前把**真实出厂类**绑定到旧路径（进程内，零文件改动）。属导入路径适配非语义 mock；建议主代理路由给 Q5 lane 修 support 一行 |
| D7 | 决策 TTL：Q5 `DECISION_TTL`/`GRANT_TTL` 均 5min；Q4 `ToolCallDecision.expires_at` 是 epoch float | allowed 决策 `expires_at = grant.expires_at.timestamp()`（断言 `== NOW + GRANT_TTL`，引用真实 `q5.GRANT_TTL` 常量） |
| D8 | 稳定码词汇：Q5 用 `RefusalCode`/`PolicyDenyCode` enum；Q4 refusal 要 code 字符串 | 不新增 Q4 code（errors.py/permissions.py 登记面不动）：`code=PERMISSION_REFUSED`，Q5 稳定码 `.value` + 类别 + evidence_ref 全入 reason 文本，审计以 `decision_id` 引用 |

## 真实退出码 / 收集数 / 红账（本轮实测，非 tail 状态）

| 目标 | 命令 | 结果 |
| --- | --- | --- |
| 本批目录 | `.venv/bin/python -m pytest plugins/assets/mcp/tests/permission_adapter -q`（repo root） | **23 collected / 23 passed / EXIT=0**（0.23s；无 skip/xfail；每测试均含真实断言） |
| 本包全量 | `.venv/bin/python -m pytest plugins/assets/mcp -q` | **246 passed / EXIT=0**（13.69s）— 新模块零既有测试扰动 |
| apps/server 对照 | `.venv/bin/python -m pytest apps/server/tests -q` | 42 failed / 1092 passed / 10 skipped / 25 errors（EXIT=1）。唯一 mcp 名匹配红为 server-compat 渲染测试 `test_a_bound_mcp_asset_is_rendered_and_materialised_without_writeback`，不 import 本批文件；数字与 checkpoint-consumption 账 foundation 消费轮「67 红 ID 全 inherited」一致，**per-ID 对照未做**（主代理职责，勿当已验证引用） |
| Q5 proof | `.venv/bin/python specs/011-q5-safety/proof/permissions_api_proof.py` | **EXIT=1**（part_a 5/5 PASS；part_b `ImportError`＝D6 既有红） |
| Q5 backend 套件 | `.venv/bin/python -m pytest plugins/permissions/backend/tests -q` | **EXIT=1**，9 collection errors（同 D6，既有红，未归因于本批） |

## V06 覆盖矩阵（格子 → 测试 ID；L=层级）

| 格子 | 测试 ID | 层级 |
| --- | --- | --- |
| allow 授权 → Q4 门放行到可调用判定（真实 Authorizer/DB） | test_q5_authority_adapter.py::test_q5_allow_flows_through_the_double_gate_as_allowed | L1 |
| allow 授权直接过适配器（basis=authority、grant 真实 `BoundGrant`/`GRANT_TTL`/op digest 比对） | 同上（inputs/grant 断言） | L1 |
| digest 拼写两式同操作（D1） | ::test_bare_and_prefixed_digests_are_the_same_operation | L1 |
| catalog 门在前，Q5 零咨询（拒绝先于副作用） | ::test_catalog_gate_refusal_never_consults_q5 | L1 |
| digest 形状非法拒在 Q5 前 | ::test_unusable_args_digest_refused_before_the_authority | L1 |
| 不可归属调用拒且零咨询（D4） | ::test_unattributable_call_refused_before_the_authority | L1 |
| deny（intent 规则）→ refused[denied]（断言 `q5.Denied`/`PolicyDenyCode.POLICY_DENY`） | ::test_intent_deny_maps_to_refused_denied | L1 |
| admin ceiling deny 压过 profile/intent allow（`POLICY_CEILING_VIOLATION`；intersect 断言） | ::test_admin_ceiling_deny_beats_an_intent_allow | L1 |
| 合法 `AdminAuthorization` 也永不放宽 ceiling deny（非对称对照：无 ceiling 时同票 allowed） | ::test_valid_admin_authorization_never_widens_a_ceiling_deny | L1 |
| pending（`q5.PendingApproval` + 真实 DB open 行 + `approval_id_for` 精确匹配）→ refused-with-pending | ::test_q5_pending_approval_maps_to_refused_pending | L1 |
| 过期：一次性 grant 花后 `APPROVAL_STALE`→[expired]（consumed 真查库） | ::test_approved_grant_allows_once_then_expired | L1 |
| 过期：时钟越过 `GRANT_TTL` →[expired] | ::test_grant_past_its_expiry_is_expired_not_allow | L1 |
| 跨 principal 授权不可复用（user-2 只得到自己的 pending；user-1 grant 未耗） | ::test_cross_principal_cannot_spend_another_users_approval | L1 |
| 跨 session 授权不可复用（同上，session-2/turn-2） | ::test_cross_session_cannot_spend_another_sessions_approval | L1 |
| Q5 服务抛错 → fail-closed（真实 store 被 DROP TABLE，异常穿真实 Authorizer；经双门） | ::test_q5_service_raising_fails_closed_through_the_double_gate | L1 |
| ceiling provider 缺席 / 空 ceiling 集（`POLICY_ADAPTER_MISSING` 语义）→ 拒 | ::test_missing_ceiling_provider_refuses_without_consulting、::test_empty_ceiling_set_refuses_as_adapter_missing | L1 |
| 端口形状（`isinstance(adapter, PermissionAuthority)` runtime-check） | ::test_the_adapter_satisfies_the_q4_consumer_port | L1 |
| provider：ceiling deny + exposure cap + 词表外 → 拒集；非承重项不误伤 | test_policy_denied_provider.py::test_provider_denies_ceiling_blocked_and_exposure_capped | L1 |
| provider：无 ceiling / 不可信 ceiling → 全拒（非对称：可信 ceiling 只拒点名项） | ::test_missing_or_untrusted_ceilings_denies_everything | L1 |
| provider：`AdminAuthorization` 永不清洗拒集 | ::test_admin_authorization_can_never_purge_a_denied_id | L1 |
| **admin ceiling deny 覆盖 profile enable（resolve 层拒绝）** + 拒后双门 catalog 零咨询 | ::test_q5_ceiling_deny_blocks_the_profile_enable_in_resolution（真实 `McpDefinitionStore`/`McpAssignmentStore`/`resolve_preview`） | L1 |
| native lane unproven 仍在真 authority 前拒 | ::test_untrusted_snapshot_lane_still_refuses_before_q5 | L1 |

未覆盖（诚实登记）：真实 `tools/call` 端到端（需 T05 真 SDK client + Harness 提交闸门，L2）；`mcp.*` wire 面上 authority 的组合注入（plugin/service 归主代理组装批）；Q5 原生 receipt 的 ACP 真实对账（G2/C0 缝）。

## 生产剩余（不遮蔽）

1. **组合**：`McpDomainService`/`ManagedSessionManager` 的构造还不接收本适配器（service 无 authority 注入口、managed 侧是 D5 的 bool 缝）；真实组装需要：lease→`Q5RequestBinding` 归属源（execution/nativeGeneration/nativeRequestId 由 harness 侧给出，G2 harness-api）、`tool_key_provider` 的品牌映射表、PolicyRepository 的宿主 DB 接线。
2. **提交闸门**：真实 tools/call 转发依赖 harness-api（G2）与 T05 SDK client；本批只交付「裁定与双门」的接线件与受控证明。
3. **建议主代理后续小改点**（本批禁改既有文件，全部内聚在适配层解决，未阻塞）：
   - D5：session_manager bool 缝与 permissions.py decision 缝收敛（一个 5 行 adapter 或改注入口）；
   - D6：路由 Q5 lane 修 `plugins/permissions/backend/tests/support.py` 的 Database 导入路径（其 proof part_b 与 backend 套件在本树当前红）；
   - `checkpoint-consumption.md` 的 permissions-api 行仍是「未发布」旧账，消费 merge `8f9f3051e2` 后应由主代理回填（本批禁改该文件）。
