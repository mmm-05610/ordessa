# Q4 T10 集成报告 — 服务层跨域整合受控链（产品装配前的最大可证链）

日期：2026-09-29。线：`codex/011-q4-mcp`，工作树 `/home/maoqh/projects/ordessa/worktrees/011-q4-mcp`，起点 HEAD `472fc05319`。
交付：`plugins/assets/mcp/tests/integration/**`（新目录：`conftest.py` + `integration_helpers.py` + 2 个自带 loopback fake + 7 个测试文件），以及**一处最小实现修复**（见 §四 缺陷账）。

定性：**L2 跨域整合链**（全部真实件 + 受控 loopback fake MCP 服务 + 标注 fake harness runtime）。
这不是 L3：产品装配（`default_plugins()`、宿主注入 principal、真实装载面）不在本链，见 §五 与 `report.md §二`。

## 一、链路图（符号级）

```
ordessa_server.plugin_host.ServerPluginHost(+MethodRegistry, data_root, host_ports)
  └─ activate(McpAssetServerPlugin) -> ServerPluginRegistration
       ├─ provided_ports{"asset.mcp.v2"} = backend.service.McpDomainService
       │    ├─ backend.definition_store.McpDefinitionStore   （真实落盘 <root>/mcp/<id>/<rev>/server.json）
       │    ├─ backend.assignment.McpAssignmentStore        （真实 CAS/冻结 selection）
       │    ├─ backend.managed.lease.McpLeaseStore / catalog.McpToolCatalogStore（真实 JSON 表+flock）
       │    └─ backend.managed.session_manager.ManagedSessionManager
       │         client_factory = [测试装配] integration_helpers.TransportRouter
       │           ├─ stdio  -> client_stdio.make_stdio_client_factory / StdioManagedClient（真实限定替代）
       │           └─ remote -> client_http.make_http_client_factory / HttpManagedClient（真实限定替代）
       │         permission_authority = backend.permission_adapter.Q5PermissionAuthority
       │           -> ordessa_permissions_backend.Authorizer(RecordingAuthorizer 子类真实 super().evaluate)
       │              over support.seeded_database(pacthold Database) + ApprovalFacts + PolicyRepository
       │              + admin ceiling（t06-wiring 用法）  【经 backend.permissions.check_tool_callable 双门】
       └─ 12 个 ServerMethodDescriptor（mcp.*）
            ↑ 全部经 ordessa_server.wire.handlers.WireService.dispatch 驱动
              （shape 墙 / requestId 墙 / error-family 解析 = 生产同件）

submission 腿（planForSubmission）:
  McpDomainService.plan_for_submission
    ├─ _preview_model -> backend.resolve.resolve_preview(catalog_provider=make_catalog_provider(真实 McpToolCatalogStore))
    ├─ _freeze_credentials -> backend.secret.host_credential_port(真实 HostCredentialPort) + resolve_for_launch
    ├─ native_planner = adapters.claude.compile(snapshot, instance_target, DictProvenance,
    │            revision_provider=McpDefinitionStore.read_revision)  【真实品牌 compile】
    └─ backend.native_binding.{facet_payload_of, desired_fragment, application_target}
         -> ordessa_harness.application.ConfigurationApplicationService.plan   【真实 C4】
              carrier = ServerPluginHost + HarnessContributionRegistry
                       + AdapterContributionPlugin(claude configuration_adapter)
              journal = ordessa_harness.application.OperationJournal(sqlite)
              runtime = [标注 fake] ControlledRuntime（tests/harness_wiring 先例，零进程零网络）

MCP 对端 = 受控 loopback fake（自带，不 import 既有 fixture 内部）：
  integration_fake_stdio_server.py（pid/request/call 见证账本；normal/drift/mismatch/slowcall）
  integration_fake_http_server.py（connections/sessions_issued/requests(含 Authorization)/calls 账本）
```

## 二、证据格矩阵（ID → 测试 → 断言要点）

