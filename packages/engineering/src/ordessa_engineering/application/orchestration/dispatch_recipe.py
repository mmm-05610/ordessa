"""Check the declared original dispatch input before its first effect.

This reads the existing MethodRun, package and method. It creates no input,
permission, attempt, action instance or receipt.
"""
from ordessa_infrastructure.encoding import canonical_bytes

from ..contracts.errors import ApplicationError
from ..contracts.operation_registry import registry_ref
from .method_bridge import MethodBridge
from .method_runs import MethodRunBindings, _check_rounds
from ...methods.definitions.models.compiled import OperationNode


def declared_dispatch_recipe(uow, bindings, *, run_id, step_id, attempt):
    if (type(bindings) is not MethodRunBindings
            or bindings.factory.authority_id != uow.authority_id):
        raise ApplicationError('DISPATCH_WORK_BINDING_AUTHORITY_UNAVAILABLE')
    row = uow.workflow.run_row(run_id)
    from types import SimpleNamespace
    method = bindings._inputs(SimpleNamespace(scope=uow.scope), row)
    snapshot = uow.methods.read_snapshot(method)
    program = bindings._bound_program(snapshot, method, row)
    _check_rounds(program, row['inputs'])
    if (not callable(bindings.registry_loader)
            or row['registry_ref'] != registry_ref(bindings.registry_loader())):
        raise ApplicationError('METHOD_CAPABILITY_CHANGED')
    cursor = row['cursor']
    if (row['status'] != 'RUNNING' or type(cursor) is not int
            or not 0 <= cursor < len(program.workflow.steps)):
        raise ApplicationError('DISPATCH_WORK_STEP_UNAVAILABLE')
    node = program.workflow.steps[cursor]
    if (type(node) is not OperationNode
            or node.id != step_id
            or node.operation != 'engineering.executions.dispatch'):
        raise ApplicationError('DISPATCH_WORK_STEP_UNAVAILABLE')
    declared = MethodBridge().operation_inputs(program, node.id, row['inputs']['slots'])['dispatch']
    if (declared['run_id'] != run_id or declared['step_id'] != step_id
            or declared['attempt'] != attempt):
        raise ApplicationError('DISPATCH_METHOD_INPUT_CHANGED')
    return snapshot, node, declared


def check_dispatch_recipe(uow, bindings, package, request):
    snapshot, node, declared = declared_dispatch_recipe(uow, bindings,
        run_id=request['run_id'], step_id=request['step_id'], attempt=request['attempt'])
    if canonical_bytes(declared) != canonical_bytes(request):
        raise ApplicationError('DISPATCH_METHOD_INPUT_CHANGED')

    # The method's task template binds the actual package bytes/refs. A caller
    # cannot bypass that producer by placing arbitrary ACP params in a slot.
    from .dispatch_inputs import render_dispatch_task
    task = render_dispatch_task(snapshot, package, node,
        run_id=request['run_id'], step_id=request['step_id'], attempt=request['attempt'],
        blobs=_UoWBlobs(uow), resource_reader=_UoWResources(uow))
    params = request['params']
    if (type(params) is not dict or set(params) != {'prompt', 'sessionId'}
            or type(params['sessionId']) is not str or not params['sessionId']
            or params['prompt'] != [{'type': 'text', 'text': task['task_text']}]
            or request['actions'] != task['actions']
            or request['timeout'] != task['timeout']):
        raise ApplicationError('DISPATCH_METHOD_TASK_MISMATCH')
    return declared


def check_bound_dispatch_recipe(uow, bindings, package, binding):
    _snapshot, _node, declared = declared_dispatch_recipe(uow, bindings,
        run_id=binding.run_id, step_id=binding.step_id, attempt=binding.attempt)
    check_dispatch_recipe(uow, bindings, package, declared)
    if (canonical_bytes(declared['unit_ref']) != binding.unit_ref_bytes
            or tuple(declared['actions']) != tuple(action for action, _ in binding.action_instances)
            or canonical_bytes(declared['params']) != uow.implementation.read_blob(binding.prompt_ref)):
        raise ApplicationError('DISPATCH_METHOD_INPUT_CHANGED')
    return declared


class _UoWBlobs:
    def __init__(self, uow):
        self.uow = uow

    def read_verified(self, ref):
        return self.uow.implementation.read_blob(ref)


class _UoWResources:
    def __init__(self, uow):
        self.uow = uow

    def read_blob(self, ref):
        from ...domain.common.models.refs import BlobRef
        from ...domain.common.models.values import Digest
        return self.uow.implementation.read_blob(BlobRef(
            Digest('sha256', ref.digest), ref.byte_length,
            ref.media_type, ref.storage_object_id))
