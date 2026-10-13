"""Baseline and package freezing on the original command journal/transaction.

A persisted package is content, never a BindingProof or a dispatch capability.
Full implementation grants remain unavailable until their original owner is bound.
"""
from dataclasses import asdict
from uuid import uuid4
import hashlib
from ordessa_infrastructure.encoding import canonical_bytes
from ...contracts.commands import CommandContext, CommandResult, request_digest
from ...contracts.errors import ApplicationError
from ....domain.common.models.values import Digest
from ....domain.common.outcomes.diagnostics import ReferenceError
from ....domain.changes.repository_baseline import RepositoryBaseline
from ....domain.changes.repository_baseline_codec import encode_repository_baseline
from ....domain.packages.models import ImplementationPackage
from ....domain.packages.codec import encode_package

class ImplementationUseCases:
    def __init__(self, factory, access=None, *, approval_usecases=None):
        self.factory=factory
        self.access=access
        if approval_usecases is not None and getattr(approval_usecases, "factory", None) is not factory:
            raise ApplicationError("AUTHORIZATION_AUTHORITY_MISMATCH")
        self.approvals=approval_usecases

    @staticmethod
    def package_request_digest(record, context):
        """Original package-command identity; shared with the public step consumer."""
        raw=encode_package(record)
        schema='urn:ordessa:engineering:implementation-content:1'
        return request_digest('engineering.packages.freeze',context,
            {'record_sha256':hashlib.sha256(raw).hexdigest()},[],input_schema_id=schema,
            input_schema_digest=Digest('sha256',hashlib.sha256(schema.encode()).hexdigest()),interface_version='1')

    def _authorize(self, context, operation):
        if type(context) is not CommandContext:
            raise ApplicationError('INVALID_CONTEXT')
        if self.access is None:
            raise ApplicationError('ACCESS_AUTHORITY_UNAVAILABLE')
        self.access.require(context,operation)

    def freeze_baseline(self, record, context):
        operation='engineering.repositories.freeze_baseline'
        self._authorize(context,operation)
        if type(record) is not RepositoryBaseline or (record.ref.realm_id,record.ref.project_id) != (context.scope.realm_id,context.scope.project_id):
            raise ApplicationError('SCOPE_MISMATCH')
        # Current creation captures same-authority content manifests only.
        # A caller-supplied Git commit/overlay is not an authenticated checkout.
        if record.ref.vcs != 'none' or record.ref.dirty_overlay_digest is not None:
            raise ApplicationError('REPOSITORY_CHECKOUT_SOURCE_UNAVAILABLE')
        return self._command(operation,record,encode_repository_baseline(record),context)

    def freeze_package(self, record, context):
        operation='engineering.packages.freeze'
        self._authorize(context,operation)
        if type(record) is not ImplementationPackage or record.scope != context.scope:
            raise ApplicationError('SCOPE_MISMATCH')
        if record.created_at != context.received_at or record.created_by != context.authenticated_actor:
            raise ApplicationError('PACKAGE_ATTRIBUTION_MISMATCH')
        if self.approvals is None:
            raise ApplicationError('IMPLEMENTATION_GRANT_AUTHORITY_UNAVAILABLE')
        from ....domain.approvals.implementation import ImplementationAuthorizationIntent
        from contextlib import ExitStack
        with self.factory.begin(context.scope, 'read') as uow:
            grant = uow.authorization.get_grant(record.payload.authorization_refs[0])
        if type(grant.intent) is not ImplementationAuthorizationIntent:
            raise ApplicationError('ACTION_NOT_AUTHORIZED')
        # Current method, truthful confirmation ingress and full review/trust
        # guards remain held until the original package/action/journal COMMIT.
        with ExitStack() as guards:
            admission = self.approvals._admission()
            guards.enter_context(admission.guard_intent(context, grant.intent))
            guards.enter_context(admission.guard_evidence(context, grant.intent, grant.evidence))
            decisions = guards.enter_context(self.approvals._gates(context, grant.intent))
            return self._command(operation,record,encode_package(record),context,decisions=decisions)

    def _command(self, operation, record, raw, context, *, decisions=()):
        schema='urn:ordessa:engineering:implementation-content:1'
        parameters={'record_sha256':hashlib.sha256(raw).hexdigest()}
        digest=request_digest(operation,context,parameters,[],input_schema_id=schema,
            input_schema_digest=Digest('sha256',hashlib.sha256(schema.encode()).hexdigest()),interface_version='1')
        if operation=='engineering.packages.freeze':
            digest=self.package_request_digest(record,context)
        with self.factory.begin(context.scope) as uow:
            owner=uow.implementation
            reservation=uow.commands.reserve(context.key,project_id=context.scope.project_id,
                operation=operation,operation_id=str(uuid4()),request_digest=digest)
            entry=reservation.entry
            if not reservation.created:
                return CommandResult(uow.authority_id,entry.operation_id,entry.state,entry.result_bytes)
            # Source integrity or binding refusals roll back the reservation;
            # no incomplete package is stored as a successfully bound object.
            if operation=='engineering.repositories.freeze_baseline':
                result={'baseline_ref':asdict(owner.create_repository_baseline(record))}
            else:
                proof = self._resolve_package(uow,record,now=context.received_at)
                self.approvals._check_gates(uow,decisions)
                action_id = str(uuid4())
                uow.authorization.consume_action(record.payload.authorization_refs[0],
                    action='generate_package',action_instance_id=action_id,
                    target_digest=record.digest,now=context.received_at)
                result={'package_ref':asdict(owner.create_package(record)),
                    'binding_proof':asdict(proof),'action_instance_id':action_id,'dispatchable':False}
            result_raw=canonical_bytes(result)
            uow.commands.complete(context.key,state='completed',result_bytes=result_raw,expected_version=entry.version)
            uow.commit()
            return CommandResult(uow.authority_id,entry.operation_id,'completed',result_raw)

    @staticmethod
    def _resolve_package(uow,record,*,now):
        p=record.payload
        baselines={r.repository_id:uow.implementation.resolve_repository_baseline(r) for r in p.baseline_snapshots}
        for row in p.resolved_file_manifest:
            files={f.path:f.blob_ref.digest for f in baselines[row.repository_id].files}
            source=row.rename_from if row.operation=='rename' else row.path
            if row.operation=='add':
                if row.path in files:
                    raise ApplicationError('PACKAGE_BASELINE_FILE_MISMATCH')
            elif files.get(source) != row.before_blob_digest:
                raise ApplicationError('PACKAGE_BASELINE_FILE_MISMATCH')
            if row.operation=='rename' and row.path in files:
                raise ApplicationError('PACKAGE_BASELINE_FILE_MISMATCH')
        blobs=(p.instructions_ref,*p.derivation.input_refs,
            *(b for c in p.proposal_coverage for b in c.instructions))
        for blob in blobs:
            uow.implementation.read_blob(blob)
        budget=uow.proposals.validated_budget()
        proposals=tuple(uow.proposals.get_proposal(ref,budget=budget) for ref in p.change_set.proposal_refs)
        specs=tuple(proposal.implementation_intent for proposal in proposals)
        if not specs or specs[0] is None or any(spec != specs[0] for spec in specs):
            raise ApplicationError('PACKAGE_IMPLEMENTATION_INTENT_MISMATCH')
        spec=specs[0]
        if (spec.implementation_intent_id != p.implementation_intent_id
                or spec.expected_baselines != p.baseline_snapshots
                or not set(p.allowed_actions) <= set(spec.requested_actions)
                or p.acceptance_requirements != spec.acceptance_requirement_refs):
            raise ApplicationError('PACKAGE_IMPLEMENTATION_INTENT_MISMATCH')
        for row in p.resolved_file_manifest:
            if row.operation=='rename':
                allowed=spec.scope.allows_path(row.repository_id,row.rename_from,row.operation,destination=row.path)
            else:
                allowed=spec.scope.allows_path(row.repository_id,row.path,row.operation)
            if not allowed:
                raise ApplicationError('PACKAGE_SCOPE_MISMATCH')
        for ref in p.design_targets:
            uow.engineering.resolve_revision(ref)
        budget.method(p.method_ref)
        if any(proposal.method_ref != p.method_ref for proposal in proposals):
            raise ApplicationError('PACKAGE_METHOD_MISMATCH')
        if p.execution_profile_ref not in spec.scope.environment_refs:
            raise ApplicationError('PACKAGE_EXECUTION_PROFILE_MISMATCH')
        for resource in p.skill_snapshot_refs:
            snapshot=budget.method(resource.method_ref)
            # Exact method resource integrity is checked by the original snapshot owner;
            # no caller-supplied mutable path is executed here.
            if resource.method_ref != p.method_ref:
                raise ApplicationError('PACKAGE_METHOD_MISMATCH')
            actual = next((r for r in snapshot.resources if r.resource_id == resource.resource_id and r.logical_path == resource.logical_path), None)
            if actual is None or actual.digest != resource.resource_digest.hex:
                raise ApplicationError('PACKAGE_RESOURCE_MISMATCH')
        grant=uow.authorization.get_grant(p.authorization_refs[0])
        from .authorization import resolve_implementation_intent
        from ....domain.packages.binding import bind_implementation_package
        resolve_implementation_intent(uow,grant.intent)
        control=uow.authorization.get_control(grant.ref)
        try:
            return bind_implementation_package(record,grant,control_state=control['state'],
                control_version=control['version'],now=now)
        except ReferenceError as exc:
            raise ApplicationError(exc.code) from exc

    def read_baseline(self,ref,context):
        self._authorize(context,'engineering.repositories.get_baseline')
        with self.factory.begin(context.scope,mode='read') as uow:
            return uow.implementation.resolve_repository_baseline(ref)

    def read_package(self,ref,context):
        self._authorize(context,'engineering.packages.get')
        with self.factory.begin(context.scope,mode='read') as uow:
            return uow.implementation.resolve_package(ref)
