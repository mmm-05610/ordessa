"""Resolve a dispatch package from one method-declared slot on the original run."""
from dataclasses import asdict
from types import SimpleNamespace

from ..contracts.errors import ApplicationError
from ..contracts.method_work import WORK_CONTRACT
from .method_runs import MethodRunBindings, _check_rounds
from ...domain.packages.codec import decode_package_ref
from ...methods.definitions.models.compiled import OperationNode, thaw_value


def resolve_method_run_package(uow, run_id, bindings, *, step_id=None, live=False, attempt=None):
    if (type(bindings) is not MethodRunBindings
            or bindings.factory.authority_id != uow.authority_id):
        raise ApplicationError('DISPATCH_WORK_BINDING_AUTHORITY_UNAVAILABLE')
    return _resolve_package(uow,run_id,step_id=step_id,live=live,attempt=attempt)


def resolve_historical_method_run_package(uow,run_id,*,step_id):
    """Explicit immutable readback only; no live source, effect or old descriptor."""
    return _resolve_package(uow,run_id,step_id=step_id)


def _resolve_package(uow,run_id,*,step_id=None,live=False,attempt=None):
    row=uow.workflow.run_row(run_id)
    method=MethodRunBindings._inputs(SimpleNamespace(scope=uow.scope),row)
    marker=uow.workflow.read(row['method_ref'])
    if marker != {k:v for k,v in row['inputs'].items() if k not in ('slots','rounds')}:
        raise ApplicationError('DISPATCH_WORK_BINDING_INVALID')
    snapshot=uow.methods.read_snapshot(method)
    program=MethodRunBindings._bound_program(snapshot,method,row)
    _check_rounds(program,row['inputs'])
    cursor=row['cursor']
    if type(cursor) is not int or not 0 <= cursor < len(program.workflow.steps):
        raise ApplicationError('DISPATCH_WORK_BINDING_INVALID')
    if step_id is None:
        node=program.workflow.steps[cursor]
    else:
        matches=[node for node in program.workflow.steps if node.id==step_id]
        if len(matches)!=1:
            raise ApplicationError('DISPATCH_WORK_BINDING_INVALID')
        node=matches[0]
    # Current/live work is authorized only under the published native
    # operation descriptor. The retired operation spelling is accepted solely
    # while reading immutable historical runs; it is never a live dispatch
    # route or permission alias.
    historical_operations = {'engineering.executions.dispatch',
                             'engineering.implementation.dispatch'}
    from ..contracts.execution_dispatch import EXECUTION_DISPATCH
    if (type(node) is not OperationNode
            or (node.operation != EXECUTION_DISPATCH
                and not (not live and node.operation in historical_operations))):
        raise ApplicationError('DISPATCH_WORK_STEP_UNAVAILABLE')
    if live:
        if (row['status']!='RUNNING' or program.workflow.steps[row['cursor']].id!=node.id
                or not uow.methods.control(method).enabled):
            raise ApplicationError('DISPATCH_WORK_STEP_UNAVAILABLE')
        if attempt is not None:
            expected_attempt=1+sum(1 for prior in uow.workflow.step_rows(run_id)
                                   if prior['step_id']==node.id and prior['receipt_ref'] is not None)
            if type(attempt) is not int or attempt!=expected_attempt:
                raise ApplicationError('DISPATCH_WORK_ATTEMPT_CHANGED')
    config={} if node.config is None else thaw_value(node.config)
    package_slot=config.get('package_slot')
    if (type(package_slot) is not str or package_slot not in (program.workflow.context_slots or ())
            or package_slot not in row['inputs']['slots']):
        raise ApplicationError('DISPATCH_METHOD_INPUT_BINDING_UNAVAILABLE')
    try:
        ref=decode_package_ref(row['inputs']['slots'][package_slot])
    except Exception as exc:
        raise ApplicationError('DISPATCH_WORK_BINDING_INVALID') from exc
    package=uow.implementation.resolve_package(ref)
    if package.scope!=uow.scope or package.payload.method_ref!=method:
        raise ApplicationError('DISPATCH_WORK_BINDING_INVALID')
    return package
