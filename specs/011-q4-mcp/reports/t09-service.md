# T09（Q4 侧）— MCP 服务/wire 层：service + ServerPlugin 注册件

范围：`plugins/assets/mcp/backend/service.py`（`McpDomainService`，contracts.md §1
操作的服务面）与 `plugins/assets/mcp/backend/plugin.py`（`ordessa.asset.mcp`
ServerPlugin：`mcp.*` typed method descriptors、provided port、error-family
contribution）。**产品装配与 server-compat 删除归 C0，本报告不含**；未修改任何
既有文件（`git status --porcelain` 本 lane 只有 `??` 新文件：`backend/service.py`、
`backend/plugin.py`、`tests/service/`）。

行号基于本工作树收工时（`plugins/assets/mcp/` 下）。

## 1. 符号表（file:line）

### backend/service.py
| 符号 | 位置 |
| --- | --- |
| `APPLICATION_PORT_ABSENT`（本模块注册的端口缺席码） | service.py:64 |
| `ProbeAuthority`（probe 权限消费端口） | service.py:67 |
| `SubmissionGate`（Harness C4/C5 提交闸门消费端口） | service.py:77 |
| `definition_view` / `revision_view` / `assignment_view` / `snapshot_view` / `catalog_view`（camelCase 版本摘要投影） | service.py:91 / :102 / :116 / :133 / :168 |
| `_result_assignment_view` / `_require_principal` | service.py:185 / :195 |
| `McpDomainService`（构造装配 definition/assignment/lease/catalog 存储 + `ManagedSessionManager`，凭据口缺省=fail-closed 适配器） | service.py:201（`__init__` :204） |
| `load`（start hook 的存储装载） | service.py:230 |
| `list_definitions` / `get_definition` / `save_revision` / `approve_revision` / `archive` | service.py:244 / :250 / :263 / :281 / :293 |
| `probe`（先权限后读取后传输；无凭据、不发 catalog 断言） | service.py:301 |
| `assign` / `unassign`（observed catalog 只取服务端 catalog store，绝不接受调用方注入） | service.py:331 / :357 |
| `_preview_model` / `resolve_preview` | service.py:372 / :386 |
| `_caller` / `inspect_connection` / `list_tools` | service.py:404 / :409 / :417 |
| `plan_for_submission`（闸门→快照→凭据批量绑定/复验→闸门，整批 fail-closed） | service.py:431 |

### backend/plugin.py
| 符号 | 位置 |
| --- | --- |
| `PLUGIN_ID = "ordessa.asset.mcp"` | plugin.py:73 |
| `_PARAM_SHAPES`（12 个 `mcp.*` 的 required/optional 精确形状） | plugin.py:79 |
| `_mcp_refusal`（SC `_asset_refusal` 风格，MCP 码；family 经组合注入的 resolver） | plugin.py:129 |
| `MCP_ERROR_FAMILIES`（`wire.error-families` 贡献表，46 行；与 static 表、workspace/compat 已发表行逐码比对零重叠） | plugin.py:163 |
| `McpAssetServerPlugin`（descriptor/build/`_dispose`） | plugin.py:219（descriptor :239，build :246） |
| 12 个 handler 闭包（mcp_list … mcp_plan_for_submission） | plugin.py:271–:398 |
| `_guard`（McpError→WireError 映射墙；WireError 直通） | plugin.py:400 |
| `probe_availability` / `submission_availability` | plugin.py:410 / :417 |
| `load_stores` start hook（`context.data_root/"assets"` 下装载三个存储） | plugin.py:448 |
| `_preview_params`（resolvePreview/planForSubmission 共享可选目标参数） | plugin.py:474 |

provided port：`asset.mcp.v2` → `McpDomainService`（plugin.py:246 起 build 内注册）。
消费端口：host 门面 `credentials` + `secret_store`（合成 `host_credential_port`，
plugin.py build 内；任一缺席 → 解析即 `SECRET_UNRESOLVED`，G7 约定）、
`wire.error_family_resolver`；插件端口 `permission.probe_authority`、
`harness.submission_gate`（均无 in-tree provider，缺席=类型化拒绝）。
descriptor 无 `requires`：本插件只消费 host 门面（对全部插件可见）与可选端口，
端口缺席在调用时处理，不在激活图上声明依赖。

## 2. 方法 × availability

availability 只回答 hello 问题、从不 gate dispatch（contract.py:52-55，order 097）；
受限方法的拒绝发生在 handler 内，为类型化 WireError。