| ID | 测试 | 格 | 等级 |
| --- | --- | --- | --- |
| T10-INT-01 | test_integration_chain_stdio.py::test_chain_activation_to_tool_call | 全链：12 descriptors 注册 → saveRevision/approve（真实 store 落盘+批准人归属）→ StdioManagedClient 对 fake 建 lease/observe（服务端账本 initialize+initialized+tools/list）→ wire assign 冻结于**真实 catalog 摘要** → wire resolvePreview（allowedToolNames/digest）→ approve_tools → **真实 Q5 权威（intent allow，AllowedOnce 真件判定）**下 tools/call（服务端 calls==1，Q5 consultations==1）→ wire inspectConnection 见 tool-call-executed fact → wire listTools → close → 子进程死（os.kill 探活）→ close 后 listTools 类型化 NOT_FOUND/MCP_CATALOG_MISSING | L2 |
| T10-INT-02a | …refusals.py::test_unapproved_tool_refuses_before_authority_and_server | 未批准工具：MCP_TOOL_NOT_APPROVED；**服务端 calls==0 且真实 Q5 consultations==0**（门序 witness 双侧） | L2 |
| T10-INT-02b | …::test_missing_authority_fails_closed_with_zero_side_effects | 权威缺席：PERMISSION_AUTHORITY_ABSENT fail-closed（G3），calls==0 | L2 |
| T10-INT-02c | …::test_expired_grant_real_q5_once_then_refused | 过期授权走完整真实回路：pending 拒（0 副作用，真实 Q5 落 pending 行）→ 真实 `facts.decide(allow)+record_native_receipt` → 执行一次（calls==1）→ 单次 grant 花尽 → `[expired]`/APPROVAL_STALE 拒，**服务端 calls 仍==1**、DB `grant_fields.consumed is True` | L1/L2 |
| T10-INT-02d | …::test_catalog_drift_stales_the_approval_then_recovers | 目录漂移：re-observe → CATALOG_CHANGED 拒且**零新副作用**（calls 仍 1）；未观察工具再批准拒 MCP_TOOL_NOT_OBSERVED；对新摘要重批准恢复；wire resolvePreview `needsRevalidation==[def]` | L2 |
| T10-INT-03 | test_integration_dual_session.py::test_dual_session_independent_leases_and_close | 双会话：同定义两 session 两条 lease（同 pid 文件两 child 见证，无池化）；session 作用域 assignment 两份**不同 toolSelection**（resolvePreview 分别 ["echo"]/["peek"]）；lease 批准子集各不同；B 冒领 A 的 lease：inspect/close 均 MCP_LEASE_MISSING，A 状态无损；A close 只收 A 的进程，B 仍可调用；**卸载反例**：B 活 lease 在时 request_unload → MCP_LEASE_BUSY（manifest 含 B leaseId），B 关闭后 allowed | L2 |
| T10-INT-04a | test_integration_close_drain.py::test_clean_close_idempotent_and_reaps | close 单次生效+幂等 replay；进程死；wire listTools 翻回 NOT_FOUND | L2 |
| T10-INT-04b | …::test_drain_timeout_busy_then_retry_closes | drain：真 in-flight call（服务端已记账后 sleep）→ close_lease(drain_timeout=0.2) → MCP_LEASE_BUSY + 状态 parking `closing` + 新调用 MCP_NOT_CONNECTED；调用完成后重试 close → closed，calls==1，进程回收 | L2 |
| T10-INT-04c | …::test_unknown_outcome_blocks_retry_until_reconcile | unknown-reconcile：真 StdioManagedClient 遇 mismatch 版本 → UNKNOWN_OUTCOME、lease `unknown`；同 key 再 open → MCP_RECONCILE_REQUIRED；close 亦拒；reconcile(terminated) → closed 放键；新 lease 起得来；mismatch 子进程被客户端自收 | L2 |
| T10-INT-05 | test_integration_six_states.py::test_six_level_ladder_is_distinguishable_from_the_wire | 六态事实格：defined→selected→planned→connecting→connected→catalog-observed→closed 每级 wire inspectConnection 的 `levels` 事实各一（`to` 字段逐步增长），listTools 在 connected 仍 NOT_FOUND、仅 catalog-observed 放行、close 后翻回——每级从 wire 响应面可区分；transient connecting 由**纯委派观察 wrapper**（不加门不替代）在真实握手进行中采样 | L2 |
| T10-INT-06a | test_integration_chain_http.py::test_http_chain_and_rotation_zero_side_effect | HTTP 链：remote 定义（Authorization=secretRef）→ 真 HttpManagedClient 对 loopback fake（服务端 sessions/requests/calls 账本 + Authorization 头 witness=哨兵）→ assign/批准/Q5 真权威 → call；**轮换凭据格**：HostCredentialPort 内容摘要移动 → 下一次 call 在 `_request_headers→resolve_for_launch` PLAN_STALE 拒，**服务端 requests 数零增长、calls 不变**（拒在写任何字节前）；close 事实 remoteServiceLifecycle=="not-owned"；重开 lease = 第二个服务端 session（无池化）；哨兵不出现在 facts 序列化面 | L1/L2 |
| T10-INT-06b | …::test_http_secretref_without_plan_fails_closed | SecretRef 无 plan 对：客户端生产即 SECRET_UNRESOLVED（fail-closed G7），服务端零请求；lease 记 **refused**（缺陷修复格，见 §四） | L2 |
| T10-INT-07a | test_integration_plan_submission.py::test_plan_submission_happy_path_with_chain_double | submission 链（标注 ChainProbe 双件，proven_routes 不翻转）：真 resolve_preview（native 条目+managed 排除各一，均来自真 store/lease 观察）→ 真品牌 compile 出完整集 facet payload → **真 ConfigurationApplicationService.plan**（真 carrier/registry/merge + 真 sqlite journal）→ submission.kind=="plan"、beforeRevision=="base-1"、snapshotDigest==wire resolvePreview 同一摘要、journal 文件在场；**零 apply**：activate_count==0、permits.calls==0 | L2(装配 L1) |
| T10-INT-07b | …::test_plan_submission_brand_honesty_refuses | 真品牌件（无双件）：assess unknown → 真服务 effect 前拒 → wire CAPABILITY_UNSUPPORTED/MCP_GATE_CAPABILITY_UNSUPPORTED；generations 目录空、permits 0（不虚报绿） | L2 |
| T10-INT-07c/d/e/f | …::test_plan_submission_requires_the_permit / requires_the_expected_revision / revision_drift_is_a_cas_conflict / second_submission_gate_refuses | 无 permit → FORBIDDEN/SUBMISSION_PERMIT_REQUIRED（零效果）；无 expectedRevision → INVALID_REQUEST（零效果）；漂移 → CONFLICT_VERSION/MCP_CAS_CONFLICT（真 C4 stale-plan，零效果）；placeholder 闸门 + 真 C4 端口同组 → CONFLICT_REQUEST/SUBMISSION_GATE_AMBIGUOUS（一道闸门，contracts §1） | L2 |

