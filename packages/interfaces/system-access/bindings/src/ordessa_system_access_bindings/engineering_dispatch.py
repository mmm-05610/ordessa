"""Original reconcile/readback consumers; native send uses the public Service."""
from ordessa_infrastructure.encoding import decode_json
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.implementation_routes import (
    IMPLEMENTATION_COMMANDS, IMPLEMENTATION_QUERIES,
)
from ordessa_engineering.domain.changes.dispatch_codec import decode_dispatch
DISPATCH_COMMANDS = IMPLEMENTATION_COMMANDS
DISPATCH_QUERIES = IMPLEMENTATION_QUERIES


class EngineeringDispatchRoutes:
    """One original UoW/Manager and optional same-factory MethodRun binding.

    A Manager lookup authenticates its retained Unit identity but does not
    supply the required checkout/selection guard. No private Manager lock is
    accessed here, and no Grant is issued by this consumer. The opaque
    MethodRunBindings object is forwarded unchanged to Engineering; it creates
    no run, package mapping, Records source, or execution permission.
    """
    def __init__(self, factory, access, *, manager=None, blobs=None, approvals=None,
                 selection=None, query_factory=None, submission_source=None, registry_loader=None,
                 source_snapshots=None, history_sources=None, method_runs=None):
        self.factory, self.access = factory, access
        self.manager, self.blobs, self.approvals = manager, blobs, approvals
        self.selection, self.query_factory = selection, query_factory
        self.submission_source, self.registry_loader = submission_source, registry_loader
        self.source_snapshots, self.history_sources = source_snapshots, history_sources
        if method_runs is not None and getattr(method_runs,'factory',None) is not factory:
            raise ApplicationError('DISPATCH_WORK_BINDING_AUTHORITY_UNAVAILABLE')
        self.method_runs = method_runs

    def _execution(self):
        from ordessa_engineering.adapters.native_records.recorded_dispatch import RecordedDispatchExecution
        if self.manager is None or self.query_factory is None:
            raise ApplicationError('DISPATCH_EXECUTION_AUTHORITY_UNAVAILABLE')
        return RecordedDispatchExecution(self.manager.records, None, None, self.blobs,
            query_factory=self.query_factory)

    @staticmethod
    def _fields(params, expected):
        if type(params) is not dict or set(params) != set(expected):
            raise ApplicationError('INVALID_ARGUMENT')

    def invoke(self, operation, params, context):
        self.access.require(context, operation)
        if operation == DISPATCH_QUERIES[0]:
            self._fields(params, ('run_id','step_id','attempt'))
            with self.factory.begin(context.scope, 'read') as uow:
                if uow.dispatch is None:
                    raise ApplicationError('DISPATCH_SCHEMA_REQUIRED')
                row = uow.dispatch.get(params['run_id'],params['step_id'],params['attempt'],context.scope)
                binding = decode_dispatch(row['binding_bytes'])
                return {'run_id':row['run_id'],'step_id':row['step_id'],'attempt':row['attempt'],
                    'phase':row['dispatch_phase'],'version':row['dispatch_version'],'fence':row['dispatch_fence'],
                    'binding':binding.projection(),
                    'result_blob_ref':None if row['result_blob_json'] is None else decode_json(row['result_blob_json']),
                    'accepted':False,'engineering_completed':False}
        if operation == 'engineering.implementation.reconcile':
            self._fields(params, ('run_id','step_id','attempt'))
            execution = self._execution()
        else:
            raise ApplicationError('OPERATION_UNAVAILABLE')
        from ordessa_engineering.application.orchestration.steps.implementation_dispatch import ImplementationDispatch
        service = ImplementationDispatch(self.factory,self.access,approval_usecases=self.approvals,
            execution=execution,selection=self.selection,blobs=self.blobs,registry_loader=self.registry_loader,
            source_snapshots=self.source_snapshots,history_sources=self.history_sources,
            method_runs=self.method_runs)
        return service.reconcile(params['run_id'],params['step_id'],params['attempt'],context)