| method id | availability | 理由 |
| --- | --- | --- |
| `mcp.list` `mcp.get` `mcp.saveRevision` `mcp.approveRevision` `mcp.archive` `mcp.assign` `mcp.unassign` `mcp.resolvePreview` `mcp.inspectConnection` `mcp.listTools` | `None`（supported） | 全部由本域自有存储支撑，生产可用；`listTools/inspectConnection` 的"活连接"事实缺失时按域语义类型化拒绝（`MCP_CATALOG_MISSING`/`MCP_LEASE_MISSING`），不是能力缺席 |
| `mcp.probe` | 谓词：authority 缺席 → `(False, "PROBE_AUTHORITY_UNWIRED")`；注入后 `(True, None)` | §1 probe 行要求"明确 probe 权限"；Q5 Permission 未合入 → hello 诚实报 unsupported，dispatch 拒绝 `PERMISSION_AUTHORITY_ABSENT`（UNAVAILABLE），probe 传输绝不先运行 |
| `mcp.planForSubmission` | 谓词：gate 缺席 → `(False, "MCP_SUBMISSION_GATE_UNWIRED")`；注入后 `(True, None)` | §1 行 6 与 Harness C4/C5 共用唯一提交闸门；无 provider → 注册但 planned/受限，handler 拒 `APPLICATION_PORT_ABSENT`（CAPABILITY_UNSUPPORTED），不产 fake 成功 |

错误→wire 映射：域码保留 `"{CODE}: {message}"` 文本 + `details.internalCode`；
family 由组合的 `wire.error_family_resolver`（本插件贡献的 `MCP_ERROR_FAMILIES`
进入该 aggregate）回答，未注册码走文档 fall-through UNAVAILABLE；非域异常只带
类型名，原始文本进 log（与 `_asset_refusal` 同纪律）。响应键名全 camelCase
（legacy `asset_view` 习惯）。

## 3. 受控 proof（真实 host 件）

命令（工作树根）与真实结果：

```
$ .venv/bin/python -m pytest plugins/assets/mcp/tests/service -q
..............................                                           [100%]
30 passed in 0.11s
EXIT=0
```

按文件：registration 8、definition roundtrip 6、probe 5、assign/resolve 6、
port-absence 5（collect-only 核对 30）。无 skip/xfail。

回归对照（同回合实测）：
- `pytest plugins/assets/mcp/tests -q` → **223 passed**（原 193 + 新 30；
  helpers 更名 `service_helpers.py` 消除了与 `tests/probe/helpers.py` 的
  模块名冲突）；
- `pytest apps/server/tests/test_plugin_host_gate.py -q` → **49 passed,
  VERDICT=GREEN_NO_SKIPS**，exit 0（host 未被触碰）。

proof 组成的关键点：
- `tests/service/service_helpers.py:Stack` 直接构造真实
  `ordessa_server.plugin_host.ServerPluginHost`/`MethodRegistry`（host.py 测试
  先例）+ 真实 `WireService.dispatch/hello`（形状墙、requestId 墙、family
  fall-through 全部走产线路径）；宿主文件零修改。
- 激活校验：owner≠descriptor.id 的仿冒注册被 `InvalidDeclarationError` 拒绝且
  整轮回滚（test_registration.py）；deactivate 后 12 行全部消失、
  `provided_port` 归 None、dispatch 报 "not a wire/1 method"。
- roundtrip：save→list→get→approve→archive 全走 dispatch；CAS 冲突
  `CONFLICT_VERSION/MCP_CAS_CONFLICT`、operationKey 重放与冲突、外 scope
  `MCP_ASSET_MISSING`（不泄露存在性）逐族核。
- probe 双路：无 authority → UNAVAILABLE `PERMISSION_AUTHORITY_ABSENT` 且
  fake 传输计数为 0；有 authority+fake runner → graded facts（`credentialScope:
  "unproven"`、doesNotProve 含 tool-catalog）；denied → FORBIDDEN；
  `PROBE_TIMEOUT` → UNAVAILABLE retryable。
- assign→resolvePreview→listTools/inspectConnection→unassign：live catalog 由
  域自带 in-memory fake client（L0/L1 标注件）经真实 `ManagedSessionManager`
  开出；selection 绑 digest、未观测工具拒 `MCP_TOOL_NOT_OBSERVED`、漂移拒
  `MCP_CATALOG_MISSING`、行 CAS、跨 principal `MCP_OWNER_CONFLICT`、archived
  阻断新 assign 均在 dispatch 层核。
- 端口缺席反例：无 gate → `APPLICATION_PORT_ABSENT`；有 fake gate、无凭据门面
  → `SECRET_UNRESOLVED` 且 gate 未被触达（`gate.planned == []`）；门面齐 →
  经 gate 完成且响应只含 slot/credentialId/revisions，明文不出现。
