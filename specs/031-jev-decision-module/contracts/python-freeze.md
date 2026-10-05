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
