"""Exact read of one declarative Work record; no model, no dispatch, no write.

The read is deliberately dumb: it returns the persisted binding as it is, plus
the *current* method-control state so a later revocation or re-admission is
visible instead of silently inherited. It never resolves the referenced records,
never compiles, never advances a run and never writes.
"""
from dataclasses import asdict

from ordessa_engineering.application.contracts.commands import CommandContext, ReadSet
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.work_context import (
    WORK_CONTEXT_KIND, WORK_STABLE_ID_PREFIX, WorkContext, decode_work_binding,
)
from ordessa_engineering.domain.common.models.values import validate_id

_INPUTS = {
    "engineering.work.get": {"work_id"},
}
SUPPORTED_WORK_QUERIES = tuple(_INPUTS)


class WorkQueries:
    """Read one Work; admission stays with the original access authority."""

    def __init__(self, factory, access, methods=None, mapped_steps=None,
                 bound_capabilities=None, permit_execute=None):
        self.factory, self.access, self.methods = factory, access, methods
        # The composition declares which declared method step maps to which
        # capability, which capabilities it actually bound in this process, and
        # whether a caller may execute a given declared action. An empty mapping
        # means "nothing is executable yet", never "available".
        # A callable is kept as-is so a binder that lands after construction
        # (the real dispatch owner) is still seen by later reads.
        self.mapped_steps = mapped_steps if callable(mapped_steps) else dict(mapped_steps or {})
        self.bound_capabilities = bound_capabilities
        self.permit_execute = permit_execute

    def _work_id(self, parameters):
        if type(parameters) is not dict:
            raise ApplicationError('INVALID_INPUT')
        try:
            work_id = parameters['work_id']
            validate_id(work_id)
        except (TypeError, KeyError, ValueError):
            raise ApplicationError('INVALID_INPUT') from None
        return work_id

    def _control(self, context, method_ref):
        """Current method-control state; a revoked method is reported, not hidden."""
        if self.methods is None:
            return None, None
        try:
            declaration, version = self.methods.read_declaration(context, method_ref)
        except (ApplicationError, TypeError, ValueError) as refused:
            return {'enabled': False, 'reason': getattr(refused, 'code', 'METHOD_CONTROL_UNAVAILABLE')}, None
        return ({'enabled': True, 'version': version,
                 'declaration_schema_version': getattr(declaration, 'schema_version', None)},
                declaration)

    def _bound(self):
        if not callable(self.bound_capabilities):
            return set()
        return {str(capability) for capability in self.bound_capabilities()}

    def _mapped(self):
        """Declared step -> capability, resolved lazily so a binder that lands
        after construction (real dispatch) is still seen."""
        return self.mapped_steps() if callable(self.mapped_steps) else self.mapped_steps

    def read_binding(self, context, work_id):
        """Decoded binding of this Work, for callers that need its exact pins."""
        if type(context) is not CommandContext:
            raise ApplicationError('INVALID_CONTEXT')
        if self.access is None:
            raise ApplicationError('ACCESS_AUTHORITY_UNAVAILABLE')
        self.access.require(context, 'engineering.work.get')
        validated = self._work_id({'work_id': work_id})
        stable = f'{WORK_STABLE_ID_PREFIX}{validated}'
        with self.factory.begin(context.scope, 'read') as uow:
            head = uow.workflow.head_ref(WORK_CONTEXT_KIND, stable)
            if head is None:
                raise ApplicationError('WORK_NOT_FOUND')
            body = uow.workflow.read(head)
        binding = decode_work_binding(body)
        if (binding.work_id != validated or binding.stable_id != stable
                or binding.revision != head.revision):
            raise ApplicationError('WORK_BINDING_INVALID')
        return binding

    def read(self, parameters, context, *, read_set=None):
        if type(context) is not CommandContext:
            raise ApplicationError('INVALID_CONTEXT')
        if self.access is None:
            raise ApplicationError('ACCESS_AUTHORITY_UNAVAILABLE')
        self.access.require(context, 'engineering.work.get')
        work_id = self._work_id(parameters)
        stable = f'{WORK_STABLE_ID_PREFIX}{work_id}'
        with self.factory.begin(context.scope, 'read') as uow:
            head = uow.workflow.head_ref(WORK_CONTEXT_KIND, stable)
            if head is None:
                raise ApplicationError('WORK_NOT_FOUND')
            body = uow.workflow.read(head)
        binding = decode_work_binding(body)
        if (binding.work_id != work_id or binding.stable_id != stable
                or binding.revision != head.revision):
            raise ApplicationError('WORK_BINDING_INVALID')
        context_view = WorkContext(work_id, binding.scope, binding.method_ref,
                                   binding.revision, head.digest,
                                   binding.associations).to_dict()
        control, declaration = self._control(context, binding.method_ref)
        context_view['method_control'] = control
        context_view['status'] = ('active' if control is not None and control.get('enabled')
                                 else 'method_unavailable')
        context_view['generation_dispatch'] = generation_dispatch_view(
            self._generation_dispatch(context, work_id))
        context_view['generation_bootstrap'] = self._generation_bootstrap(context, work_id)
        if declaration is None:
            context_view['declared_actions'] = ()
            context_view['actions'] = ()
        else:
            context_view['declared_actions'] = declared_actions(declaration)
            context_view['actions'] = work_actions(
                declaration, binding, control_enabled=bool(control.get('enabled')),
                mapped_steps=self._mapped(), bound_capabilities=self._bound(),
                permit_execute=self.permit_execute, context=context)
        return context_view

    def _generation_dispatch(self, context, work_id):
        """Cold observation of this generation attempt; never authorizes send.

        The stored attempt is looked up by the *current* key and, explicitly, by
        the historical folded form, so a row written before the key fix is found
        instead of reading as absent (a current-key miss must never authorise a
        re-send). A found row is returned with its own original key and bytes and
        `retry_allowed` false; two candidate rows are an ambiguity that must be
        reconciled by name, never guessed.

        This is the *internal* result: it carries the stored binding bytes, which
        a caller holding the record may need. The public read projects it through
        `generation_dispatch_view`, which keeps only the JSON-safe fields.
        """
        from ...contracts.dispatch_identity import (
            historical_identity_agrees, work_dispatch_key_candidates,
        )
        from ordessa_engineering.domain.changes.dispatch_codec import decode_dispatch
        step_id, attempt = 'draft', 1
        action_id = 'incremental.prepare-packages'
        candidates = work_dispatch_key_candidates(work_id, action_id, step_id)
        found = []
        with self.factory.begin(context.scope, 'read') as uow:
            for key in candidates:
                try:
                    found.append((key, uow.work_dispatch.get(key, step_id, attempt,
                                                             context.scope)))
                except ApplicationError as exc:
                    if exc.code in {'NOT_FOUND', 'WORK_DISPATCH_SCHEMA_REQUIRED'}:
                        continue
                    raise
        if not found:
            return None
        if len(found) > 1:
            # Two key forms both carry a row for this step: which one is the real
            # attempt cannot be guessed, so an explicit reconciliation is required.
            raise ApplicationError('WORK_DISPATCH_RECONCILIATION_REQUIRED')
        key, row = found[0]
        binding = decode_dispatch(row['binding_bytes'])
        work = binding.work if type(binding.work) is dict else {}
        if (row['run_id'] != key or row['step_id'] != step_id or row['attempt'] != attempt
                or binding.scope != context.scope
                or binding.run_id != key or binding.step_id != step_id
                or binding.attempt != attempt
                or work.get('dispatch_key') != key or work.get('step_id') != step_id
                # The stored binding must name the *requested* Work and action,
                # not merely agree with its own key: a truncated historical key
                # can collide across distinct Work ids, so a row belonging to
                # another Work must be refused by name rather than reported as
                # this one.
                or work.get('work_id') != work_id or work.get('action_id') != action_id
                or not historical_identity_agrees(key, work.get('work_id'),
                                                  work.get('action_id'), step_id)):
            raise ApplicationError('WORK_DISPATCH_RECONCILIATION_REQUIRED')
        phase = row['dispatch_phase']
        return {'dispatch_key': key, 'step_id': step_id, 'attempt': attempt,
                'phase': phase, 'operation_ref': row['execution_operation_ref'],
                'binding_digest': asdict(row['binding_digest']),
                'binding_bytes': row['binding_bytes'],
                'unknown_requires_reconciliation': phase in {'reserved', 'possibly_written', 'unknown'},
                'retry_allowed': False}

    def _generation_bootstrap(self, context, work_id):
        """Cold read of the Unit-start fence; it never binds a Work dispatch."""
        from ...contracts.dispatch_identity import (
            UNIT_BOOTSTRAP_OPERATION, unit_bootstrap_operation_id,
        )
        operation_id = unit_bootstrap_operation_id(context.scope, work_id)
        with self.factory.begin(context.scope, 'read') as uow:
            entry = uow.commands.find_operation(
                context.scope, operation_id, operation=UNIT_BOOTSTRAP_OPERATION)
        if entry is None:
            return None
        return {
            'operation_id': entry.operation_id,
            'state': entry.state,
            'request_id': entry.key.request_id,
            'unknown_requires_reconciliation': entry.state == 'pending',
            'retry_allowed': False,
        }