- client_factory 缺省（生产今日形态）：`start_connection` 拒
  `MCP_CLIENT_FACTORY_MISSING`，lease 落 `refused`（无假连接）。
- 包根 conftest 的 socket/Popen 封锁在本 suite 全程有效：wire 调用若偷偷 spawn
  即红。

## 4. principal / 请求上下文缺口（供 integration-request）

**精确描述**：wire/1 宿主没有任何请求级 principal 注入面。证据：
- `WireService.dispatch(method, params)` → `descriptor.handler(params)`：handler
  只收 params Mapping（apps/server/src/ordessa_server/wire/handlers.py:161-175）；
  `ServerMethodDescriptor.handler` 签名即 `Callable[[Mapping], Any]`
  （packages/server-plugin-api/.../contract.py:73）。
- `apps/server/src/ordessa_server/wire/` 与 `plugin_host/` 全目录 grep
  `principal` 零命中；传输层认证只有 hello 报告的 `session_token` bearer
  （连接级），到 handler 无调用者身份。

**本层处置（不造假）**：服务与 handler 的 auth 输入显式化 —— 12 个方法全部把
`principal` 声明为 required 参数，`McpDomainService` 每个操作以显式
`principal=` 关键字承接，域内隔离（assignment 所有权 `MCP_OWNER_CONFLICT`、
lease 可见性 `MCP_LEASE_MISSING`、probe 绑定、approval actor）**已经在用**这个
principal。但这使 wire 面上的 principal 是 **caller-claimed、未经传输认证**：
同 token 连接内任何客户端可指名任意 principal 读 Own 其 assignment/lease（定义
存储本身只按 serverScope 隔离，无 per-principal 维度）。真实宿主注入
request-principal 后，只需在 handler 层把 params["principal"] 换为上下文身份并
从形状里删该参数，服务签名不变。此缺口登记进 integration-request，属宿主
(auth-context) 侧工作，非本 lane 可闭。

## 5. 与 contracts.md §1 的差集（诚实账）

已覆盖：行 1（list/get/saveRevision/archive + approveRevision）、行 2
（probe：权限先行、无凭据、facts 分级）、行 3（assign/unassign：目标权限=域内
owner/CAS/批准/名字冲突先验）、行 4（resolvePreview 只读）、行 5
（inspectConnection/listTools 只报活连接事实）。

差集/偏离，逐条：
1. **行 6 只做 `planForSubmission`**：`apply`/`reconcile` 未注册 wire 行 —
   reconcile 是 lease owner 的域内操作（session_manager.reconcile），apply 属
   Harness C4/C5 闸门另一侧；两者都依赖不存在的 gate，等 gate 合入再定形状。
2. **probe policy 不可由客户端指定**：§1 说"受控 probe policy"，本实现固定用
   `DEFAULT_PROBE_POLICY`（composition 可注入），wire 参数无 policy 项 — 防客户
   端放宽 timeout/byte 界。
3. **resolvePreview 的 `policy_denied` 为空**：Permission 权威无 provider，
   resolve 层的该保留钩子在本层传空集；`lane_by_definition`/
   `native_enforcement_proven` 亦未暴露为 wire 参数（默认全 managed）。
4. **principal 认证缺口**：见 §4。
5. **approveRevision**：§1 输入表未列该操作，但行 3 的"批准 revision"要求它存在
   （且 actor 归属调用 principal）—— 多出的显式项，非缺。
6. **managed client / probe 真实传输**：wire 面上 probe 生产默认走 backend/
   probe.py 真实无凭据握手（tests/probe 已证）；managed lane 生产无
   client_factory → `MCP_CLIENT_FACTORY_MISSING`（G2/G4 开放，登记于
   t04-t05-research），注册件不为 wire 面新增假连接路径。
7. **listTools/inspectConnection 的 facts 内部键**：lease fact ledger 明细
   （`facts[]` 里的 `tool_names`/`catalog_digest` 等）按域存储原样透出（snake），
   顶层投影为 camelCase — 迁移 JSON 兼容性（AGENTS 规则 5）优先于键名一致，留
   待 integration 评审统一。

## 6. 已知未证范围

- 真实 HTTP/stdio probe 经此 wire 面的端到端（tests/probe 已直证域层，wire 层
  用注入 fake runner，避免在 service suite 里 spawn）。
- gate/authority 的真实 provider 行为（无 in-tree 实现）；`mcp.*` 在产品
  composition 里的装配与 compat 退场（C0）。
- error-family 冲突：本表与 `STATIC_ERROR_FAMILIES`、compat/workspace 已发表行
  无重叠码（逐码比对），双插件同组合激活无冲突路径已测（test host 聚合），但
  compat+本插件+workspace 三者同轮的产品组合装配归 C0 验证。
