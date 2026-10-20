"""Pure exact package/tree/file/effect binding; never authenticates execution."""
from .submission import Submission
from .agent_submission_report import AgentSubmissionReport
from .repository_baseline import RepositoryBaseline
from ..packages.models import ImplementationPackage, PreparedPackagePayload
from ..approvals.consent import ApprovalGrant
from ..approvals.implementation import ImplementationAuthorizationIntent, WorkPackageAuthorizationIntent
from ..common.outcomes.diagnostics import ReferenceError


def validate_submission_graph(record, package, grant, baselines, resulting):
    if type(record) is AgentSubmissionReport:
        if (type(package) is not ImplementationPackage or type(package.payload) is not PreparedPackagePayload
                or type(grant) is not ApprovalGrant or type(grant.intent) is not WorkPackageAuthorizationIntent
                or baselines != () or resulting != ()):
            raise ReferenceError('INVALID_SUBMISSION_GRAPH')
        payload, authorization = package.payload, grant.intent.authorization
        if (record.scope != package.scope or record.package_ref != package.ref
                or authorization.package_ref != package.ref or authorization.scope != record.scope
                or record.authorization_refs != (grant.ref,)
                or record.change_set.proposal_refs != (payload.change_ref,)
                or record.source_refs != (payload.baseline, payload.candidate)
                or record.method_content.schema_ref.method_ref != payload.method_ref
                or authorization.method_ref != payload.method_ref):
            raise ReferenceError('SUBMISSION_PACKAGE_BINDING_MISMATCH')
        return record
    if type(record) is Submission and record.schema_version == 2:
        if (type(package) is not ImplementationPackage or type(package.payload) is not PreparedPackagePayload
                or type(grant) is not ApprovalGrant or type(grant.intent) is not WorkPackageAuthorizationIntent
                or baselines != () or resulting != ()):
            raise ReferenceError('INVALID_SUBMISSION_GRAPH')
        payload, authorization = package.payload, grant.intent.authorization
        if (record.scope != package.scope or record.package_ref != package.ref
                or authorization.package_ref != package.ref or authorization.scope != record.scope
                or record.authorization_refs != (grant.ref,)
                or record.change_set.proposal_refs != (payload.change_ref,)
                or record.source_refs != (payload.baseline, payload.candidate)
                or record.method_content.schema_ref.method_ref != payload.method_ref
                or authorization.method_ref != payload.method_ref):
            raise ReferenceError('SUBMISSION_PACKAGE_BINDING_MISMATCH')
        return record
    if (type(record) is not Submission or type(package) is not ImplementationPackage
            or type(grant) is not ApprovalGrant or type(grant.intent) is not ImplementationAuthorizationIntent
            or type(baselines) is not tuple or type(resulting) is not tuple
            or any(type(b) is not RepositoryBaseline for b in baselines + resulting)):
        raise ReferenceError('INVALID_SUBMISSION_GRAPH')
    p = package.payload
    if (record.package_ref != package.ref or record.change_set != p.change_set
            or record.authorization_refs != p.authorization_refs or record.authorization_refs != (grant.ref,)
            or record.baseline_snapshots != p.baseline_snapshots
            or tuple(b.ref for b in baselines) != record.baseline_snapshots
            or tuple(b.ref for b in resulting) != record.resulting_snapshots
            or record.method_content is not None and record.method_content.schema_ref.method_ref != p.method_ref):
        raise ReferenceError('SUBMISSION_PACKAGE_BINDING_MISMATCH')
    before = {b.ref.repository_id: {f.path:f.blob_ref.digest for f in b.files} for b in baselines}
    after = {b.ref.repository_id: {f.path:f.blob_ref.digest for f in b.files} for b in resulting}
    if not set(after) <= set(before):
        raise ReferenceError('SUBMISSION_FOREIGN_REPOSITORY')
    declared = {repo:dict(files) for repo,files in before.items()}
    planned = {(f.repository_id,f.path):f for f in p.resolved_file_manifest}
    touched = set()
    scopes = dict(grant.intent.scope_by_action)
    for change in record.file_changes:
        plan = planned.get((change.repository_id,change.normalized_path))
        if (plan is None or plan.operation != change.operation or plan.rename_from != change.rename_from
                or plan.before_blob_digest != change.before_blob_digest
                or set(plan.proposal_refs) != set(change.proposal_refs)):
            raise ReferenceError('SUBMISSION_FILE_OUTSIDE_PACKAGE')
        path = change.rename_from if change.operation == 'rename' else change.normalized_path
        destination = change.normalized_path if change.operation == 'rename' else None
        scope = scopes.get('edit_repository')
        if ('edit_repository' not in p.allowed_actions or scope is None
                or not scope.allows_path(change.repository_id,path,change.operation,destination=destination)):
            raise ReferenceError('SUBMISSION_FILE_OUTSIDE_SCOPE')
        files = declared[change.repository_id]
        for name in {path, change.normalized_path}:
            identity = (change.repository_id,name)
            if identity in touched:
                raise ReferenceError('SUBMISSION_FILE_CONFLICT')
        touched.add((change.repository_id,path))
        touched.add((change.repository_id,change.normalized_path))
        if change.operation == 'add':
            if path in files:
                raise ReferenceError('SUBMISSION_BASELINE_MISMATCH')
        elif files.get(path) != change.before_blob_digest:
            raise ReferenceError('SUBMISSION_BASELINE_MISMATCH')
        if change.operation in ('delete','rename'):
            del files[path]
        if change.operation == 'rename' and destination in files:
            raise ReferenceError('SUBMISSION_FILE_CONFLICT')
        if change.operation != 'delete':
            files[change.normalized_path] = change.after_blob_digest
        if change.repository_id not in after:
            raise ReferenceError('SUBMISSION_RESULT_SNAPSHOT_REQUIRED')
    # Full manifest equality catches unreported additions/deletions, including
    # unchanged files silently lost from an allegedly complete resulting tree.
    if any(declared[repo] != files for repo,files in after.items()):
        raise ReferenceError('SUBMISSION_TREE_DIFF_MISMATCH')
    results = {b.ref.repository_id:b.ref for b in resulting}
    for commit in record.commit_refs:
        snapshot = results.get(commit.repository_id)
        if (snapshot is None or snapshot.commit_id != commit.commit_id or snapshot.tree_digest != commit.tree_digest
                or 'create_local_commit' not in p.allowed_actions):
            raise ReferenceError('SUBMISSION_COMMIT_BINDING_MISMATCH')
    known_trees = set(record.baseline_snapshots + record.resulting_snapshots)
    requirements = {r.template_id for r in p.acceptance_requirements}
    for check in record.test_evidence:
        if (check.subject_snapshot not in known_trees or check.requirement_id not in requirements
                or 'run_checks' not in p.allowed_actions):
            raise ReferenceError('SUBMISSION_CHECK_BINDING_MISMATCH')
    for effect in record.effect_observations:
        scope = scopes.get(effect.action)
        if (effect.action not in p.allowed_actions or scope is None
                or not any(limit.action == effect.action and limit.target_id == effect.target_ref.target_id
                    and limit.constraint_digest == effect.target_ref.constraint_digest for limit in scope.effect_limits)):
            raise ReferenceError('SUBMISSION_EFFECT_OUTSIDE_SCOPE')
    # All failed/unknown facts remain intact; binding does not produce pass.
    return record
