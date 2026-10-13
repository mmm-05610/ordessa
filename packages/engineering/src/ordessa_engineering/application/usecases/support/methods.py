"""Explicit authorized adoption/control on the original command journal.

Internal composition API only; no new wire/catalog capability is advertised.
Snapshot publication alone never selects or enables a project method.
"""
from dataclasses import asdict
from uuid import uuid4
from ordessa_infrastructure.encoding import canonical_bytes
from ...contracts.commands import CommandContext, CommandResult, request_digest
from ...contracts.errors import ApplicationError
from ....domain.artifacts.method_binding import MethodRef
from ....domain.common.models.values import Digest, validate_version, validate_text
from ....methods.definitions.models import MethodRef as SnapshotRef


class MethodUseCases:
    def __init__(self, factory, access, snapshots, management):
        if getattr(snapshots,'library',None) is not getattr(factory,'library',None) or getattr(factory,'library',None) is None:
            raise ApplicationError('METHOD_AUTHORITY_MISMATCH')
        self.factory,self.access,self.snapshots,self.management=factory,access,snapshots,management

    def _run(self, operation, method, context, parameters, mutate):
        if type(context) is not CommandContext or type(method) is not MethodRef:
            raise ApplicationError('INVALID_INPUT')
        if self.access is None: raise ApplicationError('ACCESS_AUTHORITY_UNAVAILABLE')
        self.access.require(context,operation)
        if self.management is None: raise ApplicationError('METHOD_MANAGEMENT_UNAVAILABLE')
        snapshot=self.snapshots.get(SnapshotRef(method.method_id,method.release_version,method.schema_version,method.snapshot_digest.hex))
        parameters={'method_ref':asdict(method),**parameters}
        import hashlib
        schema=canonical_bytes({'operation':operation,'internal_contract':'1'})
        digest=request_digest(operation,context,parameters,{},input_schema_id='urn:ordessa:'+operation+':internal:1',input_schema_digest=Digest('sha256',hashlib.sha256(schema).hexdigest()),interface_version='1')
        # An authorized retry is history, not a new management event.
        with self.factory.begin(context.scope,'read') as uow:
            entry=uow.commands.get(context.key)
            if entry is not None:
                if (entry.operation,entry.project_id,entry.request_digest)!=(operation,context.scope.project_id,digest):
                    raise ApplicationError('REQUEST_IDENTITY_CONFLICT')
                return CommandResult(uow.authority_id,entry.operation_id,entry.state,entry.result_bytes)
        with self.management.guard_management(context,operation,method,parameters) as event:
            if type(event) is not Digest or event.algorithm != 'sha256':
                raise ApplicationError('METHOD_MANAGEMENT_UNAVAILABLE')
            with self.factory.begin(context.scope) as uow:
                reservation=uow.commands.reserve(context.key,project_id=context.scope.project_id,operation=operation,operation_id=str(uuid4()),request_digest=digest)
                entry=reservation.entry
                if not reservation.created:
                    return CommandResult(uow.authority_id,entry.operation_id,entry.state,entry.result_bytes)
                result=mutate(uow.methods,entry.operation_id,event,snapshot)
                final=uow.commands.complete(context.key,expected_version=entry.version,result_bytes=canonical_bytes(asdict(result)),state='completed')
                answer=CommandResult(uow.authority_id,final.operation_id,final.state,final.result_bytes)
                uow.commit()
                return answer

    @staticmethod
    def _plan_digest(snapshot):
        from ....methods.compilation.encoding import program_plan_digest
        value=program_plan_digest(snapshot.program)
        return Digest('sha256',value.removeprefix('sha256:'))

    def adopt(self, method, context, *, expected_version):
        validate_version(expected_version)
        return self._run('engineering.methods.adopt',method,context,{'expected_version':expected_version},lambda repo,id,event,snapshot:repo.select(method,id,expected_version,event,context.received_at,self._plan_digest(snapshot)))

    def control(self, method, context, *, expected_version, enabled, reason):
        validate_version(expected_version);validate_text(reason)
        if type(enabled) is not bool: raise ApplicationError('INVALID_INPUT')
        return self._run('engineering.methods.control',method,context,dict(expected_version=expected_version,enabled=enabled,reason=reason),lambda repo,id,event,snapshot:repo.set_control(method,expected_version,enabled,event,reason,context.received_at))
