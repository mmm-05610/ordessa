# D 路网络绑定冻结：最小操作只读查询（FROZEN 2026-10-07）

总协调者冻结，D 路正式编码唯一依据。基线 `c47696b74b11863a9ee2fd1542033e72ce9b513b`。
核心读取语义沿已实现 `AgentOperations.read`（六字段白名单、双 read ACL、
跨 principal 不泄漏、零 owner/claim/恢复），本文件只冻结网络三件套与 CLI 映射，
不重定核心语义。

## 1. 方法与 schema 版本

- wire 方法 id：`agents.operations.read`，action 名 `operationRead`。
- 只进 `agent-assembly/3`（`_MANAGEMENT_BINDINGS` 追加一行），`/1` 不变。
  不升 `/4`：/3 尚处未发行开发期，无已发布消费者 pin /3；此次为纯加法只读方法。
- 参数：`required=("operationRef",)`，`optional=()`，`effectful=False`
 （无 requestId，故 wire 通用异常走 `UNAVAILABLE`，不走 `OUTCOME_UNKNOWN`）。
- wire 结果 schema（`results.operationMetadata`，sealed、无正文/evidence/step）：
  `required=['operationRef','kind','revision','status','nodeRef','hasResult']`，
  `additionalProperties=False`，
  `statuses=['reserved','running','unknown','published','refused','cancelled']`
 （沿 `schema.py` 既有 `preparationOperation` 状态集，不新造枚举）。
  `nodeRef` 可为 null（值为三字段 NodeRef 或 null，由 `decode_node_ref` 形状约束）。
- 能力广告：仅 `supportedMethods` 成员即广告，不新增 `supports` 键
 （`client.negotiate` 的 `support_keys` 精确集保持不变，避免破坏既有协商）。
  wire `capabilities` 的 `supportedMethods` 过滤条件追加 `operationRead` 为
  /3 常开（只读元数据，无前置 capability 键；读 ACL 仍由核心逐次核验）。

## 2. 错误族映射（wire → CLI）

| 核心异常 | wire code | CLI code / exit | status |
| --- | --- | --- | --- |
| `OperationNotFound`（含跨 principal 同形、双 ACL 隐藏） | `NOT_FOUND`（wire 新增映射，与 `ProfileNotFound` 同族） | `OPERATION_NOT_FOUND` / 4 | refused |
| `AdmissionRefusedError`（操作 ACL 先拒） | `FORBIDDEN`（既有） | `AUTHORIZATION_REFUSED` / 3 | refused |
| `IdentityMismatchError`（非法 ref 形状，wire 层） | `CONFLICT_REQUEST`（既有惯例） | `PRECONDITION_CONFLICT` / 5 | refused |
| `GuaranteeUnavailableError`（store 非同库/形状损坏） | `CAPABILITY_UNSUPPORTED`（既有） | `WIRE_REFUSED` / 4 | refused |
| 通用异常（effectful=False） | `UNAVAILABLE`（既有） | `SERVICE_UNAVAILABLE` / 4 | refused |
| 本地形状非法（CLI 发前，见 §3） | — | `PARAMETER_INVALID` / 2 | refused |
| 方法不在 `supportedMethods` | —（HTTP 前拒） | `OPERATION_READ_UNAVAILABLE` / 4 | refused |

`retryable` 全 `False`；恢复动作统一 `inspectService`。成功包络
`status=confirmed`，`evidence={"level":"operationMetadataObserved",
"runtimeVerified":False,"hasResult":<bool>}`。

## 3. CLI 命令

- `ordessa-agent operations read <operationRef> --config <f> --service <a> [--json] [--timeout N]`。
  `operationRef` 为位置参数纯字符串（非 JSON/非 @file）。
- 发前本地校验（与核心 `operations_read.py:43-45` 同形，不自造第二形状）：
  非空字符串、`strip()==`自身、长度 ≤256、无码点 <32；违者 exit 2，零 HTTP。
- 流程：`hello` → `negotiate` → 方法成员检查（缺席 exit 4，
  新码 `OPERATION_READ_UNAVAILABLE`）→ `core_call`（沿 schema 定义，
  不手写第二参数表）→ 结果校验（新 `operations.py:operation_read_result_valid`：
  精确六键集、`operationRef` 与请求一致、status 在枚举内、`hasResult` 为真 bool、
  `nodeRef` 为 null 或三字段合法形状、token 不泄漏）→ 失败 exit 4
 （`CORE_RESPONSE_INVALID`），成功 exit 0。
- 查询回执永不解释为任务完成；`hasResult=true` 只表示存在结果，
  结果正文继续走已冻结领域查询面。

## 4. 生成链路与 Skill

- `packaging/generate_schema.py` 逻辑不变（遍历双版本自动覆盖新方法）；
  执行者改完核心后必须跑 `--write` 再生 `schema-management.json`，
  digest 由测试自证，不得手改镜像。
- 三 Skill（`products/agent-tools/skills/*/SKILL.md`）只追加一条真实查询指令，
 措辞固定模板：`ordessa-agent operations read <operationRef> --config … --service … --json`
  + “只读六字段元数据，不返回正文，不推进/恢复/重发；`hasResult` 不等于任务完成”。
  不写第二种查法，不碰 Skill 其他章节。

## 5. 写权与测试归属（本轮特批，覆盖 11 域措辞冲突）

- D 独占：`pacthold/agents/schema.py`（仅追加 §1 两处：binding 行＋results 项）、
  `apps/server/src/ordessa_server/agent_core_wire.py`（仅追加 `operationRead`
  分支＋`NOT_FOUND` 映射＋supportedMethods 条件）、
  `products/agent-tools/src/ordessa_agent_tools/{cli.py,client.py,operations.py(新),operations.py校验函数}`、
  两 schema 镜像再生、`products/agent-tools/skills/*/SKILL.md` 查询行。
  `client.py` 仅在 `negotiate` 无需改动时不动；如需动，只许改本冻结 §2 所列映射，
  不许改 `support_keys`。
- `products/agent-tools/tests/integration/test_configuration_provider_wire_boundary.py`
  归 D 所有：只覆盖 provider 方法的非法 DTO/未组装拒绝（已冻结面），
  不得依赖 B 未冻结 metadata 形状；B 冻结后该文件不转交。
- D 已有三测试文件中“`agents.operations.read` 不存在”的 absence 断言，
  本冻结生效后由 D 执行者翻转为 presence 断言（保留其余全部拒绝反例，
  99P 只增不删义）。
- `agents/public.py` 仍总协调者唯一；D 不得改核心读取语义。
- pre-dispatch-refusal 无新派工（核心已实现，wire/CLI 不扩）。

## 6. 验收门（执行者逐项实跑）

1. 新方法在 /3 `wire_contract`、`supportedMethods`、生成镜像三处一致，
   digest 校验 exit 0。
2. 本 principal 读自有操作得精确六字段；跨 principal 同形 `NOT_FOUND`；
   操作可读而节点不可读同形 `NOT_FOUND`；非法 ref 本地 exit 2；
   一次查询零 owner/claim/恢复（dump＋计数断言）。
3. 未发 /3 的服务（/1 协商）CLI exit 4 `OPERATION_READ_UNAVAILABLE`，零 HTTP
   写作用；断连/401/版本错沿既有 client 映射，不新增重试。
4. 三 Skill 查询行与命令 `--help` 一致；`init` 不执行二进制行为不变。
5. D 三测试文件全绿且无 skip；既有 99P 拒绝反例（除 §5 翻转项）逐项保留。
