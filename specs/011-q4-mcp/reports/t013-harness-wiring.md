# T013 harness-wiring：native lane 接真实 C2 API + submission gate 接真实 C4 端口

批次：Q4 T013（消费已发布的 `ordessa_harness_api` pub `d3f026904e`/impl `61966e3118`，
把 T04 L1 自有 DTO 面接到真实 C2/C4 类型，并升级 `planForSubmission` 的端口消费）。
工作树：`worktrees/011-q4-mcp`，HEAD `810ef8095a`。运行环境：仓库根
`.venv/bin/python`（3.12）。纪律：零 git 写操作；只动 Q4 自有写包
（`backend/native_binding.py` 新、`backend/service.py`、`backend/plugin.py`、
`adapters/codex.py`、`adapters/claude.py`、`tests/harness_wiring/**` 新）；
未触碰 harness/permissions/其他线文件与用户运行服务。

## 1. 产物与符号（file:line）

根：`plugins/assets/mcp/`

### backend/native_binding.py（新；Q4 域 ↔ harness 类型唯一边界，909 行）

| 符号 | 位置 |
| --- | :--- |
| `FACET_ID="mcp.servers"` / `FACET_ITEM_ID` / `CONFIGURATION_POINT_ID` / `ENTRIES=("acp",)` | :96-107 |
| 本模块登记码（errors.py 冻结先例）`MCP_GATE_CAPABILITY_UNSUPPORTED`…`MCP_GATE_REFUSED`、`NATIVE_PLANNER_ABSENT` | :110-120 |
| `instance_target_id`/`session_target_id`（句柄身份契约，装配/C1 必须按此发放 handle_id，否则 compile 拒） | :126-131 |
| `FACET_PAYLOAD_SCHEMA`（封闭对象：无 targetPath、lane 枚举 native、additional_properties=False） | :197-219 |
| `OBSERVED_SCHEMA`（观察者 DTO；`evidenceRef` 为 observer 自证位） | :224-245 |
| `facet_payload_of`（NativeIntentSet→payload，schema 即断言）/`intent_set_from_payload` | :323/:352 |
| `observation_payload_of`/`observation_from_payload` | :373/:394 |
| `assessment_from_verdict`（supported 需 runtime-evidence+ref，否则降 unknown——自宣不得升级） | :410 |
| `assess_for_context`（真实 C2 assess：结构性格→`unsupported`、可能但未实证→`unknown`；两品牌 `proven_routes=∅`→恒不 `supported`） | :450 |
| `compile_intent_set`（payload→真 `IntentSet`：跨品牌拒、blocked route 拒、未授权 field 拒、managed endpoint 复用拒、secretRef→`BindSecret`(环境目标+精确 slot 授权)否则类型化拒、secret 形名字 literal 拒） | :512 |
| `verification_from_result`（fact→`Match/Mismatch/VerificationUnknown`：loaded 全量+自证→Match；projected/unknown→`VerificationUnknown`；矛盾→`Mismatch`） | :624 |
| `verification_from_config_readback`（C4 apply 递来的**内容回读**至多 projected，**永不 Match**；缺席/不符=Mismatch） | :666 |
| `configuration_descriptor`（真 `ConfigurationAdapterDescriptor`，claims=(configKey 前缀)） | :701 |
| `McpNativeConfigurationAdapter`（真 C2 Protocol 实现；verify 绑定同 context 的编译计划，跨句柄/换 instance 冒用→`VerificationUnknown` 不确认） | :730 |
| `application_target`/`desired_fragment`/`launch_request`/`plan_view` | :788/:804/:814/:832 |
| `_REFUSAL_CODES`（12 个 `ErrorCode`→域码全表）+`refused_to_mcp_error`/`unknown_to_mcp_error`（Unknown→reconcile-only，绝不重配置/启动）+`runtime_unknown_view`/`reconfiguration_view` | :848-908 |

### backend/service.py（改）

| 符号 | 位置 |
| --- | :--- |
| `SUBMISSION_PERMIT_REQUIRED` / `EXPECTED_REVISION_REQUIRED` / `SUBMISSION_GATE_AMBIGUOUS` 登记码 | service.py:81-88 |
| `McpDomainService.__init__` 新端口 `configuration_service` / `native_planner` / `lane_by_definition` | :234-236 |
| `_preview_model` 透传 lane 绑定（默认空=全 managed，语义不变） | :422 |
| `plan_for_submission`（真端口路径：permit 缺席→拒（**在解析快照之前**，零副作用）；expectedRevision 缺席→拒；双闸门→`SUBMISSION_GATE_AMBIGUOUS`；planner 缺席→`NATIVE_PLANNER_ABSENT`；fragment/payload 经 `facet_payload_of`+`desired_fragment`；`Refused`→`refused_to_mcp_error`、`Unknown`→reconcile-only） | :478 |
| `_plan_for_submission_legacy`（`real_gate is None` 时行为与 T013 前逐行一致：无 gate→`APPLICATION_PORT_ABSENT`；占位 gate→原样应答） | :582 |
| `_freeze_credentials`（两条路径共用凭据冻结；fail-closed 语义不变，明文仍不出 secret.py） | :611 |