未派生假绿：所有拒绝格都断言**服务端自有账本**零增长（非客户端自述）；Q5 侧断言真实 outcome 类型（`AllowedOnce`/`PendingApproval`）与 consultations 计数；变异审计见 §四。

## 三、门（真实退出码/收集数，本轮实测，非 tail 状态）

| 目标 | 命令（repo root） | 结果 |
| --- | --- | --- |
| 本批目录 | `.venv/bin/python -m pytest plugins/assets/mcp/tests/integration -q` | **18 collected / 18 passed / EXIT=0**（3.15–3.30s，全套 <120s 达标；无 skip/xfail） |
| 全目录（终轮，含修复与 conftest 定稿） | `.venv/bin/python -m pytest plugins/assets/mcp -q` | **508 passed / EXIT=0**（39.6s）|
| 起点基线（本批前同树实测） | 同上 | 490 passed / EXIT=0 → 新增 18 全为本批，**既有零扰动（508-490==18）** |
| 环境 | `.venv/bin/python`（Python 3.12.14；`ordessa_server/ordessa_harness*/ordessa_permissions_*/pacthold*` 均装于该 venv，import 实测指向本树） | — |

进程纪律：本目录无外网（stdio 管道 + `127.0.0.1:0`）；autouse `chain_process_cleanup` 兜底收割 witness 记账的全部子进程；stdio 客户端自持 killpg 收群（T10-INT-04 断言 pid 探活）。

