"""Exact package/submission closure for formal result acceptance.

This module resolves persisted facts through the caller's original UoW. It does
not issue authority or decide a review verdict.
"""
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from ordessa_infrastructure.encoding import canonical_bytes

from ...contracts.errors import ApplicationError
from ...contracts.snapshots import EngineeringTargetBindings
from ..proposal_closure import resolve_record
from ....domain.approvals.implementation import ImplementationAuthorizationIntent
from ....domain.changes.submission import Submission
from ....domain.changes.submission_binding import validate_submission_graph
from ....domain.common.outcomes.diagnostics import ReferenceError
from ....domain.packages.models import ImplementationPackage
from ....domain.reviews.refs import SubmissionRef
from ....domain.reviews.requirements import expand_submission_requirement
from ....domain.artifacts.refs import ArtifactRevisionRef


@dataclass(frozen=True)
class SubmissionAcceptanceClosure:
    submission: Submission
    package: ImplementationPackage
    requirements: tuple
    artifact_revisions: tuple
    proposals: tuple
    templates: tuple


def resolve_submission_acceptance(uow, submission_ref):
    """Resolve the full exact acceptance subject set on one active UoW.

    The package reference comes only from the immutable Submission. Proposal,
    grant, template and revision identities are re-read from their original
    owners; no client-selected requirement list or latest-record lookup is used.
    """
    if type(submission_ref) is not SubmissionRef or submission_ref.project_id != uow.scope.project_id or submission_ref.realm_id != uow.scope.realm_id:
        raise ApplicationError('SCOPE_MISMATCH')
    submission = uow.submissions.resolve(submission_ref)
    package = uow.implementation.resolve_package(submission.package_ref)
    payload = package.payload
    if (submission.scope != uow.scope or package.scope != uow.scope
            or submission.package_ref != package.ref
            or submission.authorization_refs != payload.authorization_refs
            or submission.change_set != payload.change_set):
        raise ApplicationError('SUBMISSION_PACKAGE_BINDING_MISMATCH')
    grant = uow.authorization.get_grant(payload.authorization_refs[0])
    if type(grant.intent) is not ImplementationAuthorizationIntent:
        raise ApplicationError('ACTION_NOT_AUTHORIZED')
    intent, spec = grant.intent, grant.intent.implementation_spec
    if (payload.authorization_refs != (grant.ref,) or payload.change_set != intent.change_set
            or set(payload.design_targets) != set(intent.targets)
            or payload.method_ref != intent.method_ref
            or payload.baseline_snapshots != spec.expected_baselines
            or payload.implementation_intent_id != spec.implementation_intent_id
            or payload.derivation.intent_digest != intent.digest
            or payload.acceptance_requirements != spec.acceptance_requirement_refs
            or not set(payload.allowed_actions) <= set(intent.actions)
            or set(payload.required_review_refs) != set(intent.supporting_review_refs)
            or payload.execution_profile_ref not in spec.scope.environment_refs):
        raise ApplicationError('PACKAGE_GRANT_BINDING_MISMATCH')
    scopes = dict(intent.scope_by_action)
    for row in payload.resolved_file_manifest:
        path, destination = ((row.rename_from, row.path) if row.operation == 'rename' else (row.path, None))
        if ('generate_package' not in scopes
                or not scopes['generate_package'].allows_path(row.repository_id, path, row.operation,
                    destination=destination)
                or 'edit_repository' in payload.allowed_actions and
                   ('edit_repository' not in scopes or not scopes['edit_repository'].allows_path(
                       row.repository_id, path, row.operation, destination=destination))):
            raise ApplicationError('PACKAGE_SCOPE_MISMATCH')
    # Historical dispatch/source binding is immutable evidence. It must still
    # resolve exactly, while current grant control is intentionally not used to
    # decide whether already captured output facts exist.
    from ...orchestration.steps.implementation_dispatch import resolve_dispatch_submission_binding
    resolve_dispatch_submission_binding(uow, submission)
    proposals_by_ref = {}
    proposal_templates = {}
    budget = uow.proposals.validated_budget()
    for proposal_ref in payload.change_set.proposal_refs:
        proposal = uow.proposals.get_proposal(proposal_ref, budget=budget)
        if proposal.implementation_intent != spec:
            raise ApplicationError('SUBMISSION_PACKAGE_BINDING_MISMATCH')
        # This validates the current Proposal and the complete frozen template
        # set against its exact revisions, while ordinary deferred templates
        # remain deliberately unexpanded here.
        resolve_record(proposal, uow.proposals, budget)
        roots = tuple(m.proposed_ref for m in proposal.mutations)
        roots += tuple(m.base_ref for m in proposal.mutations if m.base_ref is not None)
        roots += tuple(c.owner_revision_ref for c in proposal.claim_refs)
        graph = uow.proposals.resolve_revision_graph(roots, budget)
        proposals_by_ref[proposal_ref] = (proposal, graph)
        proposal_templates[proposal_ref] = tuple(t for t in proposal.review_requirement_templates if t.deferred)
    if set(proposals_by_ref) != set(payload.change_set.proposal_refs):
        raise ApplicationError('SUBMISSION_PACKAGE_BINDING_MISMATCH')

    expected_refs = tuple(spec.acceptance_requirement_refs)
    actual_refs = tuple(t.ref for rows in proposal_templates.values() for t in rows)
    package_refs = tuple(payload.acceptance_requirements)
    if (len(actual_refs) != len(set(actual_refs)) or set(actual_refs) != set(expected_refs)
            or set(package_refs) != set(expected_refs) or len(package_refs) != len(expected_refs)):
        raise ApplicationError('METHOD_REQUIREMENTS_CHANGED')
    coverage = {c.proposal_ref: c for c in payload.proposal_coverage}
    if set(coverage) != set(proposal_templates):
        raise ApplicationError('PACKAGE_COVERAGE_INCOMPLETE')
    for proposal_ref, templates in proposal_templates.items():
        refs = tuple(t.ref for t in templates)
        if (set(coverage[proposal_ref].acceptance_requirements) != set(refs)
                or len(coverage[proposal_ref].acceptance_requirements) != len(refs)):
            raise ApplicationError('PACKAGE_COVERAGE_MISMATCH')

    baselines = tuple(uow.implementation.resolve_repository_baseline(r) for r in submission.baseline_snapshots)
    resulting = tuple(uow.implementation.resolve_repository_baseline(r) for r in submission.resulting_snapshots)
    validate_submission_graph(submission, package, grant, baselines, resulting)
    output_refs = tuple(submission.output_refs)
    if not output_refs or any(type(ref) is not ArtifactRevisionRef for ref in output_refs):
        raise ApplicationError('SUBMISSION_OUTPUT_UNSUPPORTED')
    revisions_by_ref = {}
    for ref in output_refs:
        revisions_by_ref[ref] = uow.engineering.resolve_revision(ref)
    requirements, templates = [], []
    for proposal_ref in payload.change_set.proposal_refs:
        for template in proposal_templates[proposal_ref]:
            if template.purpose != 'acceptance':
                raise ApplicationError('METHOD_REVIEW_PURPOSE_UNAVAILABLE')
            templates.append(template)
            try:
                requirements.append(expand_submission_requirement(template, submission_ref,
                    spec.implementation_intent_id, output_refs, revisions_by_ref))
            except ReferenceError as exc:
                raise ApplicationError(exc.code) from exc
    if not requirements or len({r.requirement_id for r in requirements}) != len(requirements):
        raise ApplicationError('METHOD_REQUIREMENTS_CHANGED')
    return SubmissionAcceptanceClosure(submission, package, tuple(requirements),
        tuple(revisions_by_ref[ref] for ref in output_refs),
        tuple(proposals_by_ref[r][0] for r in payload.change_set.proposal_refs), tuple(templates))


