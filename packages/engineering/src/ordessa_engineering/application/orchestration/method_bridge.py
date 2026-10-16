"""Pure slot bridge to the finite, implemented Engineering command surface.

Descriptors are derived from actual handlers, not a second persisted registry.
This bridge neither advances a Work nor grants access. Composition executes the
returned parameters through EngineeringService with its own admitted context.
"""
from collections.abc import Mapping

from jsonschema import Draft202012Validator
from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.api.service import EngineeringService, SUPPORTED_COMMANDS
from ordessa_engineering.methods.definitions.models.capabilities import (
    CapabilityDescriptor, CompilationCapabilities,
)
from ordessa_engineering.methods.definitions.models.compiled import CompiledProgram, OperationNode
from ordessa_engineering.methods.definitions.models.identity import method_digest


def command_capabilities():
    """Detached compilation descriptions for the implemented finite command handlers.

    Exceptions stay exceptions; completed/rejected are CommandResult statuses.
    No human consent callback, semantic judge or dispatch capability is claimed.
    """
    descriptors = []
    for operation in SUPPORTED_COMMANDS:
        schema = EngineeringService.input_schema(operation)
        version = schema["$id"].rsplit(":", 1)[1]
        contract = {
            "input_schema": schema,
            "workflow_outcomes": ["completed", "rejected"],
            "effect": "engineering_transaction",
            "idempotency": "command_context_request_id_and_request_digest",
        }
        if operation == 'engineering.submissions.record_report':
            contract['completion'] = 'immutable_asserted_report_submitted_pending_review_not_accepted'
            contract['required_admission'] = 'original_execution_selected_method_schema_work_source_and_current_grant_guards_through_commit'
            contract['facts'] = 'authored_claims_only_no_host_test_file_effect_verification'
        if operation == 'engineering.reviews.record':
            contract['completion'] = 'formal_review_record_persisted_not_implementation_grant'
            contract['required_admission'] = 'original_full_plan_and_current_source_guards_through_commit'
            contract['response_mode'] = 'exact_utf8_envelope_verified_by_original_admission'
        if operation == 'engineering.reviews.request':
            contract['completion'] = 'review_request_persisted_not_review_pass'
        if operation == 'engineering.proposals.associate_review':
            contract['completion'] = 'immutable_successor_proposal_on_same_change_with_exact_completed_review_ref'
            contract['required_admission'] = 'original_change_cas_exact_review_current_source_guards_and_reviewer_trust_through_commit'
            contract['authorization_effect'] = 'none_no_grant_no_artifact_mutation'
        if operation in ('engineering.reviews.assign_reviewer', 'engineering.reviews.revoke_reviewer'):
            contract['completion'] = 'original_library_reviewer_assignment_or_revocation_committed'
            contract['required_admission'] = 'dedicated_current_capability_exact_method_plan_request_and_original_unit_queries'
            contract['trust'] = 'role_selection_only_no_review_decision_or_model_quality_attestation'
        if operation.startswith('engineering.approvals.') or operation == 'engineering.notices.publish':
            contract['authorization_branch'] = 'artifact_acceptance_or_exact_change_apply'
            contract['required_admission'] = 'product_selected_policy_and_original_authority_guards'
        if operation == 'engineering.changes.apply':
            contract['completion'] = 'exact_artifact_heads_and_budget_and_receipt_committed'
            contract['authorization_branch'] = 'exact_change_apply'
            contract['required_admission'] = 'original_intent_and_review_trust_guards'
        if operation.startswith('engineering.work.'):
            contract['required_admission'] = 'original_selected_snapshot_current_business_source_and_same_transaction_work_cas'
            contract['policy_owner'] = 'external_method_workflow_schema_and_roles'
            contract['automatic_dispatch'] = False
            contract['completion'] = {
                'engineering.work.start': 'declarative_work_context_persisted_pinned_to_released_declaration',
                'engineering.work.invoke': 'declared_action_delegated_to_mapped_command_journaled',
                'engineering.work.bind_inputs': 'explicit_immutable_input_revision_bound_by_original_run_cas_cursor_unchanged',
                'engineering.work.record_command_step': 'original_command_journal_result_and_step_cursor_committed',
                'engineering.work.record_dispatch_step': 'original_native_dispatch_receipt_and_step_cursor_committed',
            }[operation]
        if operation == 'engineering.runs.resume':
            contract['completion'] = 'original_wait_cursor_claimed_not_business_effect_dispatched'
            contract['required_admission'] = 'trusted_current_work_condition_and_same_transaction_run_cas'
            contract['wait_families'] = ['object_exists','review_gate','action_authorization','result_exists',
                                         'review_plan_ready','review_response_ready']
            contract['compiled_work_advance'] = 'method-declared_bind_match_next_slots_and_cursor_same_cas; no automatic_effect'
            contract['policy_owner'] = 'external_method_and_original_registered_business_bindings'
        if operation == 'engineering.runs.cancel':
            contract['completion'] = 'declared_cancelled_method_stop_in_original_run_and_journal_not_unit_stop'
            contract['required_admission'] = 'authenticated_operation_scope_exact_method_and_same_transaction_row_ordinal_cas'
            contract['external_effects'] = 'unknown_reserved_possibly_written_refuse_until_original_owner_reconciliation_no_resend'
            contract['policy_owner'] = 'existing_frozen_method_cancellation_contract_and_stop_outcomes'
        if operation == 'engineering.acceptance.adopt':
            contract['completion'] = 'artifact_acceptance_receipt_persisted'
            contract['authorization_branch'] = 'exact_submission_artifact_acceptance'
            contract['required_admission'] = 'submission_closure_current_acceptance_review_and_original_authority_guards'
        if operation == 'engineering.approvals.record_conversation':
            contract['source_trust_grade'] = 'agent-attested'
            contract['required_attestor_role'] = 'registered_main_agent'
        if operation == 'engineering.approvals.request':
            contract['completion'] = 'pending_challenge_not_grant'
        descriptors.append(CapabilityDescriptor(operation, "operation", version,
            method_digest("capability-contract", contract), contract))
    return CompilationCapabilities(tuple(descriptors), trust_class="host")


