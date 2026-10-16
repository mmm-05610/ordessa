"""Form ACP parameters once from a method task and one original live Unit."""
from collections.abc import Mapping

from ordessa_infrastructure.encoding import decode_json
from ordessa_infrastructure.encoding.immutable_json import safe_json

from ...application.api.dispatch_input import build_method_dispatch_inputs
from ...application.contracts.commands import CommandContext
from ...application.contracts.errors import ApplicationError
from ...application.contracts.execution_dispatch import EXECUTION_DISPATCH
from .local_bindings import build_local_dispatch_bindings


def build_local_method_dispatch_inputs(method_runs, blobs, unit_owner, access):
    """Bind the original method reader and selected original Unit owner.

    ``prepare`` accepts the full UnitRef returned by the one explicit creation.
    Its result is the existing seven-field dispatch value. Consumers bind that
    exact value through the original immutable Work input path and execute the
    original dispatch. This builder creates no Unit, Grant, claim or receipt.
    """
    reader = build_method_dispatch_inputs(method_runs, blobs, access)
    # Reuse the actual local producer's public owner/access validation. This
    # constructs ports over the retained owner; it never assembles another one.
    build_local_dispatch_bindings(unit_owner, access,
        prompt_parameters=lambda *_: None)
    return _LocalMethodDispatchInputs(reader, unit_owner, access)


class _LocalMethodDispatchInputs:
    def __init__(self, reader, owner, access):
        self.reader, self.owner, self.access = reader, owner, access

    def prepare(self, context, *, run_id, step_id, attempt, unit_ref):
        if (type(context) is not CommandContext
                or self.access.current_context() is not context
                or context.scope.realm_id != self.owner.permission.scope.realm_id
                or context.scope.project_id != self.owner.permission.scope.project_id
                or not isinstance(unit_ref, Mapping)):
            raise ApplicationError('DISPATCH_TASK_INPUT_AUTHORITY_UNAVAILABLE')
        self.access.require(context, EXECUTION_DISPATCH)
        try:
            unit = self.owner.manager.get(dict(unit_ref))
            snapshot = unit.snapshot()
            if (safe_json(unit.identity) != safe_json(unit_ref)
                    or safe_json(snapshot['identity']) != safe_json(unit_ref)):
                raise ValueError('original Unit identity differs')
            session = snapshot['sessionId']
            if (type(session) is not str or not session
                    or any(ord(char) < 32 for char in session)):
                raise ValueError('original native session unavailable')
        except Exception as exc:
            raise ApplicationError('RECORDED_DISPATCH_FIXED_SESSION_UNAVAILABLE') from exc
        task = self.reader.read_task(context,
            run_id=run_id, step_id=step_id, attempt=attempt)
        return {'run_id': run_id, 'step_id': step_id, 'attempt': attempt,
                'unit_ref': decode_json(safe_json(unit_ref).encode('utf-8')),
                'params': {'prompt': [{'type': 'text', 'text': task['task_text']}],
                           'sessionId': session},
                'actions': task['actions'], 'timeout': task['timeout']}

    def prompt_parameters(self, context, package, unit_ref, dispatch_recipe=None):
        """Forward the method-checked native mapping during an original cut.

        The dispatcher supplies its exact recipe to the source guard. Reconcile
        supplies the original frozen binding/prompt; neither rerenders a task or
        rewrites the native parameters here.
        """
        if (type(context) is not CommandContext
                or self.access.current_context() is not context
                or package.scope != context.scope
                or not isinstance(dispatch_recipe, Mapping)
                or safe_json(dispatch_recipe.get('unit_ref')) != safe_json(unit_ref)
                or not isinstance(dispatch_recipe.get('params'), Mapping)):
            raise ApplicationError('DISPATCH_METHOD_INPUT_SOURCE_UNAVAILABLE')
        return dispatch_recipe['params']


__all__ = ['build_local_method_dispatch_inputs']
