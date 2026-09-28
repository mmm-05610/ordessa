# Q4/T10 补格 — wire 契约防漂移守卫 + mcp.probe wire 组合格

任务：T10 剩余账中「mcp.probe wire 组合格」（specs/011-q4-mcp/reports/t10-integration.md §五.3）
+ 新增 Python 常跑的 wire 契约防漂移守卫。范围：仅新增
`plugins/assets/mcp/tests/contract/**` 与本文件；**未改任何既有实现/前端源码，无 git 写操作**。
基线树：HEAD `817ff5ef53`（工作树仅此新目录为 untracked，`git status` 全程复核）。

## 一、结论账（真实退出码）

| 采集 | 命令 | 结果 | EXIT |
| --- | --- | --- | --- |
| 前（开工基线） | `.venv/bin/python -m pytest plugins/assets/mcp -q` | 508 passed in 40.02s | 0 |
| 新目录单跑 | `.venv/bin/python -m pytest plugins/assets/mcp/tests/contract -q` | 16 passed in 2.15s | 0 |
| 后（全目录 gate） | `.venv/bin/python -m pytest plugins/assets/mcp -q` | **524 passed in 40.72s**（508+16，无红、无 skip/xfail、无 warning；conftest 撞名历史坑未复现——目录内无 `from conftest import`，helper 唯一名 `contract_helpers.py`） | 0 |

红账：全程无新增红，也无「整目录红再修复」的前后 ID 账需要记（曾出现过的两目录 helpers/conftest 撞名坑按既有纪律规避，未触发）。

## 二、wire 契约守卫（tests/contract/test_wire_contract_guard.py）

数据源全部从 SOURCE 现读（AST-lite 文本扫描，禁跑 node；descriptor 取真实激活插件的注册面，
非手抄 `_PARAM_SHAPES`）：`frontend/src/wire.ts`（`MCP_WIRE_METHODS` 表、`McpWireClient`
入参与返回类型、fetch 客户端实际发送的 body 字段）、`frontend/src/dto.ts`（响应接口）、
`backend/plugin.py` 经 `ServerPluginHost.activate` 后的 `ServerMethodDescriptor`、
`backend/service.py`/`backend/probe.py::_handshake_facts` 的真实 roundtrip 结果键。

**关键裁定（守卫为何带冻结账本）**：T08 报告自记 wire.ts 的 11 个 id 为 contracts.md §1
操作表的「拟定值」，并把最终核对交给 T09（t08-frontend.md §遗留 5）；T09 按 §1 表注册
`mcp.list/get/archive` 后未回核——两侧均为冻结且各自有测试的 Q4 件。据 contracts.md §1
（行名 `list/get/…/archive`、`planForSubmission`）与「注册面=已测已集成的活线面」判定：
**后端 descriptor 为权威侧，前端表不是**（「若前端表对→列缺陷修复建议」分支不成立）。
改名后端会重写 tests/service / tests/harness_wiring / tests/integration 全部调用面
（非最小改动、违背契约文档名）；前端源码本任务禁改。故守卫**冻结测量出的漂移账本**：任何
一侧再动一个符号而账本未同步更新即红，报错信息点名漂移符号；前端修复时守卫同样变红，
强制对账本做一次有评审的更新（这是防漂移语义，不是遮蔽）。

守卫映射表（TS ↔ descriptor 逐项；「额外缺口」=TS 发送但 descriptor 未声明（dispatch 会按
`unexpected` 拒），「未发必填」=required 而 TS body 不含（dispatch 会按 `missing` 拒）；两者
即 host `WireService.dispatch` 的 shape 墙镜像——静态钉住的正是浏览器今日调不通的原因）：

| TS 键 → TS id | descriptor id | TS body 字段 | 额外缺口 | 未发必填 | 响应路径 | TS 缺字段（相对实答） | 实答多出（TS 未声明） |
| --- | --- | --- | --- | --- | --- | --- | --- |
| listDefinitions → `mcp.listDefinitions` | `mcp.list`（改名在册） | ∅ | — | serverScope, principal | `definitions[0]` | name, approvedRevision, source, lastProbe | nativeName, serverScope |
| getDefinition → `mcp.getDefinition` | `mcp.get`（改名在册） | definitionId | — | serverScope, principal | `latestRevision` | canonical, canonicalDigest, canonicalShape | digest, shape |
| saveRevision → `mcp.saveRevision` | 同名 | definition, definitionId, expectedVersion, operationKey | — | serverScope, principal | `revision` | canonicalDigest | approval, createdAt, digest, shape, source |
| approveRevision → `mcp.approveRevision` | 同名 | +expectedVersion, operationKey | expectedVersion, operationKey | serverScope, principal | 顶层 | approvedRevision | approval, definitionId, revision |
| archiveDefinition → `mcp.archiveDefinition` | `mcp.archive`（改名在册） | definitionId, +expectedVersion, operationKey | expectedVersion, operationKey | serverScope, principal | 顶层 | archived | definition |
| probe → `mcp.probe` | 同名 | definitionId, revision | — | serverScope, principal | `probe` | — | negotiation |
| assign → `mcp.assign` | 同名 | 8 字段 | revision, enabled, expectedRevision | serverScope, principal, decision, expectedRowVersion | `assignment` | revision, enabled, toolSelection | harness, decision, rowVersion, approvedRevision |
| unassign → `mcp.unassign` | 同名 | 5 字段 | expectedRevision | serverScope, principal, expectedRowVersion | `assignment` | — | approvedRevision, decision, definitionId, harness, rowVersion, scopeId, scopeKind |
| resolvePreview → `mcp.resolvePreview` | 同名 | target, scopeRevisions | target, scopeRevisions | serverScope, principal | 顶层 | entries | nativePermissionPostures, snapshot |
| inspectConnection → `mcp.inspectConnection` | 同名 | definitionId, generation, target | definitionId, generation, target | principal, sessionRef, runtimeGeneration, leaseId | 不抽样（需活 lease） | — | — |
| listTools → `mcp.listTools` | 同名 | definitionId, generation, target | generation, target | principal, sessionRef, runtimeGeneration, serverScope, revision | 不抽样（需活 lease） | — | — |
| —（TS 无） | `mcp.planForSubmission` | — | — | — | 在册「后端独有」行：提交面由 Chat/Profile owner 经服务端口消费，非本前端客户端职责 | | |

