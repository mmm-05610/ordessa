# B 路准入冻结：配置贡献的原 Registry 准入与发现（FROZEN 2026-10-07）

总协调者冻结，B 路正式编码唯一依据。基线 `c47696b74b11863a9ee2fd1542033e72ce9b513b`。
020 纯 DTO（`ConfigurationRoute/Descriptor/Pin/Reference/Extraction`、
`validate_reference_extraction`）已实现已验证，不重冻；本文件只冻结
“贡献进唯一 Registry 的准入表示、Runtime 认可端口关联、对外安全 metadata”，
三项在 020 明确缺席（`configuration-reference-contract-v1.md:23`）。

## 1. 准入表示：配置贡献走既有 Agent 贡献通道

- 不新增 Registry 表/第二注册中心。配置提供者贡献搭载既有
  `AgentContributionSet.agent_runtime_providers` 通道：同一 staged batch、
  同一 commit 原子性、同一 `owner → provider → descriptor` 三元存储
  （`registration.py:301-316` 准入、`380-382` 发布、`419-421` 退役）。
- 配置贡献的载体是 **RuntimeProvider 实例上挂载的只读声明**，不是新 provider
  种类：沿 `AgentContributionSet.__post_init__` 既有门（`runtime.py:26-31`
  “RuntimeProvider 不得声明可信 owner 身份”保持），新增一条 additive 检查——
  若实例携带 `configuration_routes` 属性，则其值必须为
  `tuple[ConfigurationRoute, ...]`（020 冻结类型，逐项复用其 `__post_init__`），
  否则 `CoreDTOError`。无该属性 = 无配置贡献，不猜、不补空。
- 冲突键（`RegistrationConflictError`，复用既有异常类型）：
  1. `configuration_kind + schema_version` 二元键跨全 Registry 唯一
     （与 `claimed_agent_runtime` provider_id 键、`claimed_definitions` definition
     键并列第三套键；同一 batch 内重复、跨 batch 已占均冲突）。
  2. 同一 definition 精确键被两个不同 provider 的 route 同时声明 → 冲突
     （歧义路线，发前拒，不做优先级仲裁）。
  3. 同一 provider 同一 kind/schema 重复 route → 冲突。
- 退役：`unregister` 整 batch 移除（既有语义），配置贡献随所属 batch 同生共死；
  不提供单 route 摘除。退役 pin 永不可用于新作用（沿夜派 B:41 验收）。
- 020 三字段 contribution 冻结保持：C1 `CoreContributionSet` 三字段签名不变，
  本片只读 `agent_runtime_providers` 扩展位，不改旧准入语义。

## 2. Runtime 认可端口关联（核心固定并验证）

- 关联表示：配置 route 的每个 `definition_ref` 必须精确等于**同一 Registry 内
  已接纳的某个 RuntimeProvider descriptor 的 `definition_ref`**
  （`safe_json` 逐字节相等，复用 `environment.py:639` 既有比较式）。
  不相等 = 无 Runtime 认可关联 = 该 route 不可用于提取/编译（见 §4）。
- 核验点（两处，缺一不可）：
  1. **准入时**（`CoreRegistry.stage` 内新增检查）：route 的每个 definition 精确键
     必须命中“同一 batch 内或已 active 的”Runtime definition 键集合，
     否则 `RegistrationConflictError`（发前拒：声明了无人认可的 definition）。
  2. **读取时**（`Environment.agent_configuration_contribution` 新方法，见 §3）：
     重核 `agent_runtime_contribution` 既有四重门
     （active 唯一 activation、descriptor 未篡改、方法可调用、无自报 owner，
     `environment.py:644-650`），任一失败 → `AdmissionRefusedError`
     （不降级为自报信任）。
- `supported_methods` 门：route 可用当且仅当其所属 provider 的
  Runtime descriptor `supported_methods` 包含 `assess_configuration`。
  提取引用另需该 provider 的配置 descriptor 声明 `extract_references`
  （020 既有 validator 门保持）；编译（`compile`）本片不广告（见 §4）。
- generation 语义：关联核验只认当前 active generation；activation 换代后旧 pin
  的 route 查询按“退役 pin 不可新用”拒绝，不做跨代沿用。

## 3. 对外安全 metadata（只读副本，无 callable）