class MethodBridge:
    def operation_inputs(self, program, node_id, slots):
        """Resolve an exact modern node; do not evaluate config as command data."""
        if type(program) is not CompiledProgram or type(node_id) is not str:
            raise ApplicationError("INVALID_METHOD_PROGRAM")
        if not isinstance(slots, Mapping):
            raise ApplicationError("INVALID_METHOD_SLOTS")
        nodes = [node for node in program.workflow.steps if node.id == node_id]
        if len(nodes) != 1 or type(nodes[0]) is not OperationNode:
            raise ApplicationError("METHOD_OPERATION_NODE_UNAVAILABLE")
        node = nodes[0]
        available=command_capabilities().capabilities
        if node.operation=='engineering.executions.dispatch':
            from .owner_capabilities import owner_capabilities
            available=available+tuple(d for d in owner_capabilities()
                                     if d.capability_id==node.operation)
        descriptors = [item for item in available
                       if item.capability_id == node.operation]
        if len(descriptors) != 1:
            raise ApplicationError("OPERATION_UNAVAILABLE")
        descriptor = descriptors[0]
        bindings = [item for item in program.capability_bindings
                    if item.capability_id == node.operation]
        if len(bindings) != 1 or any(getattr(bindings[0], key) != getattr(descriptor, key)
                for key in ("kind", "interface_version", "contract_digest")):
            raise ApplicationError("METHOD_CAPABILITY_CHANGED")
        if {item.outcome for item in node.outcomes.entries} != set(descriptor.contract["workflow_outcomes"]):
            raise ApplicationError("METHOD_OUTCOME_CONTRACT_MISMATCH")
        parameters = {}
        for binding in (() if node.inputs is None else node.inputs.entries):
            if binding.slot not in slots:
                raise ApplicationError("METHOD_INPUT_SLOT_UNAVAILABLE")
            parameters[binding.name] = slots[binding.slot]
        # Canonical copying forbids arbitrary live objects and breaks nested
        # aliases both ways. Domain codecs still validate exact typed refs.
        try:
            parameters = decode_json(canonical_bytes(parameters))
        except (TypeError, ValueError) as exc:
            raise ApplicationError("INVALID_METHOD_SLOTS") from exc
        if not Draft202012Validator(descriptor.contract["input_schema"]).is_valid(parameters):
            raise ApplicationError("INVALID_ARGUMENT")
        return parameters

    def review_requirements(self, snapshot, bindings, *, proposal=None, artifacts=(), revisions=()):
        """Produce the complete applicable set; optionally retain Proposal IDs.

        The supplied snapshot and business bindings are resolved by original
        owners. Pure conversion neither authenticates them nor activates a
        method. Proposal mode uses the original validator/expander, checking
        its entire frozen set rather than accepting a client-selected subset.
        """
        if proposal is None:
            return tuple(row[0] for row in _review_rows(snapshot, bindings, revisions=revisions))
        return self.proposal_review_requirements(snapshot, (bindings,), proposal=proposal,
            artifacts=artifacts, revisions=revisions)

    def require_workflow_phase(self, snapshot, bindings):
        """Production admission rejects aggregate analysis for declared phases."""
        from ordessa_engineering.methods.definitions.models.compiled import OperationNode, thaw_value
        declared = any(type(n) is OperationNode and n.operation == 'engineering.reviews.request'
            and type(thaw_value(n.config)) is dict and 'standards' in thaw_value(n.config)
            for n in snapshot.program.workflow.steps)
        declared = declared or any(type(n) is OperationNode and n.operation == 'engineering.acceptance.request'
            and type(thaw_value(n.config)) is dict and 'standards' in thaw_value(n.config)
            for n in snapshot.program.workflow.steps)
        if declared and bindings.workflow_node_id is None:
            raise ApplicationError('METHOD_REVIEW_PHASE_UNAVAILABLE')
        if bindings.workflow_node_id is not None:
            _phase_standards(snapshot, bindings)

    def proposal_review_requirements(self, snapshot, phase_bindings, *, proposal, artifacts, revisions):
        """Compare all trusted business phases with one full original Proposal.

        Phase bindings are supplied by the original business owner, never
        enumerated from the stored templates. No template filtering can hide
        another phase or a whole standard omitted by the caller.
        """
        from ordessa_engineering.application.contracts.snapshots import EngineeringTargetBindings
        if (type(phase_bindings) is not tuple or not phase_bindings or len(phase_bindings) > 4096
                or any(type(b) is not EngineeringTargetBindings for b in phase_bindings)
                or len({b.phase_key for b in phase_bindings}) != len(phase_bindings)):
            raise ApplicationError('METHOD_SUBJECT_BINDING_MISMATCH')
        rows = tuple(row for binding in phase_bindings for row in _review_rows(snapshot, binding, revisions=revisions))
        expected = tuple(row[0] for row in rows)
        from ordessa_engineering.domain.changes.operations import validate_proposal
        from ordessa_engineering.domain.changes.models import Proposal
        from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
        if (type(proposal) is not Proposal or proposal.method_ref != expected[0].method_ref
                or any(proposal.scope != b.scope for b in phase_bindings)):
            raise ApplicationError('METHOD_SUBJECT_BINDING_MISMATCH')
        try:
            actual = validate_proposal(proposal, artifacts, revisions)
        except ReferenceError as exc:
            raise ApplicationError(exc.code) from exc
        if sorted(_requirement_semantics(r) for r in actual) != sorted(_requirement_semantics(r) for r in expected):
            raise ApplicationError('METHOD_REQUIREMENTS_CHANGED')
        return actual

    def submission_review_requirements(self, snapshot, phase_bindings, *, requirements, revisions):
        """Validate the full configured acceptance phase set against closure."""
        from ordessa_engineering.application.contracts.snapshots import EngineeringTargetBindings
        if (type(phase_bindings) is not tuple or not phase_bindings or len(phase_bindings) > 4096
                or any(type(b) is not EngineeringTargetBindings or b.review_purpose != 'acceptance'
                       for b in phase_bindings)
                or len({b.phase_key for b in phase_bindings}) != len(phase_bindings)
                or type(requirements) is not tuple or not requirements):
            raise ApplicationError('METHOD_SUBJECT_BINDING_MISMATCH')
        from ...domain.artifacts.models import ArtifactRevision
        if type(revisions) is not tuple or any(type(r) is not ArtifactRevision for r in revisions):
            raise ApplicationError('UNRESOLVED_REVIEW_TARGET')
        resolved = {r.ref:r for r in revisions}
        if len(resolved) != len(revisions) or any(
                target.ref not in resolved for phase in phase_bindings for target in phase.targets.targets):
            raise ApplicationError('UNRESOLVED_REVIEW_TARGET')
        rows = tuple(row for binding in phase_bindings for row in _review_rows(snapshot, binding, revisions=revisions))
        expected = tuple(row[0] for row in rows)
        if sorted(_requirement_semantics(r) for r in expected) != sorted(_requirement_semantics(r) for r in requirements):
            raise ApplicationError('METHOD_REQUIREMENTS_CHANGED')
        # Preserve the original immutable Submission/template expansion identity.
        # Returning base requirements loses the SubmissionRef-bound id/digest,
        # making review_plan reject every otherwise exact expanded requirement.
        return requirements

    def submission_review_plans(self, snapshot, phase_bindings, *, requirements, revisions, review_ids):
        """Build all exact closure requirements; callers cannot request a subset.

        Inputs come from original resolve_submission_acceptance and configured
        phase bindings. This is pure preparation, not source admission or COMMIT;
        actual request/record revalidates the original closure and current guards.
        """
        admitted = self.submission_review_requirements(snapshot, phase_bindings,
            requirements=requirements, revisions=revisions)
        identifiers = {r.requirement_id for r in admitted}
        if (len(identifiers) != len(admitted) or type(review_ids) is not dict
                or set(review_ids) != identifiers
                or any(type(v) is not str or not v for v in review_ids.values())
                or len(set(review_ids.values())) != len(admitted)):
            raise ApplicationError('METHOD_SUBJECT_BINDING_MISMATCH')
        phases = {b.phase_key:b for b in phase_bindings}
        return tuple(self.review_plan(snapshot, phases[r.phase_key], r, review_ids[r.requirement_id],
            revisions=revisions, phase_bindings=phase_bindings, submission_requirements=admitted)
            for r in admitted)

    def review_plan(self, snapshot, bindings, requirement, review_id, *, proposal=None, artifacts=(), revisions=(), phase_bindings=None, submission_requirements=None):
        """Freeze all check policies before evidence, never infer semantic pass."""
        from ordessa_engineering.domain.reviews.models import ReviewPlan, AggregationPolicy
        from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
        if submission_requirements is not None:
            if phase_bindings is None:
                raise ApplicationError('METHOD_SUBJECT_BINDING_MISMATCH')
            admitted = self.submission_review_requirements(snapshot, phase_bindings,
                requirements=submission_requirements, revisions=revisions)
        elif phase_bindings is None:
            admitted = self.review_requirements(snapshot, bindings, proposal=proposal, artifacts=artifacts, revisions=revisions)
        else:
            if proposal is None or bindings not in phase_bindings:
                raise ApplicationError('METHOD_SUBJECT_BINDING_MISMATCH')
            admitted = self.proposal_review_requirements(snapshot, phase_bindings,
                proposal=proposal, artifacts=artifacts, revisions=revisions)
        if requirement not in admitted:
            raise ApplicationError('METHOD_REQUIREMENTS_CHANGED')
        rows = _review_rows(snapshot, bindings, revisions=revisions)
        matching = [policies for expected, policies in rows
                    if _requirement_semantics(expected) == _requirement_semantics(requirement)]
        if len(matching) != 1:
            raise ApplicationError('METHOD_REQUIREMENTS_CHANGED')
        try:
            return ReviewPlan(review_id, requirement, matching[0], AggregationPolicy(), requirement.eligible_reviewer_roles)
        except ReferenceError as exc:
            raise ApplicationError(exc.code) from exc


