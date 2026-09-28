# Q4 T05（受管域核心）：连接租约 / 唯一 owner / 工具目录 / 关闭-drain 状态机

日期：2026-09-28。线：Q4 `codex/011-q4-mcp` 受管子代理。
基线 HEAD：`02e4175f13`（"Q4 T03: bounded negotiable credential-less probes…"）。
本包只新增文件，零改动既有模块与共享 conftest；无任何 git 写操作。

## 0. 证据级别（先说死）

**本批 = L0/L1 域层。** 没有真实 MCP SDK client，没有 Pi 桥，没有连接过任何
真实 server，一次都没有。`ManagedClientPort` 是注入式 Protocol
（session_manager.py:81），本批仅有的实现是两个显式标注 L0/L1 的内存 fake
（`InMemoryManagedClient` session_manager.py:132、
`FaultInjectingManagedClient` session_manager.py:183）。真实 SDK client 与
Pi 受管扩展属 **G2/G4 依赖批**（`specs/011-q4-mcp/reports/t04-t05-research.md` §8，
integration-request 在案）。任何把本目录测试读成"真实连接已通"的说法都是误读。
测试环境无网络、无真 spawn：包级 autouse 封锁（tests/conftest.py）在本目录
**从不解除**（与 tests/probe 不同，本目录没有任何放开 fixture），并由
`test_environment_guard.py` 3 个 ID 显式钉住。

## 1. 落盘物

| 文件 | 内容 |
| --- | --- |
| `plugins/assets/mcp/backend/managed/lease.py` | 租约实体、状态机转移表、事实账、租约存储（flock+staging+`os.replace`，`<root>/managed/leases.json`，同 definition_store 风格）、native 投影占用 |
| `plugins/assets/mcp/backend/managed/catalog.py` | `McpToolCatalog`、确定性 digest、观察存储（`<root>/managed/catalogs.json`）、漂移/superseded、`make_catalog_provider`（resolve.py 接缝形状） |
| `plugins/assets/mcp/backend/managed/session_manager.py` | `ManagedClientPort`/`PermissionAuthority`/`AuditSink` 端口、两个内存 fake、`ManagedSessionManager`（open/plan/start/observe/approve/call/close/drain/reconcile/unload/inspect） |
| `plugins/assets/mcp/backend/managed/__init__.py` | 受控导出 |
| `plugins/assets/mcp/tests/managed/` | conftest + managed_helpers + 9 个测试文件，51 ID |

关键符号（file:line，均为绝对前缀 `plugins/assets/mcp/`）：

- 状态机表 `LEASE_STATES/ACTIVE_STATES/LEGAL_TRANSITIONS`：lease.py:82-109；`transition()`（每级转移一条独立事实）lease.py:373
- 唯一占用键 `(runtimeGeneration, sessionRef, endpointFingerprint)`：`lease_key` lease.py:147；`_occupancy_conflict`（active→`MCP_OWNER_CONFLICT`，unknown→`MCP_RECONCILE_REQUIRED`，native 占用→`MCP_OWNER_CONFLICT`）lease.py:272
- lane 互斥双向：`create_lease` lease.py:300 / `project_native` lease.py:548
- 不可见性（跨 principal/session 冒领→统一 `MCP_LEASE_MISSING`，不泄露存在性）：`_check_visible` lease.py:364
- `reconcile`（unknown 唯一出路：terminated→closed / alive→connected）：lease.py:463 + session_manager.py:650
- 目录仅可由 connected/catalog-observed lease 的 tools/list 产生：`record_observation` catalog.py:163（store 层再校验 `MCP_CATALOG_UNOBSERVABLE`）+ `observe_catalog` session_manager.py:339
- 漂移失效 + `catalog-changed` 事实：`observe_catalog`（session_manager.py:339 起）；`is_digest_current` catalog.py:231
- 新工具默认不可调用（批准集只可显式冻结、逐项须在当前观察目录内）：`approve_tools` session_manager.py:402、`set_approved_catalog_snapshot` lease.py:420
- call_tool 单门（可见性→owner→状态门→活目录→未批准→陈旧 digest→观察名→Permission→在途登记）：session_manager.py:438
- close 序（停新调用→限时 drain→drain-timeout 清单→一次释放→幂等 replay→cleanup 错不遮蔽）：`close_lease` session_manager.py:544
- 审计 sink 故障落 `cleanup-error` 不吞主错：`_audit` session_manager.py:792
- 无池化：工厂每 lease 必产新 client（session_manager.py:280,314，测试 `production_count` 钉住）

## 2. 需求条款 → 测试 ID（tests/managed/，V05 域内格）

全部路径前缀 `plugins/assets/mcp/tests/managed/`。

