"""Declarative Work creation on the original command journal.

A Work is one context record: scope + one exactly released method *declaration*
(never a compiled program) + material revision + caller-selected owner
references. Creation compiles nothing, materializes no program, dispatches no
Unit and writes no project file. Reads of the same record live in
``usecases/queries/works.py``; this module owns the write and the write schema.
"""
import hashlib
from uuid import uuid4

from jsonschema import Draft202012Validator
from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ordessa_engineering.application.contracts.commands import (
    CommandContext, CommandResult, ReadSet, request_digest, read_set_projection,
)
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.work_context import (
    WORK_CONTEXT_KIND, WorkAssociation, WorkBinding, work_binding_projection,
)
from ordessa_engineering.domain.artifacts.method_binding import MethodRef
from ordessa_engineering.domain.artifacts.method_codec import decode_method_ref
from ordessa_engineering.domain.artifacts.ref_codec import decode_artifact_ref
from ordessa_engineering.domain.common.models.values import Digest, validate_id
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
from ordessa_engineering.domain.packages.codec import decode_package_ref
from ordessa_engineering.domain.approvals.ref_codec import decode_approval_ref
from ordessa_engineering.domain.reviews.target_codec import decode_subject_ref

_REFERENCE = {'type': 'object'}
_FIELDS = {
    'engineering.work.start': {
        'work_id': {'type': 'string', 'minLength': 1, 'maxLength': 128},
        'method_ref': _REFERENCE,
        'revision': {'type': 'integer', 'minimum': 1, 'maximum': (1 << 63) - 1},
        'associations': {
            'type': 'array', 'maxItems': 4096,
            'items': {'type': 'object', 'additionalProperties': False,
                      'required': ['kind', 'ref'],
                      'properties': {'kind': {'enum': ['artifact', 'proposal',
                                                       'package', 'submission', 'approval']},
                                     'ref': _REFERENCE}}},
    },
    # A caller names the Work, the declared action, its inputs and an optional
    # revision condition. It never names a command or a step subset: order,
    # steps, inputs and prerequisites come from the released declaration.
    'engineering.work.invoke': {
        'work_id': {'type': 'string', 'minLength': 1, 'maxLength': 512},
        'action_id': {'type': 'string', 'minLength': 1, 'maxLength': 512},
        'inputs': {'type': 'object'},
        'expected_revision': {'x-optional': True, 'type': 'integer', 'minimum': 1,
                              'maximum': (1 << 63) - 1},
    },
}
# Version 2 of the same entry: an explicit continuation request. It is a closed
# shape of its own, so a v1 request keeps its schema id, digest and replay
# identity byte for byte, and a v2 request can never be read as v1 or vice versa.
_VERSIONED = {'engineering.work.invoke': {
    1: _FIELDS['engineering.work.invoke'],
    2: {
        'invocation_version': {'const': 2},
        'work_id': {'type': 'string', 'minLength': 1, 'maxLength': 512},
        'action_id': {'type': 'string', 'minLength': 1, 'maxLength': 512},
        'inputs': {'type': 'object'},
        'expected_revision': {'x-optional': True, 'type': 'integer', 'minimum': 1,
                              'maximum': (1 << 63) - 1},
        'continuation_of': {
            'type': 'object', 'additionalProperties': False,
            'required': ['execution_operation_ref', 'expected_dispatch_version',
                         'expected_acp_revision'],
            'properties': {
                'execution_operation_ref': {'type': 'string', 'minLength': 1, 'maxLength': 512},
                'expected_dispatch_version': {'type': 'integer', 'minimum': 1,
                                             'maximum': (1 << 63) - 1},
                'expected_acp_revision': {'type': 'integer', 'minimum': 1,
                                         'maximum': (1 << 63) - 1}}},
    }}}
_INVOKE = 'engineering.work.invoke'
def _required_and_props(props):
    """Field specs plus the required list; `x-optional` fields are not required."""
    cleaned = {name: {key: value for key, value in spec.items() if key != 'x-optional'}
               for name, spec in props.items()}
    required = [name for name, spec in props.items() if not spec.get('x-optional')]
    return cleaned, required


def _schema_bytes(op, version):
    props = _VERSIONED[op][version] if op in _VERSIONED else _FIELDS[op]
    cleaned, required = _required_and_props(props)
    return canonical_bytes({
        '$schema': 'https://json-schema.org/draft/2020-12/schema',
        '$id': f'urn:ordessa:engineering:operations:{op}:input:{version}', 'type': 'object',
        'properties': cleaned, 'required': required, 'additionalProperties': False})


_SCHEMA_BYTES = {op: _schema_bytes(op, 1) for op in _FIELDS}
_CONTINUATION_SCHEMA_BYTES = {_INVOKE: _schema_bytes(_INVOKE, 2)}
SUPPORTED_WORK_COMMANDS = tuple(_FIELDS)