### backend/plugin.py（改）

- `mcp.planForSubmission` optional params 增 `expectedRevision`/`submissionPermit`
  （plugin.py:137）；handler 透传 :435-448。
- 端口消费 `harness.configuration_service`（:295；缺席=行为不变）+
  组合注入 `native_planner`/`lane_by_definition`（构造器，:243-266 区段）。
- `MCP_ERROR_FAMILIES` 新 12 行（:232-253 区段：SUBMISSION_*/MCP_GATE_*/
  MCP_VERIFICATION_MISMATCH/MCP_ISOLATION_UNPROVEN/NATIVE_PLANNER_ABSENT +
  经 planner 抛出的 T04 native 码三行），全部有 raise 位点。
- availability：`configuration_service` 或占位 gate 任一在→supported；
  两者无→原 `MCP_SUBMISSION_GATE_UNWIRED`（hello 如实，缺席语义保留）。
- 贡献注册：**不在 plugin.build 里无条件加 `harness.configuration-adapters`
  贡献**——宿主对未声明点的贡献直接拒绝激活（host.py:684-688
  `ContributionPointUnboundError`），默认 `tests/service` Stack 无该点会全红。
  注册路径改为：产品装配声明点（products/server
  `composition.py:89-113` 已声明）后，用 `adapters.<brand>.configuration_adapter()`
  的 payload 做 `Contribution(...)`；本批用真
  `HarnessContributionRegistry`/真 `ServerPluginHost` 在测试里全链证明
  （test_adapter_surface.py 注册格 + test_controlled_chain.compose）。

### adapters/codex.py / adapters/claude.py（改，公开行为不动）

- 原 `assess/compile/verify`（域函数）与 `CODEX`/`CLAUDE` 品牌件零改动——
  `tests/adapters` 63 例全绿为证。
- 新 `configuration_adapter(**overrides)` 工厂（codex.py:94、claude.py:90）：
  把品牌件 pin 进 `McpNativeConfigurationAdapter`（verify_fn 注入
  `verify_native`，backend 包不 import adapters——安装边界）。

### tests/harness_wiring/（新，55 例）

`conftest.py`（复用 adapters/service 测试目录 helper 上 sys.path；无文件系统封禁，
受控链需要真实 tmp 私有代次目录）、`wiring_helpers.py`（真品牌 compile 出计划集、
真 API context/句柄、`StubConfigurationService`、贡献载体插件）、
`test_native_binding_roundtrip.py`(9)、`test_adapter_surface.py`(19)、
`test_submission_gate.py`(13)、`test_controlled_chain.py`(8)、
`test_binding_boundary.py`(6)。

## 2. 真实 API 与设计 §3 的差集（API 不承载 → Q4 侧保留层）

| §3 / T04 映射表语义 | 真 API 承载情况 | Q4 侧保留 |
| --- | --- | --- |
| instance-config 目标 = 文件路径 | `TargetHandle` 明文"never a filesystem path"；descriptor/payload 只带 configKey/format+scope | `InstanceConfigTarget.targetPath` 留在域侧注入描述符，边界**丢弃**不入 payload（test_no_home_path_material_crosses_the_boundary 断言字节级无路径） |
| session-override InvokeAction（R-Q4-3 Codex 主路） | C4 slice `_has_claim` 对 InvokeAction 一律拒（"action claims need a separate explicit grant"，configuration_service.py:110） | 建模为 session-scope file target 上的 `SetField`（merge/preflight 真件放行已证）；真正的 `session/new.mcpServers` 参数路仍是 harness 侧缺口（T10 前置，G2 追加项） |
| 类型化凭据槽（t04 §3 G2 硬条款） | 仅 `BindSecret`：environment 目标 + 描述符级**精确 slot** claims；MCP server/env 名是动态的，静态 descriptor 无法预 claim | 两条腿：context 带授权 env 目标→真 `BindSecret`（ref-only，已证）；否则 secretRef 槽**类型化拒 compile**，绝不落明文、绝不落"ref 冒充值"。缺口如实：文件内嵌 secret 的解析-落盘语义 API 未承载（进 integration 请求） |
| verify 输入=原生观察 | C4 apply 递来的是**内容回读**（materialized generation 解析值，configuration_service.py:300-305），非观察者 attestation | 双形 verify：`OBSERVED_SCHEMA` 观察者形（loaded+自证→`Match`）；内容形至多 `projected`→`VerificationUnknown`。后果：经真 C4 apply 的 MCP 配置**永远到不了 Confirmed**（诚实且已证，见 §4） |
| reset/移除旧 owned 服务器 | compile 只有 `(context, before, desired)`，无 owned-name 枚举 | 类型化 `AdapterRefusal(capability-unsupported)`，不猜测（test_compile_refusals_matrix） |
| planForSubmission 的 permit | `ConfigurationService.plan` 不收 permit；permit 属 `apply(PermitVerifier)` | presence-check 在本域（无 permit 不产 plan、不重配置、不启动）；验证与一次性花费留 harness apply（API 语义如此，不虚报已校验） |
| `ApplicationTarget(server_id, session_id, channel_id)` | Q4 域无 channel 概念 | 映射 server_scope/session_ref/(target_session→harness→"mcp-plan")，差集登记于此 |
| `McpEffectiveSnapshot.lane/owner/enforcement/markers` | API 无 lane 语义 | payload 封闭 schema 镜像这些审计位（lane 枚举 native），managed 泄漏在 schema+endpoint 复查两层拒 |