def work_context_view(value):
    """Projection for callers that already hold a decoded binding."""
    if value is None:
        return None
    return asdict(value)


# The public view of a generation-dispatch observation holds only fields the
# strict JSON wire accepts. The stored binding *bytes* stay on the internal
# result (`_generation_dispatch`) and are deliberately not copied here: the wire
# encoder refuses bytes, and a public reader is served by the digest.
GENERATION_DISPATCH_PUBLIC_FIELDS = (
    'dispatch_key', 'step_id', 'attempt', 'phase', 'operation_ref',
    'binding_digest', 'unknown_requires_reconciliation', 'retry_allowed',
)


def generation_dispatch_view(value):
    """JSON-safe projection of the internal dispatch observation, or None."""
    if value is None:
        return None
    return {name: value[name] for name in GENERATION_DISPATCH_PUBLIC_FIELDS}


# Dispositions of a declared action for the *current* composition. "available"
# is never derived from a frozen registry name: it requires a composed mapping
# plus the capability actually being bound in this process.
WORK_ACTION_AVAILABLE = 'available'
WORK_ACTION_MISSING_INPUT = 'missing_input'
WORK_ACTION_CONDITION_BLOCKED = 'condition_blocked'
WORK_ACTION_UNSUPPORTED = 'unsupported'
WORK_ACTION_UNKNOWN = 'unknown'