def _requirement_semantics(requirement):
    from dataclasses import asdict
    value = asdict(requirement)
    # Expanded Proposal identifiers incorporate the exact ProposalRef; retain
    # those identities, while comparing every remaining frozen contract field.
    return canonical_bytes({k:v for k,v in value.items() if k not in ('requirement_id','digest')})



def _phase_standards(snapshot, bindings):
    """Resolve an exact compiled review node; unbound mode is aggregate analysis.

    This content binding does not attest a current Work/StepAttempt. The trusted
    business owner supplies that provenance and the full cross-phase closure.
    """
    from dataclasses import asdict
    from ordessa_engineering.methods.definitions.models.compiled import OperationNode, thaw_value
    if bindings.workflow_node_id is None:
        return snapshot.program.standard_definitions
    nodes = tuple(n for n in snapshot.program.workflow.steps if n.id == bindings.workflow_node_id)
    if len(nodes) != 1 or type(nodes[0]) is not OperationNode:
        raise ApplicationError('METHOD_REVIEW_PHASE_UNAVAILABLE')
    allowed_operations = (('engineering.reviews.request', 'engineering.acceptance.request')
                          if bindings.review_purpose == 'acceptance'
                          else ('engineering.reviews.request',))
    if nodes[0].operation not in allowed_operations:
        raise ApplicationError('METHOD_REVIEW_PHASE_UNAVAILABLE')
    config = thaw_value(nodes[0].config)
    refs = config.get('standards') if type(config) is dict else None
    if type(refs) is not list or not refs or len(refs) > 4096:
        raise ApplicationError('METHOD_PHASE_STANDARDS_UNAVAILABLE')
    standards, seen = [], set()
    for ref in refs:
        if (type(ref) is not dict or set(ref) != {'resource_id', 'sha256', 'kind'}
                or any(type(v) is not str for v in ref.values()) or ref['kind'] != 'standard'):
            raise ApplicationError('METHOD_PHASE_STANDARDS_UNAVAILABLE')
        identity = tuple(sorted(ref.items()))
        if identity in seen:
            raise ApplicationError('METHOD_PHASE_STANDARDS_UNAVAILABLE')
        seen.add(identity)
        matches = tuple(s for s in snapshot.program.standard_definitions if asdict(s.resource_ref) == ref)
        if len(matches) != 1:
            raise ApplicationError('METHOD_PHASE_STANDARDS_UNAVAILABLE')
        standards.append(matches[0])
    configured_purpose = config.get('purpose', bindings.review_purpose)
    if (configured_purpose is None
            or any(s.purpose != configured_purpose for s in standards)):
        raise ApplicationError('METHOD_REVIEW_PURPOSE_UNAVAILABLE')
    return tuple(standards)