## 3. 矩阵格升格判定（codex/claude × assess/compile/verify）

L 级定义沿 verification.md（L1 固定版本文件/配置编译、L2 受控实例内全链、
L3 真实运行装载）。**supported 状态无一翻转**（`proven_routes` 仍为空集）。

| 格 | 批前 | 批后 | 依据 |
| --- | --- | --- | --- |
| codex×assess | L1 | **L2** | 真 `Assessment` 类型 + 真 C4 service 里 assess→refused(capability-unsupported) 全链实跑（test_brand_honesty_blocks_the_real_plan），unknown 判定被真实调用方消费 |
| codex×compile | L1 | **L2*** | session-override 真 `IntentSet`/`SetField` 产出+封闭 schema 拒收实跑；真 merge 授权放行经 claude 链证（codex 路同函数）；*InvokeAction 原路未被 API 承载（§2 行 2） |
| codex×verify | L1 | **L2** | 观察者形/内容形双映射 + 跨句柄绑定拒 + sealed-run 全链（test_binding_boundary） |
| claude×assess | L1 | **L2** | 同上，instance-config ctx 真 assess 实跑 |
| claude×compile | L1 | **L2** | 真 C4 plan 全链：compile→merge→preflight→journal.register_plan→Plan（test_probe_double_chain…，链双 assess 标注，见 §4） |
| claude×verify | L1 | **L2** | apply 后真 readback→本 verify→非 Match→服务 Unknown（不重放）；Mismatch/内容缺位两反例实跑 |
| 任何格 L3（真实 CLI 运行装载/权限） | — | **未达，零翻转** | 无真机受控实例；assess 仍 unknown/unsupported；两品牌不得报 supported |

升格口径：L2=「真实 API/harness 件内全链受控执行」，非「路线被实证可用」；
语义正确性证据仍只有 L1（域层）+类型层。报告与测试措辞同此，不越界。

## 4. 受控运行探针：做了什么 / 没做什么

有可无害运行件 → 做了：harness 公开 `ConfigurationApplicationService`（C4 slice）+
`HarnessContributionRegistry`（产品装配就是它俩的 handler 面）+ 自有 controlled
runtime 先例。本批在进程内组装真载体（真 `ServerPluginHost` 声明点+激活贡献
插件、真 merge/materialize/preflight、真 sqlite journal、真 permit 协议、真私有
代次目录），跑 MCP adapter 全链。

- 跑了：assess(unknown)→plan 被真服务类型化拒、零激活零落盘；链双（labelling
  subclass `ChainProbeAdapter`，assess 强制 supported，类注释明标"证明 WIRING
  不证明品牌路线"）→plan 受理→apply 无 permit 拒（permit 花费前零副作用、
  activate_count=0）→signed permit apply→materialize 成功→内容回读 verify→
  服务落 `Unknown`（pending check 原话
  "native effects require independent readback"；本侧 verify 原因
  "projected-only…" 经直连 introspection 复核，非任意异常撞红）→
  query/reconcile 稳定、重放拒；expectedRevision 漂移 plan 拒/apply 拒；
  target generation 换冒用拒；伪造他人 handle 的 intent 超 claim 拒；
  BindSecret（env 目标+精确 slot claim）经真 `_has_claim`/merge 放行（adapter 级）。
- 没做：不 spawn 任何真 CLI、不触网（父 conftest socket/Popen 封禁全程式在场）、
  不写 HOME；未跑 codex 的 C4 全链（compose 只挂 claude 贡献——C4 slice 明文
  "first slice supports one unambiguous contribution"，codex 同路径以 adapter 级+
  sealed-run 覆盖）；真实装载（L3）零——内容回读永远不该确认加载，这条本身是
  本批最重要的负证明。