def declared_actions(declaration):
    """Describe exactly what the released method declares; no support claim."""
    actions = []
    for action in getattr(declaration, 'actions', ()) or ():
        actions.append({
            'action_id': action.action_id,
            'admission': [asdict(item) for item in getattr(action, 'admission', ()) or ()],
            'outputs': [asdict(item) for item in getattr(action, 'outputs', ()) or ()],
            'inputs': [{'name': item.name, 'value_kind': item.value_kind}
                       for item in getattr(action, 'inputs', ()) or ()],
            'steps': [{'step_id': step.step_id, 'kind': step.kind, 'name': step.name,
                       'admission': [asdict(item) for item in getattr(step, 'admission', ()) or ()],
                       'inputs': [{'name': item.name,
                                   'source_kind': getattr(item, 'source_kind', None),
                                   'source_name': getattr(item, 'source_name', None),
                                   'step_id': getattr(item, 'step_id', None)}
                                  for item in getattr(step, 'inputs', ()) or ()],
                       'outputs': list(getattr(step, 'outputs', ()) or ())}
                      for step in getattr(action, 'steps', ()) or ()],
        })
    return tuple(actions)


_INPUT_KINDS = {'package_ref': 'package', 'source_ref': 'artifact',
                'artifact_ref': 'artifact', 'submission_ref': 'submission',
                'proposal_ref': 'proposal'}


def action_input_status(action, binding, *, method_ref):
    """Per declared input: what the Work already holds and what the caller supplies.

    Two categories are kept apart on purpose:

    work_bound       - the Work itself already pins it (its method, or a matching
                       association), so nothing is asked of the caller.
    caller_supplied  - the caller provides it in the invoke request (a reference,
                       a JSON object, a profile/review selection). It is NOT an
                       obstacle: requiring every declared input to be pre-bound to
                       the Work would make the action permanently uncallable.
    prerequisite_missing - the method needs a record the Work does not hold and
                       the caller cannot supply. Empty today: no released
                       declaration requires a Work-held record beyond its method.
    """
    status = []
    bound_kinds = {association.kind for association in binding.associations}
    for item in getattr(action, 'inputs', ()) or ():
        kind = _INPUT_KINDS.get(item.value_kind)
        if item.value_kind == 'method_ref':
            status.append({'name': item.name, 'value_kind': item.value_kind,
                           'source': 'work_bound', 'satisfied': True,
                           'reason': 'pinned_by_work'})
        elif kind is not None and kind in bound_kinds:
            status.append({'name': item.name, 'value_kind': item.value_kind,
                           'source': 'work_bound', 'satisfied': True,
                           'reason': 'bound_association'})
        else:
            status.append({'name': item.name, 'value_kind': item.value_kind,
                           'source': 'caller_supplied', 'satisfied': None,
                           'reason': 'provided_at_invoke'})
    return tuple(status)


