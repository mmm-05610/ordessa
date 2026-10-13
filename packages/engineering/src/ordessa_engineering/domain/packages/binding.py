"""Pure current-time package binding; a proof is not a permanent execution token."""
from dataclasses import dataclass
from ..common.models.values import Digest, utc_instant, validate_version
from ..common.outcomes.diagnostics import ReferenceError
from ..approvals.consent import ApprovalGrant
from ..approvals.implementation import ImplementationAuthorizationIntent
from ..approvals.refs import ApprovalRef
from .models import ImplementationPackage
from .refs import ImplementationPackageRef


@dataclass(frozen=True)
class PackageBindingProof:
    package_ref: ImplementationPackageRef
    approval_refs: tuple[ApprovalRef, ...]
    intent_digest: Digest
    evaluated_control_versions: tuple[tuple[ApprovalRef, int], ...]
    evaluator_contract_version: str = 'ordessa.package-binding/1'


def bind_implementation_package(package, grant, *, control_state, control_version, now):
    if type(package) is not ImplementationPackage or type(grant) is not ApprovalGrant:
        raise ReferenceError('INVALID_PACKAGE_BINDING')
    intent = grant.intent
    if type(intent) is not ImplementationAuthorizationIntent:
        raise ReferenceError('ACTION_NOT_AUTHORIZED')
    validate_version(control_version)
    utc_instant(now)
    if control_state != 'granted':
        raise ReferenceError('AUTHORIZATION_REVOKED')
    if not intent.not_before <= now < intent.expires_at:
        raise ReferenceError('AUTHORIZATION_EXPIRED')
    p = package.payload
    spec = intent.implementation_spec
    if (package.scope != intent.scope or p.authorization_refs != (grant.ref,)
            or p.change_set != intent.change_set or set(p.design_targets) != set(intent.targets)
            or p.method_ref != intent.method_ref or p.baseline_snapshots != spec.expected_baselines
            or p.implementation_intent_id != spec.implementation_intent_id
            or p.derivation.intent_digest != intent.digest
            or p.acceptance_requirements != spec.acceptance_requirement_refs
            or not set(p.allowed_actions) <= set(intent.actions)
            or set(p.required_review_refs) != set(intent.supporting_review_refs)):
        raise ReferenceError('PACKAGE_GRANT_BINDING_MISMATCH')
    if 'generate_package' not in intent.actions:
        raise ReferenceError('ACTION_NOT_AUTHORIZED')
    scopes = dict(intent.scope_by_action)
    if p.execution_profile_ref not in spec.scope.environment_refs:
        raise ReferenceError('PACKAGE_EXECUTION_PROFILE_MISMATCH')
    for row in p.resolved_file_manifest:
        # File plans are bounded even when the current action merely generates
        # their package; generation never authorizes editing those files.
        path, destination = (row.rename_from, row.path) if row.operation == 'rename' else (row.path, None)
        if not scopes['generate_package'].allows_path(row.repository_id, path, row.operation, destination=destination):
            raise ReferenceError('PACKAGE_SCOPE_MISMATCH')
        if 'edit_repository' in p.allowed_actions and not scopes['edit_repository'].allows_path(
                row.repository_id, path, row.operation, destination=destination):
            raise ReferenceError('PACKAGE_SCOPE_MISMATCH')
    if 'generate_package' not in intent.actions:
        raise ReferenceError('ACTION_NOT_AUTHORIZED')
    return PackageBindingProof(package.ref, (grant.ref,), intent.digest, ((grant.ref, control_version),))
