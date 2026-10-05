# JD002 Python freeze v1 (2026-10-05)

Authorised implementation baseline e4714eba00a78ba04c5b53318830a0d409e76bbe.
Contracts live in packages/backend/decision/src/ordessa_decision/contracts.
DTO fields use snake_case; to_dict emits the same names; wire adapters explicitly map native camelCase.
No new product wire method is introduced. Codec decision-json/1 and domain-separated SHA-256 are fixed.
ModelCallContext and ReadContext are internal opaque host objects, never serialised in DTOs.
Runtime creates permits only after slot, deadline/budget/cancellation checks and durable call.intent ACK.
Provider claims permit with question+settings+run identity immediately before SDK call.
Gateway validates answer id/kind/closed option ids, records only digests and usage metadata.

Runtime public frozen target: TrustedFlow(ref, graph, new_state, policy_refs, reviewed_code_digest,
review_ref, output_schema=BusinessOutcome, parallel_state_writes=False); runner awaits graph.run,
state from new_state(request), deps=RunContext. Graph steps call await ctx.deps.enter_node(node_id)
then gateway=ctx.deps.gateway. RunContext has request, read-only node services (read,
candidate_source, proposal_source, validator, policy, read_context, policy_refs), limits, gateway,
run_id. It never exposes raw provider. Runtime owns completion/cancellation and evidence.

## Native core read seam

Add optional RuntimeProviderDescriptor.pure_read_contract_version default None.
Accept only agent-configuration-read/1. Methods describe_configuration_offers and
assess_configuration_proposal are opt-in supported_methods. Existing providers stay unsupported.
Core-owned frozen DTOs in pacthold.agents.read_configuration:
OwnerReadContext (environment identity, admitted provider ref and existing authenticated
principal realm; created by core only and identity validated by receiving fake owner in tests),
OwnerConfigurationOfferBatch (owner_ref, definition_ref, descriptor_revision, descriptor_digest,
offers tuple[ConfigurationDescription], complete bool, pure_read_guarantee, unknown_items,
evidence_refs); OwnerProposalAssessment (input_digest, source_versions, status,
issues, obligation_results, validation_scope, evidence_refs, pure_read_guarantee).
OwnerProposalInput (definition_ref, provider_ref, descriptor_revision, proposal_data, source_refs,
required_obligations); input_digest = sha256('agent.configuration-proposal\nagent-read-json/1\n'
+ safe_json(input.to_dict()).encode()), safe_json native canonical encoding with fixed vectors.
Adapter verifies both input digest and decision proposal digest via its local immutable mapping.
Public entry points on existing AgentProviders: describe_configuration_offers(definition_ref),
assess_configuration_proposal(input). Caller already bound to Environment authenticated realm;
no arbitrary principal parameter. Read context comes from core, not caller text.
Core uses existing admission lock, agent_runtime_contribution and read policy,
checks descriptor/revision/provider generation before and after owner callback.
No registry, state owner, operation dispatcher, lease or effect record is introduced.

## Subagent ownership
Runtime: runtime/** and tests/runtime/** only.
Jev: providers/jev/** and tests/providers/** only.
Evidence: evidence/** and tests/integration/test_evidence* only.
No contracts/shared assembly/pyproject/locks/status/Git writes; no test/install execution;
no nested agents. Main session reruns every submitted check serially.

## 防御性绑定补充（2026-10-05）

OwnerProposalValidator 的 input_builder 与 input_verifier 都是可信 host 装配，业务映射不由模型生成。
input_verifier(draft, basis, OwnerProposalInput) 必须返回精确 True；缺席／非 True 在 owner 调用前拒绝。
它负责独立审阅不同 wire 字段、配置 kind 与引用的语义对应；adapter 另外精确核对全部 required_obligations，保留双摘要绑定。
这不是任意映射的自动正确性证明：恶意或错误的可信 verifier 仍是装配风险，不能据此宣称真实家族支持。
原核心复读来源权限／版本与来源 provider generation；must 义务只能引用 input 的已知资料版本或 descriptor，版本标量类型严格一致。
政策内容进入 DecisionServices 时冻结，外部别名不得改变已检查策略。
证据 ACK 绑定精确记录摘要／序号；成功也须读取核对精确持久终态。已 dispatch 的未知失败与协议失败锁定技术失败，业务捕获不恢复预算或重发。
写者身份只证明原目录的非终态存活／中断；已提交归档可通过完整终态与 commit 链验证，复制后的 inode 不作为原写者退出证明。