值域行（WCG-04/04b）：TS `scopeKind: 'user'|'project'|'profile'` ↔ 后端
`SCOPE_KINDS = ("user-default","project","profile","session")`；`'user'` 不可派发由真实
dispatch 见证（MCP_ASSIGNMENT_INVALID / INVALID_REQUEST）。

响应对照方式（按任务要求选可靠并说明）：选 **tests/service 先例的真实 roundtrip 结果形状**，
不选静态读 `service.py`——返回键由 store 视图函数动态拼装，文本扫描会漏/误读；守卫 fixture
在同一组合上逐方法 dispatch（`backend.probe._handshake_facts` 的输出直接作为 probe 腿的
runner 返回值，杜绝手抄 facts 键）。`inspectConnection/listTools` 需真实 lease，属
tests/integration T10-INT-01/05 已证面，守卫只钉其 TS 返回接口名（改名即红）并在账本标注
不抽样原因。

守卫格 ID（pytest nodeid 去前缀）：

| ID | 测试 | 断言面 |
| --- | --- | --- |
| WCG-01 | test_wcg01_method_set_equality_against_registered_drift_ledger | 方法集合相等（经冻结改名/未前端化账本），漂移符号点名 |
| WCG-02 | test_wcg02_ts_request_bodies_within_registered_param_shapes | TS body ⊆ required∪optional 的镜像账本（额外缺口 + 未发必填，双向精确相等） |
| WCG-03 | test_wcg03_ts_answer_contract_vs_real_roundtrip_keys | TS 响应字段/顶层包装 vs 活 dispatch 键（缺口与多出双向精确相等；dto 接口缺失即红） |
| WCG-04 | test_wcg04_scope_kind_value_domains_are_the_registered_drift_pair | scopeKind 两侧值域冻结 + 非子集断言（修复单侧也会变红逼复核） |
| WCG-04b | test_wcg04b_ts_scope_kind_user_value_is_a_typed_live_refusal | `'user'` 漂移的活线反证 |
| WCG-05 | test_wcg05_guard_is_not_vacuous_synthetic_drift_turns_each_layer_red | 反空转孪生：合成改名/新增字段/后端改名键/越界方法各喂一层，断言对应符号出现在漂移串 |
| WCG-06 | test_wcg06_binding_table_row_count_and_ids_are_the_parsed_snapshot | 解析非空转：表 11 行逐键名钉死 |

## 三、mcp.probe wire 组合格（tests/contract/test_probe_wire_chain.py）

真实 `ServerPluginHost`+`WireService.dispatch` 面（tests/service 先例），插件组合的 probe
runner 用生产默认（`backend.probe.probe_definition`），传输为毫秒级 loopback/fake stdio，
probe_authority 端口真实接入。需要 socket/Popen 的格显式请求 `contract_primitives`
（tests/probe lifting 先例）；其余格全程处于包根封锁下——「拒在传输之前」由封锁本体证明，
非 mock 记账。