| 条款 / 反例 | 测试 ID |
| --- | --- |
| 唯一 active lease per 键；close 后键释放 | test_lease_uniqueness.py::test_second_active_lease_on_same_key_is_refused |
| ownerId 唯一（active 域内） | ::test_owner_id_must_be_unique_among_active_leases |
| native/managed 互斥（双向 `MCP_OWNER_CONFLICT`） | ::test_native_projection_then_managed_lease_is_refused, ::test_managed_lease_then_native_projection_is_refused |
| 占用状态在文件不在内存（新 manager 实例仍拒） | ::test_occupancy_is_file_backed_across_manager_instances |
| 指纹确定性且不含凭据 | ::test_endpoint_fingerprint_is_deterministic_and_secret_free |
| 两会话同 endpoint 各得独立 lease（非池化前提） | ::test_different_sessions_same_endpoint_get_independent_leases |
| 六级事实独立、不折叠成一个布尔（FR-02） | test_state_machine.py::test_full_chain_records_six_independent_facts_not_one_boolean |
| 非法转移类型化拒绝且零副作用 | ::test_illegal_transitions_are_typed_and_change_nothing, ::test_skipping_connected_before_catalog_is_refused, ::test_terminal_states_accept_no_transitions |
| 早期状态 close 不触工厂 | ::test_close_from_early_states_releases_without_a_client |
| 反例 2：跨 principal/session 冒领拒且不泄露（错误文本不含 id/指纹/目录） | test_owner_isolation.py::test_foreign_principal_cannot_see_the_lease_at_all, ::test_same_principal_foreign_session_cannot_read_the_catalog |
| close 只可由 owner、一次生效、幂等可重试、无泄漏（close_count==1） | ::test_close_requires_the_sole_owner_and_leaks_nothing, ::test_owner_close_is_effective_once_and_idempotently_replayable, ::test_call_tool_requires_the_owner_even_for_the_right_principal |
| 反例 7/FR-10：connect 失败结果不可确认→unknown+独立事实；unknown 期间禁第二 lease、禁盲 close、禁乱转移；reconcile(terminated) 后重试得新 client；reconcile(alive) 续用原 lease | test_unknown_reconcile.py::test_connect_failure_parks_lease_in_unknown_with_its_own_fact, ::test_no_second_lease_while_unknown_must_be_reconciled_first, ::test_reconcile_terminated_releases_key_and_retry_gets_fresh_client, ::test_reconcile_alive_continues_the_same_lease_never_a_second, ::test_reconcile_requires_owner_and_only_applies_to_unknown |
| 可确认失败→refused（非 unknown），键即释放 | ::test_start_failure_is_confirmed_refused_and_releases_the_key, test_close_drain.py::test_refused_lease_close_replays_without_a_client |
| drain：停新调用→限时等在途→drain-timeout 清单（只含 tool+argsDigest）→busy 可重试→一次释放 | test_close_drain.py::test_inflight_call_blocks_close_into_busy_then_retry_closes, ::test_close_stops_new_calls_before_the_drain_even_when_idle |
| 活 lease 卸载 busy→close 后放行（反例 9 前半） | ::test_unload_with_active_lease_is_busy_until_owners_close |
| 反例 9 后半：client-close 错→unknown+cleanup_errors 账、不装确认；audit sink 错不遮蔽主错（busy/unknown 仍上抛）且落账 | test_cleanup_errors.py::test_client_close_failure_becomes_unknown_and_is_booked, ::test_audit_sink_failure_never_masks_the_primary_busy_error, ::test_audit_sink_failure_on_successful_close_still_succeeds |
| 目录只源于活连接观察；定义不能伪装 live（无 lease/关后 listTools 拒）；sourceEvidence/leaseId 绑定 | test_catalog.py::test_catalog_store_refuses_observation_over_a_dead_lease, ::test_closed_lease_can_no_longer_produce_observations, ::test_catalog_carries_source_evidence_and_lease_binding, test_close_drain.py::test_definition_never_answers_list_tools_for_anyone |
| digest 确定性（乱序/元数据噪声同值；schema 变则变） | test_catalog.py::test_digest_is_deterministic_across_order_and_metadata_noise |
| 反例 5：漂移使旧 digest 失效、`catalog-changed` 事实、冻结批准整体变陈旧；新工具默认不可调用；批准不能含未观察名；未批准=全拒（批准门先于权限门） | ::test_drift_supersedes_old_digest_books_catalog_changed_and_stales_approval, ::test_no_approval_means_nothing_is_callable |
| resolve.py catalog_provider 接缝形状对齐 + 漂移触发 needs-revalidation（V02 联动） | ::test_catalog_provider_feeds_resolve_needs_revalidation_on_drift |
| 反例 3：双会话同 URL 各独立 client/catalog/凭据修订，close A 不碰 B | test_no_pooling_isolation.py::test_two_sessions_same_url_get_independent_clients_and_catalogs, ::test_clients_are_never_shared_even_when_specs_match; test_lease_uniqueness.py::test_second_active_lease_on_same_key_is_refused（同会话叠加拒） |
| call_tool 必经 lease 状态门 + Permission fail-closed（fake 扩展绕权限不可能） | test_call_gate.py::test_call_before_catalog_observed_is_refused_by_the_state_gate, ::test_no_permission_authority_means_no_call_reaches_the_client, ::test_denying_authority_blocks_before_any_side_effect, ::test_allowing_authority_runs_exactly_through_the_lease, ::test_client_call_fault_becomes_unknown_without_auto_retry |
| 事件/事实不落秘密与参数正文（金丝雀扫盘） | test_audit_no_secrets.py::test_full_lifecycle_leaves_no_secrets_or_bodies, ::test_catalog_digests_are_the_only_tool_payload_stored |
| L0/L1 环境封锁不自破 | test_environment_guard.py 全部 3 ID |