GUARD_STEP = 'declared-step-guard'
"""Marks a declared step this composition implements as a guard over real records.

Such a step is mapped (never `unsupported`) but consumes no command capability,
so it is never reported as an unbound capability either.
"""


def action_disposition(action, binding, *, method_ref, control_enabled, mapped_steps,
                       bound_capabilities, execute_permitted=False):
    """The one determination both the status read and any invoke must reuse.

    available     - control enabled, the caller holds the execute permission for
                    this action, every declared step mapped to a capability that
                    this process actually bound, and no prerequisite is missing.
    missing_input - a prerequisite record the Work must hold is missing.
    condition_blocked - the method is disabled, the caller has no execute
                    permission, or a mapped capability is not bound in this
                    composition (for example real dispatch).
    unsupported   - a declared step has no composed mapping at all.
    unknown       - an obstacle that cannot be established either way.

    Read permission is enforced separately by the owning query; execute
    permission participates here, so a read-only caller never sees `available`.
    All observed obstacles are reported in `reasons`; `disposition` is the
    strongest one, so one obstacle never hides another.
    """
    inputs = action_input_status(action, binding, method_ref=method_ref)
    steps = list(getattr(action, 'steps', ()) or ())
    mapped = [(step.name, mapped_steps.get(step.name)) for step in steps]
    unmapped = tuple(name for name, capability in mapped if capability is None)
    unbound = tuple(capability for _, capability in mapped
                    if capability is not None and capability != GUARD_STEP
                    and capability not in bound_capabilities)
    missing = tuple(item['name'] for item in inputs if item['source'] == 'prerequisite_missing')
    unknown_inputs = tuple(item['name'] for item in inputs
                           if item['source'] != 'prerequisite_missing'
                           and item['satisfied'] is None and item.get('unresolved'))
    reasons = []
    if not control_enabled:
        reasons.append('METHOD_DISABLED')
    if unmapped:
        reasons.append('ACTION_STEP_NOT_MAPPED')
    if unbound:
        reasons.append('CAPABILITY_NOT_BOUND')
    if not execute_permitted:
        reasons.append('ACTION_EXECUTE_NOT_PERMITTED')
    if missing:
        reasons.append('WORK_PREREQUISITE_MISSING')
    if unknown_inputs:
        reasons.append('WORK_INPUT_STATE_UNKNOWN')
    if not control_enabled:
        disposition = WORK_ACTION_CONDITION_BLOCKED
    elif unmapped:
        disposition = WORK_ACTION_UNSUPPORTED
    elif unbound or not execute_permitted:
        disposition = WORK_ACTION_CONDITION_BLOCKED
    elif missing:
        disposition = WORK_ACTION_MISSING_INPUT
    elif unknown_inputs:
        disposition = WORK_ACTION_UNKNOWN
    else:
        disposition = WORK_ACTION_AVAILABLE
    return {'disposition': disposition, 'reason': reasons[0] if reasons else None,
            'reasons': tuple(reasons), 'inputs': inputs,
            'unmapped_steps': unmapped, 'unbound_capabilities': unbound,
            'missing_prerequisites': missing,
            'execute_permitted': bool(execute_permitted)}


def work_actions(declaration, binding, *, control_enabled, mapped_steps, bound_capabilities,
                 permit_execute=None, context=None):
    """Declared actions plus their disposition for the current composition."""
    views = []
    for action in getattr(declaration, 'actions', ()) or ():
        capabilities = tuple(mapped_steps.get(step.name)
                             for step in getattr(action, 'steps', ()) or ())
        permitted = bool(callable(permit_execute)
                         and permit_execute(action.action_id, capabilities, context))
        disposition = action_disposition(
            action, binding, method_ref=binding.method_ref, control_enabled=control_enabled,
            mapped_steps=mapped_steps, bound_capabilities=bound_capabilities,
            execute_permitted=permitted)
        views.append({'action_id': action.action_id, **disposition,
                      'steps': [step.name for step in getattr(action, 'steps', ()) or ()]})
    return tuple(views)