def _review_rows(snapshot, bindings, *, revisions=()):
    from dataclasses import asdict
    from ordessa_engineering.application.contracts.snapshots import EngineeringTargetBindings
    from ordessa_engineering.methods.definitions.models.snapshot import MethodSnapshot
    from ordessa_engineering.methods.definitions.models.compiled import thaw_value
    from ordessa_engineering.methods.definitions.defaults import CRITERION_DEFAULTS_V1
    from ordessa_engineering.domain.artifacts.method_binding import MethodRef
    from ordessa_engineering.domain.artifacts.models import ArtifactRevision
    from ordessa_engineering.domain.artifacts.refs import ArtifactRevisionRef
    from ordessa_engineering.domain.common.models.values import Digest
    from ordessa_engineering.domain.common.mechanisms.hashing import record_digest
    from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
    from ordessa_engineering.domain.reviews.targets import TargetSet
    from ordessa_engineering.domain.reviews.models import CriterionSetRef, CheckKey, CheckPolicy, ReviewRequirement
    if type(snapshot) is not MethodSnapshot or type(snapshot.program) is not CompiledProgram:
        raise ApplicationError('METHOD_MODERN_SNAPSHOT_REQUIRED')
    if type(bindings) is not EngineeringTargetBindings:
        raise ApplicationError('INVALID_METHOD_TARGET_BINDINGS')
    if type(revisions) is not tuple or any(type(r) is not ArtifactRevision for r in revisions):
        raise ApplicationError('INVALID_RESOLVED_GRAPH')
    if len(revisions) > 10000:
        raise ApplicationError('MATERIAL_LIMIT')
    graph = {r.ref:r for r in revisions}
    if len(graph) != len(revisions):
        raise ApplicationError('INVALID_RESOLVED_GRAPH')
    types = dict(bindings.document_types)
    known = {d.document_type for d in snapshot.program.document_definitions}
    if not set(types.values()) <= known:
        raise ApplicationError('METHOD_DOCUMENT_TYPE_UNAVAILABLE')
    if len(types) > 4096 or len(snapshot.program.standard_definitions) > 4096:
        raise ApplicationError('MATERIAL_LIMIT')
    ref = snapshot.ref
    method = MethodRef(ref.method_id, ref.release_version, ref.schema_version, Digest('sha256',ref.snapshot_digest))
    rows, covered, work = [], set(), 0
    for standard in _phase_standards(snapshot, bindings):
        policies, required_keys, applicable_targets = [], [], set()
        for criterion in standard.criteria:
            labels = criterion.applies_to
            selected = tuple(t for t in bindings.targets.targets if not labels or types[t] in labels)
            if not selected:
                continue
            if not set(criterion.required_inputs or ()) <= set(bindings.input_slots):
                raise ApplicationError('METHOD_INPUT_SLOT_UNAVAILABLE')
            checks = tuple(thaw_value(check.bindings) for check in criterion.checks)
            modes = tuple(check['iteration'] for check in checks if 'iteration' in check)
            if any(mode not in ('once', 'each_evidence_required_claim') for mode in modes):
                raise ApplicationError('METHOD_CHECK_ITERATION_UNAVAILABLE')
            # Explicit once is the existing single key per target behavior.
            # Only the declared claim expansion introduces claim-specific keys.
            iteration = 'each_evidence_required_claim' in modes
            if iteration and (len(checks) != 1 or checks[0].get('iteration') != 'each_evidence_required_claim'
                    or checks[0].get('claim_selection') != 'all_declared_claims'
                    or checks[0].get('empty_claim_set') != 'error'):
                # Historical snapshots lacking the selection declaration retain
                # their unsupported result; no host-inferred kind exemption.
                raise ApplicationError('METHOD_CHECK_ITERATION_UNAVAILABLE')
            required = CRITERION_DEFAULTS_V1['required'] if criterion.required is None else criterion.required
            blocking = CRITERION_DEFAULTS_V1['blocking'] if criterion.blocking is None else criterion.blocking
            for target in selected:
                if iteration:
                    if type(target.ref) is not ArtifactRevisionRef:
                        raise ApplicationError('METHOD_CLAIM_TARGET_UNAVAILABLE')
                    revision = graph.get(target.ref)
                    if revision is None:
                        raise ApplicationError('UNRESOLVED_REVIEW_TARGET')
                    if not revision.claims:
                        raise ApplicationError('METHOD_REQUIRED_CLAIMS_EMPTY')
                    # The immutable revision's full formal Claim collection is
                    # the authority. Proposal.claim_refs, caller lists, kinds
                    # and presence/absence of evidence links cannot filter it.
                    claim_ids = tuple(c.claim_id for c in revision.claims)
                else:
                    claim_ids = (None,)
                for claim_id in claim_ids:
                    work += 1
                    if work > 10000:
                        raise ApplicationError('MATERIAL_LIMIT')
                    key = CheckKey(target,criterion.criterion_id,claim_id)
                    try:
                        policies.append(CheckPolicy(key,required,blocking))
                    except ReferenceError as exc:
                        raise ApplicationError('METHOD_CHECK_POLICY_UNAVAILABLE') from exc
                    if required: required_keys.append(key)
                applicable_targets.add(target)
        if not policies:
            if bindings.workflow_node_id is not None:
                from ...methods import decode_review_binding
                node = next((n for n in snapshot.program.workflow.steps
                             if n.id == bindings.workflow_node_id), None)
                if node is not None and decode_review_binding(node) is not None:
                    # A declared group member must produce its own complete
                    # single-Plan requirement. Empty applicability cannot
                    # silently omit a standard from the group's full gate.
                    raise ApplicationError('METHOD_REVIEW_APPLICABLE_EMPTY')
            continue
        if (standard.reduction.required_criteria != 'all_applicable' or standard.reduction.empty_applicable_set != 'error'
                or standard.reduction.priority != ('block','manual','pass')):
            raise ApplicationError('METHOD_REDUCTION_UNAVAILABLE')
        if bindings.review_purpose is None:
            if standard.purpose not in ('quality','provenance_support'):
                raise ApplicationError('METHOD_REVIEW_PURPOSE_UNAVAILABLE')
        elif standard.purpose != bindings.review_purpose:
            raise ApplicationError('METHOD_REVIEW_PURPOSE_UNAVAILABLE')
        if len({p.key for p in policies}) != len(policies):
            raise ApplicationError('METHOD_DUPLICATE_CHECK')
        if set(k.target for k in required_keys) != applicable_targets:
            raise ApplicationError('METHOD_REQUIRED_TARGET_UNCOVERED')
        targets = TargetSet(tuple(applicable_targets))
        criteria = CriterionSetRef(standard.standard_id,bindings.criterion_set_version,Digest('sha256',standard.resource_ref.sha256))
        fields = dict(scope=bindings.scope,requirement_version=bindings.requirement_version,purpose=standard.purpose,
            expected_targets=targets,method_ref=method,criterion_set_ref=criteria,required_check_keys=tuple(required_keys),
            eligible_reviewer_roles=bindings.eligible_reviewer_roles,phase_key=bindings.phase_key)
        digest = record_digest('method-review-requirement', {k:asdict(v) if hasattr(v,'__dataclass_fields__') else
            [asdict(x) for x in v] if k=='required_check_keys' else v for k,v in fields.items()})
        try:
            requirement = ReviewRequirement(requirement_id='method-requirement:'+digest.hex,**fields)
        except ReferenceError as exc:
            raise ApplicationError(exc.code) from exc
        rows.append((requirement,tuple(policies)))
        covered.update(applicable_targets)
    if not rows:
        raise ApplicationError('METHOD_REVIEW_REQUIREMENTS_EMPTY')
    if covered != set(bindings.targets.targets):
        raise ApplicationError('METHOD_REVIEW_TARGET_UNCOVERED')
    return tuple(rows)