## 3. 真实运行记录（不造绿）

命令（工作树根）：`.venv/bin/python -m pytest plugins/assets/mcp/tests/managed -q`
（Python 3.12.14，pytest 9.1.1；按派单要求全程未跑全目录，共享 gate 由主代理执行）。

- 第 1 跑：`1 error during collection`（测试 import 错置 `MCP_LEASE_MISSING`）→ 修。
- 第 2 跑：**6 failed, 45 passed**（真实红：audit kind 命名不一致、unload 消息缺 id、
  测试文件路径写错、"fail(s) closed" 文本、catalog protocolVersion/serverInfo 来源缺失）。
  逐条修实现/测试（serverInfo 与协商版本改为从 connect 事实读取，不发明）。
- 第 3 跑：**5 failed, 46 passed**；第 4 跑：**1 failed, 50 passed**；
  第 5 跑：**51 passed, exit 0**。
- 稳定性复跑 ×2：`51 passed in 0.40s` / `51 passed in 0.40s`，均 exit 0，收集数 51。
- 无 skip/xfail/删除断言；红色历史如上。

## 4. 错误码登记

复用 `backend/errors.py`（未改）：`MCP_OWNER_CONFLICT`、`MCP_CATALOG_MISSING`、
`MCP_TOOL_NOT_OBSERVED`、`MCP_ASSET_MISSING`、FR-10 词表中的
`CONNECTION_FAILED`/`UNKNOWN_OUTCOME`/`CATALOG_CHANGED`/`PERMISSION_REFUSED`
（本批首次真实抛出，兑现 errors.py "reserved for T03+" 注释）。

本域新增（模块内登记，probe.py 先例；错误串形如 `"{code}: {message}"`）：
`MCP_STATE_TRANSITION_INVALID`、`MCP_LEASE_MISSING`、`MCP_LEASE_BUSY`、
`MCP_RECONCILE_REQUIRED`、`MCP_NOT_CONNECTED`、`MCP_TOOL_NOT_APPROVED`
（以上 lease.py:68-73），`MCP_CATALOG_UNOBSERVABLE`（catalog.py:43），
`MCP_CLIENT_FACTORY_MISSING`（session_manager.py:75）。

## 5. 与设计/legacy 的偏差与已知限制（如实）

1. **`refused` 释放占用键**：设计未规定 refused 的键语义。本实现把 refused 定为
   "资源从未活着的已确认终态"，即刻释放；`unknown` 保持占用（这是反例 7 要的形状）。
   `closing` 超时不释放（等 owner 重试）。
2. **endpointFingerprint 排除全部 headers/env**（连 literal 也排除）：数据模型未逐项
   规定；排除面收窄到 executable+argv / url，凭据维度由 `credentialRevision` 字段承载。
   代价：同 endpoint 不同 header 的"两个 lease"在同一 session 内会被键冲突挡住——
   这正是首版想要的（一键一活连接）。
3. **client 句柄只在 manager 进程内存**：新 manager 实例对旧 active lease 的
   observe/call 得到类型化拒（`_require_client`），close 则跳过 client 调用直接释放
   账（内存模型，L0/L1 单进程）。跨进程接管/查证属 G2/G4 真实 client 批的 reconcile
   面，届时必须重做，不如今日偷跑。
4. **`MCP_TOOL_NOT_OBSERVED` 的 call_tool 分支是纵深防御**：公开路径上
   "已批准但未观察"结构上不可达（批准只发生在冻结时对当前目录的子集，漂移先触发
   `CATALOG_CHANGED`），该分支未测，登记为未测项（同分支在 approve_tools 上已有测试）。
5. **`make_catalog_provider` 按 (definitionId, revision) 暴露最新观察**，不区分会话来源
   （digest+工具名，无正文）——与 T02 注入端语义一致；会话内正文读取一律走
   owner-scoped 的 `list_tools_for_definition`。
6. **审计未接宿主事件总线**：首版注入 `AuditSink` port（默认 None），落宿主事件接口是
   Server 装配批（T09）的接缝，contracts §5 "不另建第二条宿主生命周期" 由此守住。
7. 与本批派单并行面（backend/permissions.py、backend/secret.py、tests/permissions/）
   零交集；`PermissionAuthority` 只是 Protocol 接缝，T06 的权威实现可注入
   `ManagedSessionManager(permission_authority=...)`，缺席时 call_tool fail-closed。

## 6. 未测 / 阻塞（不许被当作已完成）

- 真实 MCP SDK client、Pi extension 桥、双 lane 运行时互斥的**执行级**证据（L2+）：
  G2/G4 依赖批，本批明确不做、也无从做。
- V05 全口径（Pi 两会话经真实 ACP/扩展的隔离与单次关闭）需 T10 生产路径验收，
  本批只交付其域内格。
- 上文偏差 4 的防御分支。