- 新只读方法 `Environment.agent_configuration_contributions()` /
  `agent_configuration_contribution(definition_ref)`，复用
  `agent_runtime_contributions` 的锁/读 ACL（`agents.runtime` read）与
  “staged/draining 排除、篡改拒绝”语义（`environment.py:598-617`）。
- 返回 `AdmittedConfigurationProviderMetadata`（新 frozen DTO，
  放 `core/configuration_admission.py`，字段：`owner_activation`（复制
  `ActivationRef`，沿 `AdmittedResourceProviderMetadata:116-123` 模式）、
  `descriptor: ConfigurationProviderDescriptor`（深快照）、
  `recognized_definitions: tuple[sealed definition_ref, ...]`（§2 已核验子集，
  排序固定）、`runtime_provider_ref`（§2 命中的 `AdmittedRuntimeProvider`
  的 `provider_ref` 密封投影，不泄漏实例对象）。
  无 callable、无实例对象、无 payload 解析器。
- `agents/providers.py` 新增 `AgentProviders.configuration_list/describe` 薄投影
  （`descriptor.to_dict()` + `providerRef` + `recognizedDefinitions`），
  wire 方法暂不新增（B 本片不碰 wire/CLI/schema；对外暴露面止于核心 API，
  待 A 纵向接合时由总协调者另行绑定）。
- 缺 provider 行为：空 Registry/无 route/关联核验失败 → 空元组或
  `AdmissionRefusedError`，统一为 `unsupported/unknown`，不补空依赖、
  不回退旧链。

## 4. 方法广告边界（不把 DTO 存在当能力）

- 本片**只接准入/发现/引用提取的已冻结端口**：`describe`、`validate`、
  `extract_references`（020 六方法中仅此三者进入本片验收）。
- `assess`、`compile`、`verify` 在本片保持“声明可存在、核心不调用”：
  descriptor 可声明它们为子集，但核心无调用点、无 wire 绑定、无 CLI；
  任何调用企图 typed 拒绝。`compile` 可执行的广告等 A 路效果计划冻结后另议。
- `supportedMethods` 存在 ≠ 能力已验证（沿 020 合同：元数据存在不当实现证据）。

## 5. 写权与测试归属（本轮特批）

- B 独占：`pacthold/core/registration.py`（仅 §1 通道检查＋冲突键）、
  `pacthold/core/configuration_admission.py`（仅 §3 新 DTO）、
  `pacthold/environment.py`（仅 §3 两个新方法）、
  `pacthold/agents/runtime.py`（仅 §1 属性检查）、
  `pacthold/agents/providers.py`（仅 §3 薄投影）、
  `pacthold/agents/public.py`（仅导出新 DTO/方法名清单，由总协调者复核）、
  新测试 `products/agent-tools/tests/integration/test_configuration_provider_admission.py`。
  `environment.py` 跨域写权由本冻结特批（覆盖 11 域“环境归平台身份域独占”
  措辞），仅限上述两个方法，锁/ACL 沿既有用例。
- 旧 Registry/Runtime/material 准入语义不改义；020 三字段 contribution 冻结保持。
- `test_configuration_provider_wire_boundary.py` 仍归 D（§5 已裁定），B 不得依赖它；
  B 自己的 wire 边界测试等总协调者后续绑定时另派。

## 6. 验收门

1. 无 `configuration_routes` 属性的 Runtime 贡献准入行为与冻结前一致
   （既有 Registry 测试全绿）。
2. 非法 routes（坏类型/跨环境/重复 kind+schema/无人认可 definition）→
   `CoreDTOError`/`RegistrationConflictError`，batch 不留残余 staged。
3. 同一 kind+schema 被两家声明 → 第二家 `RegistrationConflictError`；
   同一 definition 被两家 route → 第二家冲突；descriptor 篡改/换代后读取
   `AdmissionRefusedError`。
4. `supported_methods` 缺 `assess_configuration` 的 provider 其 route 发现时
   不可用（`recognized_definitions` 为空），但准入本身可过（声明≠能力）。
5. Host 身份伪造（自带 owner/generation 属性）→ `CoreDTOError`（沿既有门）。
6. 对外 metadata 无 callable（`callable` 扫描断言）、输入输出副本不改内部
   （alias 污染反例）、core 原方向 guard 保绿。
7. 缺 provider 时发现为空/`AdmissionRefusedError`，不补空、不回退。