def input_schema(operation, version=None):
    try:
        if version == 2:
            return decode_json(_CONTINUATION_SCHEMA_BYTES[operation])
        return decode_json(_SCHEMA_BYTES[operation])
    except KeyError:
        raise ApplicationError('OPERATION_SCHEMA_UNAVAILABLE') from None


def decode_work_associations(value):
    """Decode caller-selected exact owner references; nothing is resolved here."""
    if type(value) is not list:
        raise ApplicationError('WORK_ASSOCIATION_INVALID')
    associations = []
    try:
        for item in value:
            if type(item) is not dict:
                raise ApplicationError('WORK_ASSOCIATION_INVALID')
            kind, ref = item['kind'], item['ref']
            if kind == 'package':
                decoded = decode_package_ref(ref)
            elif kind == 'artifact':
                decoded = decode_artifact_ref(ref)
            elif kind == 'approval':
                decoded = decode_approval_ref(ref)
            else:
                decoded = decode_subject_ref(ref)
            associations.append(WorkAssociation(kind, decoded))
    except ApplicationError:
        raise
    except (ReferenceError, TypeError, ValueError, KeyError):
        raise ApplicationError('WORK_ASSOCIATION_INVALID') from None
    return tuple(associations)


class WorkUseCases:
    """Create one declarative Work; every rule stays with the original owners."""

    def __init__(self, factory, access, methods=None):
        self.factory, self.access, self.methods = factory, access, methods

    def _input(self, operation, parameters, context, read_set, *, version=1):
        if type(context) is not CommandContext:
            raise ApplicationError('INVALID_CONTEXT')
        if self.access is None:
            raise ApplicationError('ACCESS_AUTHORITY_UNAVAILABLE')
        self.access.require(context, operation)
        schema_bytes = (_CONTINUATION_SCHEMA_BYTES[operation] if version == 2
                        else _SCHEMA_BYTES[operation])
        try:
            parameters = decode_json(canonical_bytes(parameters))
            if (len(canonical_bytes(parameters)) > 2 * 1024 * 1024
                    or not Draft202012Validator(input_schema(operation, version)).is_valid(parameters)):
                raise ApplicationError('INVALID_INPUT')
        except (TypeError, ValueError):
            raise ApplicationError('INVALID_INPUT') from None
        reads = ReadSet(context.scope, ()) if read_set is None else read_set
        if type(reads) is not ReadSet or reads.scope != context.scope:
            raise ApplicationError('SCOPE_MISMATCH')
        schema = input_schema(operation, version)
        digest = request_digest(operation, context, parameters, read_set_projection(reads),
            input_schema_id=schema['$id'],
            input_schema_digest=Digest('sha256', hashlib.sha256(schema_bytes).hexdigest()),
            interface_version=str(version))
        return parameters, reads, digest

    def _replay(self, operation, context, digest):
        with self.factory.begin(context.scope, 'read') as uow:
            entry = uow.commands.get(context.key)
            if entry is None:
                return None
            if (entry.operation != operation or entry.project_id != context.scope.project_id
                    or entry.request_digest != digest):
                raise ApplicationError('REQUEST_IDENTITY_CONFLICT')
            return CommandResult(uow.authority_id, entry.operation_id, entry.state,
                                 entry.result_bytes)

    def _run(self, operation, context, reads, digest, mutate):
        with self.factory.begin(context.scope) as uow:
            reservation = uow.commands.reserve(context.key, project_id=context.scope.project_id,
                operation=operation, operation_id=str(uuid4()), request_digest=digest)
            entry = reservation.entry
            if not reservation.created:
                return CommandResult(uow.authority_id, entry.operation_id, entry.state,
                                     entry.result_bytes)
            uow.engineering.check_read_set(reads)
            result = mutate(uow)
            final = uow.commands.complete(context.key, expected_version=entry.version,
                result_bytes=canonical_bytes(result), state='completed')
            answer = CommandResult(uow.authority_id, final.operation_id, final.state,
                                   final.result_bytes)
            uow.commit()
            return answer

    def _declaration(self, context, method_ref):
        """Exact released declaration under current control; never a program."""
        if self.methods is None:
            raise ApplicationError('METHOD_DECLARATION_AUTHORITY_UNAVAILABLE')
        declaration, version = self.methods.read_declaration(context, method_ref)
        if getattr(declaration, 'schema_version', None) != 2 or hasattr(declaration, 'program'):
            raise ApplicationError('METHOD_DECLARATION_UNSUPPORTED')
        return declaration, version

    def invoke_replay(self, parameters, context, *, read_set=None):
        """Recorded result of this parent invoke request, or None.

        The parent request identity is journaled like any command: the same
        request with the same content replays exactly the recorded output, and
        the same request with different content is refused instead of writing a
        second effect under one identity.
        """
        value, reads, digest = self._input(_INVOKE, parameters, context, read_set)
        return value, digest, self._replay(_INVOKE, context, digest)

    def continuation_replay(self, parameters, context, *, read_set=None):
        """Recorded result of this exact continuation request, or None.

        The v2 request is a distinct identity (own schema id, digest and
        interface version), so a continuation never replays a v1 invoke result
        and a v1 invoke never replays a continuation.
        """
        value, reads, digest = self._input(_INVOKE, parameters, context, read_set, version=2)
        return value, digest, self._replay(_INVOKE, context, digest)

    def begin_continuation_claim(self, context, candidate, digest):
        """Own the one causal journal row for this origin before any Unit exists.

        The reservation is committed on its own so an interrupted preparation
        leaves a knowable pending row; a competing request id or principal can
        only observe it.
        """
        from .changes.dispatch_continuation import (
            claim_continuation, recheck_continuation_candidate, continuation_operation_id,
            CONTINUATION_OPERATION, ContinuationCandidate)
        if type(candidate) is not ContinuationCandidate or type(digest) is not Digest:
            raise ApplicationError('INVALID_INPUT')
        with self.factory.begin(context.scope) as uow:
            # The evidence reader already closed its read transaction. Recheck
            # the immutable predecessor and root debit inside this claim cut.
            occupied = uow.commands.find_operation(context.scope,
                continuation_operation_id(context.scope, candidate.origin),
                operation=CONTINUATION_OPERATION)
            if occupied is None:
                recheck_continuation_candidate(uow, context, candidate)
            reservation = claim_continuation(uow, context, candidate, digest)
            uow.commit()
            return reservation

    def finish_continuation(self, context, operation_id, result, *, state='completed'):
        return self.finish_invoke(context, operation_id, result, state=state)

    def begin_invoke(self, context, digest):
        """Reserve the invoke journal row before any step runs.

        A row left reserved means the invoke was interrupted while its steps were
        running: that is a knowable pending record for reconciliation, distinct
        from a request that never existed.
        """
        with self.factory.begin(context.scope) as uow:
            reservation = uow.commands.reserve(context.key, project_id=context.scope.project_id,
                operation=_INVOKE, operation_id=str(uuid4()), request_digest=digest)
            entry = reservation.entry
            if not reservation.created:
                return None, CommandResult(uow.authority_id, entry.operation_id,
                                           entry.state, entry.result_bytes)
            operation_id = entry.operation_id
            uow.commit()
            return operation_id, None

    def finish_invoke(self, context, operation_id, result, *, state='completed', validate=None):
        """Finalize the reserved invoke row with the raw step results."""
        self.access.require(context, _INVOKE)
        with self.factory.begin(context.scope) as uow:
            if validate is not None:
                validate(uow)
            entry = uow.commands.get(context.key)
            if entry is None or entry.operation_id != operation_id:
                raise ApplicationError('OPERATION_NOT_FOUND')
            final = uow.commands.complete(context.key, expected_version=entry.version,
                result_bytes=canonical_bytes(result), state=state)
            answer = CommandResult(uow.authority_id, final.operation_id, final.state,
                                   final.result_bytes)
            uow.commit()
            return answer

    def read_command_operation_id(self, context):
        """Operation id of the journal row for this exact request identity.

        Used by the declared-step chain so a step run through the orchestration
        layer still reports the id of the command it delegated to.
        """
        if type(context) is not CommandContext:
            raise ApplicationError('INVALID_CONTEXT')
        with self.factory.begin(context.scope, 'read') as uow:
            entry = uow.commands.get(context.key)
            return None if entry is None else entry.operation_id

    def open(self, parameters, context, *, read_set=None):
        """Pin one Work to a released declaration and caller-chosen references."""
        op = 'engineering.work.start'
        value, reads, digest = self._input(op, parameters, context, read_set)
        validate_id(value['work_id'])
        method_ref = decode_method_ref(value['method_ref'])
        if type(method_ref) is not MethodRef:
            raise ApplicationError('INVALID_INPUT')
        associations = decode_work_associations(value.get('associations', []))
        declaration, control_version = self._declaration(context, method_ref)
        binding = WorkBinding(value['work_id'], context.scope, method_ref,
                              value['revision'], associations)
        replay = self._replay(op, context, digest)
        if replay is not None:
            return replay

        def mutate(uow):
            stable = binding.stable_id
            head = uow.workflow.head_revision(WORK_CONTEXT_KIND, stable)
            current = 0 if head is None else head[0]
            if current + 1 != binding.revision:
                raise ApplicationError('WORK_REVISION_STALE')
            ref = uow.workflow.write_work_context(stable_id=stable, revision=binding.revision,
                body=work_binding_projection(binding))
            return {'work_id': binding.work_id, 'revision': binding.revision,
                    'method_id': method_ref.method_id,
                    'release_version': method_ref.release_version,
                    'snapshot_digest': {'algorithm': 'sha256', 'hex': method_ref.snapshot_digest.hex},
                    'material_digest': ref.digest,
                    'control_version': control_version,
                    'associations': len(binding.associations)}

        return self._run(op, context, reads, digest, mutate)