## 5. 反例账（需求5，全绿）

| 反例 | 抓它的真件/守卫 | 测试 |
| --- | --- | --- |
| 明文 secret 进 IntentSet | 类型层：域 DTO 无明文形；schema 层：封闭 props+`validate_json` secret 名拒；路径层：`SetField` secret 名段拒；渲染层：值只填 literal，secretRef 走 BindSecret 或类型化拒 | roundtrip×3、adapter_surface×2；变异 M3/M4 转红 |
| managed 定义泄漏进 native IntentSet | 域 compile 拒（T04）+ schema lane 枚举 managed 不可形 + 边界 endpoint∈excludedManaged 复拒 | adapter_surface、roundtrip（变异 M4 红） |
| 无 permit 的 plan | service 前置拒（先于任何解析），真 C4 apply 侧 permit 缺失拒且 activate_count=0 | submission_gate、controlled_chain（变异 M2 红） |
| mismatch 报成 loaded | verify 映射无矛盾→Match 通路；内容回读只 project（变异 M1 双红：adapter 级+经真服务链）；未自证 runtime-loaded 降 Unknown | adapter_surface、controlled_chain |
| 跨 target/instance 冒用句柄 | verify ctx-key 绑定（换 generation/品牌 ctx→不确认）；merge"unknown or stale target generation"；`_has_claim` 超 claim 拒；`launch_request` 路径冒充构造期拒 | adapter_surface、controlled_chain×3 |

## 6. 数字与红账（真退出码）

| 命令 | 结果 |
| --- | --- |
| `pytest tests/harness_wiring tests/adapters -q`（dispatch gate） | **118 passed**，exit 0（55 新 + 63 旧零破坏） |
| `pytest tests/harness_wiring -q` | 55 passed（9/19/13/8/6 分文件复跑同值） |
| `pytest tests/service -q` | 30 passed，exit 0（缺席语义/占位 gate/hello 行未破坏） |
| `pytest plugins/assets/mcp/tests -q`（全 MCP 域） | **433 passed**，exit 0 |
| `pytest plugins/harness/api/tests -q` | 14 passed + 37 subtests，exit 0（api 件未动） |
| 变异 M1 内容回读谎报 Match | 2 红（adapter 级 + 真服务链级）→恢复绿 |
| 变异 M2 permit 门前置旁路 | 2 红（含 wire 面）→恢复绿 |
| 变异 M3 secretRef 无 env 目标拒取消 | 1 红→恢复绿 |
| 变异 M4 payload lane 枚举放宽 | 1 红→恢复绿（恢复脚本首跑因参数序自坏，修正后复验绿） |
| 本批红账 | 无遗留红；无 skip/xfail（grep 零命中） |

并行观察：本轮 `plugins/harness` 的 WIP 文件在批次中转为干净（非我改动）；
`tests/managed_client/client_helpers.py` 的 M 属他线，未触碰。最终全量 gate 由主代理跑。

## 7. 遗留（登记，不遮掩）

1. **InvokeAction 路**：C4 slice 现在对 action intent 一律拒——Codex
   `session/new.mcpServers` 真参数路需要 harness 侧 action claims；已按
   session-scope SetField 建模过渡（§2）。→ integration-request/G2 追加。
2. **文件内嵌 secret 落盘**：BindSecret 只吃 environment 目标+静态精确 slot
   claims，动态 slot 名无法预 claim；无 env 目标时 compile 类型化拒——装配
   要给 native 文件里带凭据槽的 server 放行，须 harness 定「动态 slot」承载形。
3. **Confirmed 不可达**：真 C4 apply 用内容回读，本 verify 永不 Match——
   harness 需把观察者 attestation（`OBSERVED_SCHEMA` 形）接进 apply readback，
   MCP 链才可能 Confirmed（这是语义正确，不是缺陷；但产品验收要知道）。
4. reset/owned-name 枚举未建模（§2）；per-definition toolSelection 仍走快照全局
   （T04 遗留原样）。
5. T012 posture 标注面、T014 码收编（本批又添 8 个模块码+12 family 行——
   收编时并表）、T10 Pi 格与 L3 受控探针（需真固定工件授权）。
6. 主树 default 产品装配未把 `harness.configuration_service` 端口指到
   `ConfigurationApplicationService` 实例（需要 ControlledRuntime/PermitVerifier
   真件，归 C0 装配线）；本批 plugin 只消费端口名，缺席语义保持。
7. `mcp.planForSubmission` 的 permit/expectedRevision 仍走 wire params 明文
   字符串——principal 注入面缺口（T09 gap 原样）之上不多伪装。