| ID | 测试 | 证据 | 等级 |
| --- | --- | --- | --- |
| PCP-01 | test_pcp01_probe_stdio_full_chain_graded_facts | 合法 stdio 定义（sys.executable + 毫秒 fake 应答器，env 含 secretRef+literal）经 wire → 真 spawn → 六级 facts：键集恰为 10 键（含 negotiation）、`credentialScope=="unproven"`、`credentialsExcluded==["TOKEN"]`（secretRef 排除未解析）、proves/doesNotProve 逐值、fake 塞入的 `tools[]` 被忽略（wire 面见证反例 8）、权限账本 `[(alice,s1,demo,1)]` | L2 |
| PCP-02 | test_pcp02_probe_wire_shape_wall_refuses_every_malformed_request | 参数校验反例全簇：缺 serverScope/principal/definitionId/revision 各一（`params shape is invalid: missing …`）、revision 字符串、definitionId 非串、未知参数 `unexpected`——且权限端口零调用（全程封锁） | L1 |
| PCP-02b | test_pcp02b_probe_missing_definition_is_a_typed_not_found | 缺定义（形状合法）→ NOT_FOUND `MCP_ASSET_MISSING: …` 过 WireError 映射 | L1 |
| PCP-03 | test_pcp03_probe_gate_is_a_wire_visible_refusal | 权威缺席→UNAVAILABLE/PERMISSION_AUTHORITY_ABSENT；权威拒绝→FORBIDDEN/PERMISSION_REFUSED；均先于传输 | L1 |
| PCP-04 | test_pcp04_probe_remote_definition_via_loopback_http_wire | remote 定义（`Authorization=secretRef`）wire probe 对 127.0.0.1 fake：facts transport remote / unproven / excluded=["Authorization"]；**服务端 witness 恰 1 请求且收到头不含 Authorization**（凭据零携带由被探侧记账） | L2 |
| PCP-05a | test_pcp05a_spawn_failure_keeps_its_typed_code_through_the_wire | 不存在命令 → `PROBE_SPAWN_FAILED: …`、UNAVAILABLE、retryable=True——wire 层不吞 typed 码 | L2 |
| PCP-05b | test_pcp05b_http_refusals_keep_their_families[auth / redirect] | loopback 401→UNAUTHENTICATED/`PROBE_AUTH_REQUIRED: `；302→CAPABILITY_UNSUPPORTED/`PROBE_REDIRECT_REFUSED: ` | L2 |
| PCP-05c | test_pcp05c_timeout_is_policy_bounded_and_typed | 组合注入 `ProbePolicy(timeout=0.3)` 对 2s 慢应答 → `PROBE_TIMEOUT`/UNAVAILABLE（界由 policy 生效，整格毫秒级） | L1/L2 |

反假绿勘察：一次性孪生探针（已删除、不入库）把 PCP-01 同组合去掉 primitives 提升 → dispatch
落在封锁的 `_Blocked`（internalCode）上——证明 PCP-01/04/05 确走真 Popen/socket，非注入双件。

## 四、发现的漂移/缺陷（登记，未修）

1. **MCP 前端 `wire.ts` 客户端对真实 Server 不可用（结构性漂移，非单点）**：
   a) 方法 id 三名不同（`listDefinitions/getDefinition/archiveDefinition` ↔ 注册的
   `list/get/archive`）；b) 每个请求都缺必填 `serverScope`/`principal`（宿主没有请求级
   principal 注入面，T09 已把 principal 作为必填 wire 参数——即 t09-service.md 的 T09 gap 与
   本漂移同源）；c) 7 个方法发送 descriptor 未声明字段（dispatch 会以 `unexpected` 拒）；
   d) 响应为顶层包装（`definitions/latestRevision/probe/assignment/snapshot` 等），TS 客户端
   直接返回内层类型，缺解包；e) 字段名漂移（`canonicalDigest`↔`digest`、
   `canonicalShape`↔`shape`、缺 `canonical`、`revision/enabled/expectedRevision`↔
   `decision/approvedRevision/expectedRowVersion`、`lastProbe/approvedRevision/name/source`
   后端行不产）；f) `scopeKind:'user'` 越出后端值域。影响面：桌面装配（C0）若按现
   wire.ts 起 fetch client，任何 mcp.* 调用都 100% 失败；Settings/Chat 的 fake-client 单测
   不受影响（vitest 全走内存双件，未接真线面）。
2. **TS 客户端缺 `planForSubmission` 绑定**——按 §1 该腿归提交面 owner，判读为有意缺席，
   在册「后端独有」而非缺陷。

**缺陷修复建议（供前端 owner / C0 对账，本任务无权改前端）**：
- 以 descriptor 面为准改名三个方法 id；客户端每请求带 `serverScope`+`principal`
  （或由 C0 决定宿主注入面后另行绑定）；删/改未声明参数（CAS 字段用
  `expectedRowVersion`，开关用 `decision`）；在 `createFetchMcpWireClient` 内解包响应或把
  `McpWireClient` 返回类型改成包装类型；dto.ts 对齐视图键名（`digest/shape` 等）或后端补
  alias（不推荐，会扩面）；`scopeKind` 用 `user-default|project|profile|session`。
- 前端任何一条落地时，本守卫会红并点名符号——按报错把对应账本行删掉/改写即可，账本即
  迁移进度表。

## 五、遗留/边界诚实声明

- 守卫为「快照对账」型：钉死今日测得的漂移账本，防的是「未评审的进一步漂移」；账本本身的
  消除依赖第四节修复建议被采纳（属前端/C0 owner）。
- `inspectConnection/listTools` 的响应键不在本守卫抽样（需活 lease；活线面证据在
  tests/integration T10-INT-01/05），守卫仅保证其 TS 返回接口引用名不漂移。
- 本任务未跑 vitest、未触碰 node；真实外网/真模型零调用（loopback + stdio 管道，无成本）。
