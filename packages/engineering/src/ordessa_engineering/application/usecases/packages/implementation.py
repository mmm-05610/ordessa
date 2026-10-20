"""Baseline and package freezing on the original command journal/transaction.

A persisted package is content, never a BindingProof or a dispatch capability.
Full implementation grants remain unavailable until their original owner is bound.
"""
from dataclasses import asdict
from contextlib import ExitStack
from uuid import uuid4
import hashlib
from ordessa_infrastructure.encoding import canonical_bytes
from ...contracts.commands import CommandContext, CommandResult, request_digest
from ...contracts.errors import ApplicationError
from ....domain.common.models.values import Digest
from ....domain.common.outcomes.diagnostics import ReferenceError
from ....domain.changes.repository_baseline import RepositoryBaseline
from ....domain.changes.repository_baseline_codec import encode_repository_baseline
from ....domain.packages.models import (ImplementationPackage, ImplementationPackagePayload,
                                        PreparedPackagePayload)
from ....domain.packages.codec import encode_package
from ..material_closure import (guard_method_resources, verify_external_source)

class ImplementationUseCases:
    def __init__(self, factory, access=None, *, approval_usecases=None, blobs=None,
                 source_materials=None,method_guard=None,review_admission=None):
        self.factory=factory
        self.access=access
        if approval_usecases is not None and getattr(approval_usecases, "factory", None) is not factory:
            raise ApplicationError("AUTHORIZATION_AUTHORITY_MISMATCH")
        self.approvals=approval_usecases
        if blobs is not None and getattr(blobs, 'authority_id', None) != factory.authority_id:
            raise ApplicationError('PACKAGE_DOCUMENT_BLOB_AUTHORITY_MISMATCH')
        self.blobs=blobs
        self.source_materials,self.method_guard=source_materials,method_guard
        self.review_admission=review_admission
        for port in (source_materials,method_guard):
            if port is not None and getattr(port,'factory',None) is not factory:
                raise ApplicationError('SOURCE_MATERIAL_AUTHORITY_MISMATCH')
        if review_admission is not None and getattr(review_admission,'factory',None) is not factory:
            raise ApplicationError('REVIEW_SOURCE_AUTHORITY_MISMATCH')

    @staticmethod
    def package_request_digest(record, context):
        """Original package-command identity for the immutable reference record."""
        raw=encode_package(record)
        schema='urn:ordessa:engineering:implementation-content:2'
        parameters={'record_sha256':hashlib.sha256(raw).hexdigest()}
        return request_digest('engineering.packages.freeze',context,
            parameters,[],input_schema_id=schema,
            input_schema_digest=Digest('sha256',hashlib.sha256(schema.encode()).hexdigest()),interface_version='2')

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
        if type(record.payload) is not PreparedPackagePayload:
            raise ApplicationError('IMPLEMENTATION_ENVELOPE_UNAVAILABLE')
        if record.created_at != context.received_at or record.created_by != context.authenticated_actor:
            raise ApplicationError('PACKAGE_ATTRIBUTION_MISMATCH')
        # Exact caller identity is enough to reconcile an existing command.
        # Do this before consulting current grant/control state: completed work
        # is read back, never re-authorized and replayed as a new effect.
        expected=self.package_request_digest(record,context)
        with self.factory.begin(context.scope, 'read') as uow:
            prior=uow.commands.get(context.key)
            if prior is not None:
                if (prior.operation != operation or prior.project_id != context.scope.project_id
                        or prior.request_digest != expected):
                    raise ApplicationError('REQUEST_IDENTITY_CONFLICT')
                return CommandResult(uow.authority_id,prior.operation_id,prior.state,prior.result_bytes)
        with ExitStack() as guards:
            payload=record.payload
            if self.source_materials is None:
                raise ApplicationError('SOURCE_VERSION_UNAVAILABLE')
            if self.method_guard is None:
                raise ApplicationError('METHOD_AUTHORITY_UNAVAILABLE')
            if self.review_admission is None:
                raise ApplicationError('REVIEW_SOURCE_AUTHORITY_UNAVAILABLE')
            definition=guards.enter_context(guard_method_resources(context,payload.method_ref,
                payload.method_resource_refs,self.method_guard))
            role_reader=getattr(self.method_guard,'preparation_roles',None)
            if not callable(role_reader):
                raise ApplicationError('METHOD_PREPARATION_ROLES_UNAVAILABLE')
            try:
                required_roles=role_reader(context,definition,payload.method_resource_refs)
            except ApplicationError:
                raise
            except Exception as exc:
                raise ApplicationError('METHOD_PREPARATION_ROLES_UNAVAILABLE') from exc
            if (type(required_roles) is not tuple or not required_roles or len(required_roles)>128
                    or any(type(role) is not str or not role or len(role)>128 for role in required_roles)
                    or len(set(required_roles))!=len(required_roles)):
                raise ApplicationError('METHOD_PREPARATION_ROLES_UNAVAILABLE')
            document_roles=tuple(document.role for document in payload.documents)
            if (not payload.documents or any(document_roles.count(role)!=1 for role in required_roles)
                    or any(role not in required_roles for role in document_roles)):
                raise ApplicationError('PACKAGE_DOCUMENT_ROLES_INCOMPLETE')
            for source in (payload.baseline,payload.candidate):
                verify_external_source(context,source,self.source_materials)
            if self.blobs is None:
                raise ApplicationError('PACKAGE_DOCUMENT_BLOB_AUTHORITY_MISMATCH')
            for document in payload.documents:
                source = document.source_ref
                raw = verify_external_source(context, source, self.source_materials)
                self.blobs.put_verified(raw, source.capture.content_digest, source.media_type)
            with self.factory.begin(context.scope,'read') as uow:
                proposal=uow.proposals.get_proposal(payload.change_ref)
                proposal_control=uow.proposals.get_control(payload.change_ref)
                if proposal_control.disposition!='available':
                    raise ApplicationError('PACKAGE_SOURCE_BINDING_MISMATCH')
                self._validate_prepared_package(payload,proposal)
                reviews=tuple(uow.reviews.get_review(ref) for ref in payload.review_refs)
            self._validate_prepared_reviews(context,payload,proposal,reviews,guards)
            with self.factory.begin(context.scope) as uow:
                owner=uow.implementation
                reservation=uow.commands.reserve(context.key,project_id=context.scope.project_id,
                    operation=operation,operation_id=str(uuid4()),request_digest=expected)
                entry=reservation.entry
                if not reservation.created:
                    return CommandResult(uow.authority_id,entry.operation_id,entry.state,entry.result_bytes)
                state='completed'
                try:
                    with uow.isolate():
                        current=uow.proposals.get_proposal(payload.change_ref)
                        current_control=uow.proposals.get_control(payload.change_ref)
                        self._validate_prepared_package(payload,current)
                        actual=tuple(uow.reviews.get_review(ref) for ref in payload.review_refs)
                        if (current!=proposal or current_control!=proposal_control
                                or current_control.disposition!='available' or len(actual)!=len(reviews)
                                or any(a.record!=b.record or a.control.state!='active'
                                       for a,b in zip(actual,reviews))):
                            raise ApplicationError('PACKAGE_SOURCE_BINDING_MISMATCH')
                        ref=owner.create_package(record)
                        result={'package_ref':asdict(ref),'dispatchable':False}
                except ApplicationError as exc:
                    if exc.code not in {'NOT_FOUND','SCOPE_MISMATCH','RECORD_CORRUPT',
                            'PACKAGE_SOURCE_BINDING_MISMATCH','PROPOSAL_REVIEW_ASSOCIATION_INVALID'}:
                        raise
                    state,result='rejected',{'code':exc.code}
                raw=canonical_bytes(result)
                final=uow.commands.complete(context.key,state=state,result_bytes=raw,
                    expected_version=entry.version)
                answer=CommandResult(uow.authority_id,final.operation_id,state,raw)
                uow.commit()
                return answer

    @staticmethod
    def _validate_prepared_package(payload,proposal):
        source=proposal.source_change
        if (proposal.schema_version!=2 or source is None
                or source.baseline.content_identity!=payload.baseline.content_identity
                or source.candidate.content_identity!=payload.candidate.content_identity
                or set(source.review_refs)!=set(payload.review_refs)
                or proposal.method_ref!=payload.method_ref
                or set(source.method_resource_refs)!=set(payload.method_resource_refs)):
            raise ApplicationError('PACKAGE_SOURCE_BINDING_MISMATCH')

    def _validate_prepared_reviews(self,context,payload,proposal,reviews,guards):
        from ....domain.reviews.targets import SourceTargetRef
        from ....domain.reviews.models import CurrentReviewTrust
        expected={proposal.source_change.baseline.content_identity,
                  proposal.source_change.candidate.content_identity}
        for controlled in reviews:
            record=controlled.record
            plan=record.plan
            targets=plan.requirement.expected_targets.targets
            refs=tuple(t.ref for t in targets if type(t.ref) is SourceTargetRef)
            if (controlled.control.state!='active' or not record.complete or record.verdict!='pass'
                    or plan.requirement.schema_version!=2
                    or plan.requirement.method_ref!=payload.method_ref
                    or set(plan.requirement.method_resource_refs)!=set(payload.method_resource_refs)
                    or len(refs)!=len(targets)
                    or {item.source_ref.content_identity for item in refs}!=expected):
                raise ApplicationError('PROPOSAL_REVIEW_ASSOCIATION_INVALID')
            guards.enter_context(self.review_admission.guard_plan(context,plan))
            trusted=guards.enter_context(self.review_admission.guard_trust(context,(record,)))
            if (type(trusted) is not tuple or len(trusted)!=1
                    or type(trusted[0]) is not CurrentReviewTrust
                    or trusted[0].review_ref!=record.ref
                    or trusted[0].verifier_id!=record.reviewer_evidence.verifier_id
                    or trusted[0].trust_version!=record.reviewer_evidence.trust_version):
                raise ApplicationError('UNTRUSTED_REVIEWER')

    def _command(self, operation, record, raw, context):
        if operation != 'engineering.repositories.freeze_baseline':
            raise ApplicationError('IMPLEMENTATION_ENVELOPE_UNAVAILABLE')
        schema='urn:ordessa:engineering:implementation-content:1'
        parameters={'record_sha256':hashlib.sha256(raw).hexdigest()}
        digest=request_digest(operation,context,parameters,[],input_schema_id=schema,
            input_schema_digest=Digest('sha256',hashlib.sha256(schema.encode()).hexdigest()),interface_version='1')
        with self.factory.begin(context.scope) as uow:
            owner=uow.implementation
            reservation=uow.commands.reserve(context.key,project_id=context.scope.project_id,
                operation=operation,operation_id=str(uuid4()),request_digest=digest)
            entry=reservation.entry
            if not reservation.created:
                return CommandResult(uow.authority_id,entry.operation_id,entry.state,entry.result_bytes)
            # Source integrity or binding refusals roll back the reservation;
            # no incomplete package is stored as a successfully bound object.
            result={'baseline_ref':asdict(owner.create_repository_baseline(record))}
            result_raw=canonical_bytes(result)
            uow.commands.complete(context.key,state='completed',result_bytes=result_raw,expected_version=entry.version)
            uow.commit()
            return CommandResult(uow.authority_id,entry.operation_id,'completed',result_raw)

    @staticmethod
    def _resolve_package(uow,record,*,now):
        p=getattr(record, 'payload', None)
        if type(p) is not ImplementationPackagePayload:
            raise ApplicationError('IMPLEMENTATION_ENVELOPE_UNAVAILABLE')
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

    def get_package(self,ref,context):
        self._authorize(context,'engineering.packages.get')
        with self.factory.begin(context.scope,mode='read') as uow:
            return uow.implementation.resolve_package(ref)