## 四、缺陷/修复账（本批唯一实现改动）

`plugins/assets/mcp/backend/managed/session_manager.py::ManagedSessionManager.start_connection`

- **缺陷（由 T10-INT-06b 暴露）**：方法 docstring 与模块文档承诺「A factory fault or a start() error before the client was adopted is a confirmed ``refused``」，但原实现把 `client = self.client_factory(lease)` 放在 try **之外**——工厂抛错（如真 `make_http_client_factory` 对 SecretRef 头无 plan 对在构造期抛 `SECRET_UNRESOLVED`）时异常直接穿透，lease 滞留 `connecting`：不记 refused、无 audit、无证据，与该状态「尚未有客户端存活」的事实登记语义矛盾（connecting→refused 本是合法迁移表内边）。
- **修复（最小）**：工厂调用纳入确认失败路径——transition 到 `refused`（evidence `{phase: factory, error: <类型名>}`）+ `lease-refused` audit；域内 `McpError` 保持原类型化码穿透，非域错误投影 `CONNECTION_FAILED`（与 start() 失败同形）。零其他改动。
- **修复前行为（变异审计实锤）**：临时还原原代码跑 T10-INT-06b → **红**（断言到 `connecting` 而非 `refused`），EXIT=1；恢复修复后 → 绿。
- **修复后回归**：integration 18/18 EXIT=0；全目录 **508 passed EXIT=0**（含 tests/managed 51 例、tests/managed_client/managed_http——`tests/managed_http/test_http_roundtrip.py::test_stdio_lease_is_a_typed_refusal_for_the_http_factory` 同路径工厂抛错仅断言错误码不变，绿）。

## 五、剩余（不遮蔽）

1. **产品装配格（本测试不覆盖，见 report.md §二 1）**：`default_plugins()` 挂载、extensions.json 登记、宿主注入认证 principal（integration-request 7：本链 principal 仍是 caller-claimed 的域内隔离值）、`credentials`/`secret_store` 端口的真实宿主装配（本链用标注 host-layer 双件 + 真 HostCredentialPort）。装配前最大可证链即本文。
2. **真实装载格（report.md §二 2、§三）**：codex/claude 真 CLI L3 格（本机零命中）、Pi 正式 runtime 装载与信任批准（G9）、L4 真实外部 MCP 服务/真实用户凭据/真实数据根迁移——均未跑，不虚报。
3. **mcp.probe 的 wire+真 transport+probe_authority 组合格**：probe 传输自身 L2 已有（t03 49 例）；本链未接 `permission.probe_authority` 端口（provider 缺席即类型化拒，tests/service 已证），组合格随装配落地。
4. **C4 apply/reconcile 之后的链**：submission 腿证到 plan 为止（本域不 launch，contracts §1）；apply 侧真机格随 harness runtime/品牌 CLI（report.md §二 1(c) C4 slice 差集在案）。
5. **前端渲染/真实 Server 传输往返**：未跑（§三 在案；本链是进程内 WireService.dispatch，非 HTTP 传输层）。

## 六、写入面账（git status 复核）

新增：`plugins/assets/mcp/tests/integration/{conftest.py, integration_helpers.py, integration_fake_stdio_server.py, integration_fake_http_server.py, test_integration_chain_stdio.py, test_integration_chain_http.py, test_integration_refusals.py, test_integration_plan_submission.py, test_integration_dual_session.py, test_integration_close_drain.py, test_integration_six_states.py}`
修改：`plugins/assets/mcp/backend/managed/session_manager.py`（§四 最小修复），本报告。
零他线/产品面文件改动；无 git 写操作。
