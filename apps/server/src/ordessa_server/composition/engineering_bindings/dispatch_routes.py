"""Original reconcile/readback consumers; native send uses the public Service."""
from ordessa_infrastructure.encoding import decode_json
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.implementation_routes import (
    IMPLEMENTATION_COMMANDS, IMPLEMENTATION_QUERIES,
)
from ordessa_engineering.domain.changes.agent_dispatch_codec import (
    decode_agent_dispatch, SCHEMA_VERSION, PRE_F2_SCHEMA_VERSION, WORK_SCHEMA_VERSION,
)
from ordessa_engineering.domain.changes.dispatch_codec import decode_dispatch
from ordessa_engineering.application.contracts.dispatch_identity import is_work_key


def _stored_binding_kind(raw):
    """Closed stored format selection; decoder errors never trigger fallback."""
    value = decode_json(raw)
    if type(value) is not dict:
        raise ApplicationError('DISPATCH_BINDING_FORMAT_UNAVAILABLE')
    if value.get('schemaVersion') in (SCHEMA_VERSION, PRE_F2_SCHEMA_VERSION, WORK_SCHEMA_VERSION):
        return 'agent'
    if ('schemaVersion' not in value and 'unit_ref_bytes' in value
            and value.get('binding_version', 1) in (1, 2)):
        return 'historical-unit'
    raise ApplicationError('DISPATCH_BINDING_FORMAT_UNAVAILABLE')


class HistoricalUnitDispatchRead:
    """Original persisted Unit bindings only, without Unit construction or send.

    The caller reads the row through the original admitted scoped repository.
    No current liveness or newly reconciled outcome is inferred from old data.
    """
    @staticmethod
    def binding(row):
        binding = decode_dispatch(row['binding_bytes'])
        if ((binding.run_id, binding.step_id, binding.attempt) !=
                (row['run_id'], row['step_id'], row['attempt'])
                or binding.execution_operation_ref != row['execution_operation_ref']
                or binding.fence != row['dispatch_fence']):
            raise ApplicationError('DISPATCH_RECEIPT_BINDING_MISMATCH')
        return binding

DISPATCH_COMMANDS = IMPLEMENTATION_COMMANDS
DISPATCH_QUERIES = IMPLEMENTATION_QUERIES


class EngineeringDispatchRoutes:
    """One original UoW/Agent source and optional same-factory MethodRun binding.

    Actual Agent reads independently authorize the original persisted TurnRef.
    Source snapshot/selection remain separate current original ports. No Grant,
    private Manager lock or application query/operation mapping is created.
    """
    def __init__(self, factory, access, *, execution=None, blobs=None, approvals=None,
                 selection=None, submission_source=None, registry_loader=None,
                 source_snapshots=None, history_sources=None, method_runs=None,
                 method_guard=None, source_materials=None):
        self.factory, self.access = factory, access
        self.execution, self.blobs, self.approvals = execution, blobs, approvals
        self.selection = selection
        self.submission_source, self.registry_loader = submission_source, registry_loader
        self.source_snapshots, self.history_sources = source_snapshots, history_sources
        if method_runs is not None and getattr(method_runs,'factory',None) is not factory:
            raise ApplicationError('DISPATCH_WORK_BINDING_AUTHORITY_UNAVAILABLE')
        self.method_runs = method_runs
        self.method_guard, self.source_materials = method_guard, source_materials

    def _execution(self):
        from ordessa_engineering.adapters.native_records.agent_recorded_dispatch import RecordedDispatchExecution
        if type(self.execution) is not RecordedDispatchExecution or self.execution.blobs is not self.blobs:
            raise ApplicationError('DISPATCH_EXECUTION_AUTHORITY_UNAVAILABLE')
        return self.execution

    @staticmethod
    def _fields(params, expected):
        if type(params) is not dict or set(params) != set(expected):
            raise ApplicationError('INVALID_ARGUMENT')

    @staticmethod
    def _stored_row(uow, params, scope):
        repository = uow.work_dispatch if is_work_key(params['run_id']) else uow.dispatch
        if repository is None:
            raise ApplicationError('DISPATCH_SCHEMA_REQUIRED')
        return repository.get(params['run_id'], params['step_id'], params['attempt'], scope)

    def invoke(self, operation, params, context):
        self.access.require(context, operation)
        if operation == DISPATCH_QUERIES[0]:
            self._fields(params, ('run_id','step_id','attempt'))
            with self.factory.begin(context.scope, 'read') as uow:
                row = self._stored_row(uow, params, context.scope)
                kind = _stored_binding_kind(row['binding_bytes'])
                if kind == 'historical-unit':
                    binding = HistoricalUnitDispatchRead.binding(row)
                else:
                    binding = decode_agent_dispatch(row['binding_bytes'])
                    binding.require_turn_binding()
                return {'run_id':row['run_id'],'step_id':row['step_id'],'attempt':row['attempt'],
                    'phase':row['dispatch_phase'],'version':row['dispatch_version'],'fence':row['dispatch_fence'],
                    'binding':binding.projection(), 'historical':kind == 'historical-unit',
                    'result_blob_ref':None if row['result_blob_json'] is None else decode_json(row['result_blob_json']),
                    'accepted':False,'engineering_completed':False}
        if operation == 'engineering.implementation.reconcile':
            self._fields(params, ('run_id','step_id','attempt'))
            with self.factory.begin(context.scope, 'read') as uow:
                row = self._stored_row(uow, params, context.scope)
                if _stored_binding_kind(row['binding_bytes']) == 'historical-unit':
                    # No historical Unit read authority is bound here. Never
                    # reconstruct its runtime or upgrade stored data to a fresh
                    # native observation. The public get_dispatch stays usable.
                    HistoricalUnitDispatchRead.binding(row)
                    raise ApplicationError('HISTORICAL_DISPATCH_READ_AUTHORITY_UNBOUND')
            execution = self._execution()
        else:
            raise ApplicationError('OPERATION_UNAVAILABLE')
        from ordessa_engineering.application.orchestration.steps.implementation_dispatch import ImplementationDispatch
        service = ImplementationDispatch(self.factory,self.access,approval_usecases=self.approvals,
            execution=execution,selection=self.selection,blobs=self.blobs,registry_loader=self.registry_loader,
            source_snapshots=self.source_snapshots,history_sources=self.history_sources,
            method_runs=self.method_runs,method_guard=self.method_guard,source_materials=self.source_materials)
        if is_work_key(params['run_id']):
            return service.reconcile_agent_work(params['run_id'],params['step_id'],params['attempt'],context)
        return service.reconcile_agent(params['run_id'],params['step_id'],params['attempt'],context)