def _canonical_set(records):
    return sorted(canonical_bytes(asdict(value)) for value in records)


class SubmissionAcceptanceIntentAdmission:
    """Current method and business-owner guard for an exact acceptance intent."""
    def __init__(self, factory, method_control, bindings):
        if getattr(method_control, 'factory', None) is not factory:
            raise ApplicationError('METHOD_AUTHORITY_MISMATCH')
        self.factory, self.methods, self.bindings = factory, method_control, bindings
        from ...orchestration.method_bridge import MethodBridge
        self.bridge = MethodBridge()

    @contextmanager
    def guard_intent(self, context, intent):
        from ....domain.approvals.consent import AuthorizationIntent
        if (type(intent) is not AuthorizationIntent or intent.scope != context.scope
                or intent.actions != ('accept_artifact',)):
            raise ApplicationError('ACTION_NOT_AUTHORIZED')
        selector = getattr(self.bindings, 'resolve_acceptance_submission', None)
        phase_resolver = getattr(self.bindings, 'resolve_submission_bindings', None)
        if not callable(selector) or not callable(phase_resolver):
            raise ApplicationError('METHOD_TARGET_BINDINGS_UNAVAILABLE')
        submission_ref = selector(context, intent)
        if (type(submission_ref) is not SubmissionRef
                or (submission_ref.realm_id, submission_ref.project_id) !=
                   (context.scope.realm_id, context.scope.project_id)):
            raise ApplicationError('METHOD_SUBJECT_BINDING_MISMATCH')
        with self.methods.guard_method(context, intent.method_ref) as snapshot:
            phases = phase_resolver(context, intent.method_ref, submission_ref)
            if (type(phases) is not tuple or not phases or len(phases) > 4096
                    or any(type(binding) is not EngineeringTargetBindings
                           or binding.scope != context.scope
                           or binding.review_purpose != 'acceptance' for binding in phases)
                    or len({binding.phase_key for binding in phases}) != len(phases)):
                raise ApplicationError('METHOD_SUBJECT_BINDING_MISMATCH')
            for binding in phases:
                self.bridge.require_workflow_phase(snapshot, binding)
            with self.factory.begin(context.scope, 'read') as uow:
                closure = resolve_submission_acceptance(uow, submission_ref)
            payload = closure.package.payload
            if payload.method_ref != intent.method_ref:
                raise ApplicationError('CONSENT_BINDING_MISMATCH')
            self.bridge.submission_review_requirements(snapshot, phases,
                requirements=closure.requirements, revisions=closure.artifact_revisions)
            output_refs = {record.ref for record in closure.artifact_revisions}
            if (set(intent.targets) != output_refs
                    or len(intent.targets) != len(output_refs)
                    or not intent.required_review_requirements
                    or any(requirement.purpose != 'acceptance'
                           or requirement.method_ref != intent.method_ref
                           or requirement.scope != context.scope
                           or any(type(target.ref) is not ArtifactRevisionRef
                                  for target in requirement.expected_targets.targets)
                           for requirement in intent.required_review_requirements)
                    or {target.ref for requirement in intent.required_review_requirements
                        for target in requirement.expected_targets.targets} != output_refs
                    or _canonical_set(intent.required_review_requirements) !=
                       _canonical_set(closure.requirements)):
                raise ApplicationError('CONSENT_BINDING_MISMATCH')
            yield closure
