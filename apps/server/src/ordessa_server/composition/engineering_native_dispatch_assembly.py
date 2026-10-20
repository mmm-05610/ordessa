"""Bind canonical Engineering dispatch to the selected original Unit owners."""
from __future__ import annotations

from contextlib import contextmanager
from collections.abc import Mapping

from ordessa_engineering.application.api import (
    DispatchBinding,
    EngineeringService,
    ApplicationError,
)
from ordessa_engineering.application.assembly import bind_execution_dispatch
from ordessa_engineering.adapters.native_records import (
    RecordedDispatchExecution,
    engineering_effect_write_guard_factory,
)
from ordessa_engineering.application.contracts.dispatch_identity import (
    work_dispatch_key_candidates,
)
from ordessa_engineering.application.contracts.work_context import WorkBinding
from ordessa_engineering.domain.approvals.implementation import WorkPackageAuthorization
from ordessa_engineering.domain.approvals.scope import EnvironmentRef
from ordessa_engineering.domain.changes.dispatch_codec import decode_dispatch
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_execution_agents.profiles import (
    ProfileRevisionRef, decode_revision_ref, encode_revision_ref,
)
from ordessa_infrastructure.encoding import decode_json
from ordessa_infrastructure.encoding.immutable_json import safe_json
from ordessa_units.assembly import LocalUnitOwner
from ordessa_units.public import AgentOwnerUnavailable, UnitServices


_DEFERRED_FACTORY_REQUIRED = (
    "Original effect-write factory finalization is required before Unit creation"
)
_GENERATION_ACTION_ID = "incremental.prepare-packages"
_GENERATION_STEP_ID = "draft"


def _effect_factory_state(owner, supplied):
    """Read the original factory or prove this owner is explicitly deferred."""
    current = getattr(owner, "effect_write_guard_factory", None)
    if current is not None:
        if (supplied is not None and supplied is not current
                or not callable(current)
                or not callable(getattr(current, "guard_effect_handoff", None))):
            raise ApplicationError("DISPATCH_ORIGINAL_UNIT_OWNER_UNAVAILABLE")
        return current, False
    if supplied is not None or getattr(owner, "acp_turn_opt_in", None) is not True:
        raise ApplicationError("DISPATCH_ORIGINAL_UNIT_OWNER_UNAVAILABLE")
    ensure_ready = getattr(owner, "ensure_unit_creation_ready", None)
    if not callable(ensure_ready):
        raise ApplicationError("DISPATCH_ORIGINAL_UNIT_OWNER_UNAVAILABLE")
    try:
        ready = ensure_ready()
    except AgentOwnerUnavailable as error:
        if str(error) == _DEFERRED_FACTORY_REQUIRED:
            return None, True
        raise ApplicationError("DISPATCH_ORIGINAL_UNIT_OWNER_UNAVAILABLE") from error
    if ready is not True:
        raise ApplicationError("DISPATCH_ORIGINAL_UNIT_OWNER_UNAVAILABLE")
    # An opted-in owner with no factory but no outstanding deferred finalizer
    # is an ordinary unguarded owner and cannot serve canonical dispatch.
    raise ApplicationError("DISPATCH_ORIGINAL_UNIT_OWNER_UNAVAILABLE")


class _OriginalUnitDispatchExecution:
    """Resolve each call to the same retained Unit, records, and live lease."""

    def __init__(self, owner, services, records, blobs, query_factory, effect_factory):
        owner_ports = getattr(getattr(owner, "admission", None), "owner_ports", None)
        original_manager = getattr(owner_ports, "unit_manager", None)
        current_factory, deferred = _effect_factory_state(owner, effect_factory)
        if (type(owner) is not LocalUnitOwner or type(services) is not UnitServices
                or original_manager is None
                or services.unit_manager is not original_manager
                or owner.records is not records
                or not callable(getattr(records, "acp_prompt_input_digest", None))
                or not callable(getattr(records, "acp_turn_query_digest", None))
                or not callable(getattr(records, "query_acp_turn", None))
                or not callable(getattr(query_factory, "__call__", None))
                or not callable(getattr(blobs, "read_verified", None))
                or not callable(getattr(blobs, "put_verified", None))
                or (current_factory is not None
                    and not callable(getattr(current_factory, "guard_effect_handoff", None)))):
            raise ApplicationError("DISPATCH_ORIGINAL_UNIT_OWNER_UNAVAILABLE")
        self.owner = owner
        self.services = services
        self.records = records
        self.blobs = blobs
        self.query_factory = query_factory
        self.effect_write_guard_factory = current_factory
        self.deferred_effect_write_guard_factory = deferred

    def finalize_effect_write_guard_factory(self, factory):
        if (self.deferred_effect_write_guard_factory is not True
                or getattr(self.owner, "effect_write_guard_factory", None) is not factory
                or not callable(factory)
                or not callable(getattr(factory, "guard_effect_handoff", None))):
            raise ApplicationError("DISPATCH_ORIGINAL_UNIT_OWNER_UNAVAILABLE")
        self.effect_write_guard_factory = factory
        self.deferred_effect_write_guard_factory = False

    def _current_effect_write_guard_factory(self):
        factory = getattr(self.owner, "effect_write_guard_factory", None)
        if (factory is None or factory is not self.effect_write_guard_factory
                or not callable(factory)
                or not callable(getattr(factory, "guard_effect_handoff", None))):
            raise ApplicationError("DISPATCH_ORIGINAL_UNIT_OWNER_UNAVAILABLE")
        return factory

    def _binding(self, value):
        if type(value) is not DispatchBinding:
            raise ApplicationError("RECORDED_DISPATCH_BINDING_REQUIRED")
        return value

    def _native(self, unit_ref):
        if not isinstance(unit_ref, Mapping):
            raise ApplicationError("RECORDED_DISPATCH_UNIT_REF_INVALID")
        try:
            unit = self.owner.manager.get(unit_ref)
            authorization = self.owner.authorization()
            instance = self.owner.native_unit(unit, authorization)
            lease = self.owner.authorize("interaction", unit, authorization)
        except Exception as error:
            raise ApplicationError("DISPATCH_ORIGINAL_UNIT_OWNER_UNAVAILABLE") from error
        if getattr(instance, "records", None) is not self.records:
            raise ApplicationError("DISPATCH_ORIGINAL_UNIT_RECORDS_MISMATCH")
        return instance, lease

    def _recorded(self, unit_ref, *, live=True):
        if live:
            instance, lease = self._native(unit_ref)
        else:
            instance, lease = None, None
        return RecordedDispatchExecution(
            self.records, instance, lease, self.blobs, self.query_factory,
            effect_write_guard_factory=self._current_effect_write_guard_factory(),
        )

    def freeze_input(self, unit_ref, params):
        return self._recorded(unit_ref).freeze_input(unit_ref, params)

    def query_digest(self, unit_ref, operation_ref, prompt_digest):
        return self._recorded(unit_ref, live=False).query_digest(
            unit_ref, operation_ref, prompt_digest,
        )

    @contextmanager
    def guard_effect_handoff(self, context, binding, *, access, timeout=60):
        binding = self._binding(binding)
        unit_ref = decode_json(binding.unit_ref_bytes)
        execution = self._recorded(unit_ref)
        with execution.guard_effect_handoff(
            context, binding, access=access, timeout=timeout,
        ):
            yield

    def send(self, binding, *, timeout=60):
        binding = self._binding(binding)
        unit_ref = decode_json(binding.unit_ref_bytes)
        return self._recorded(unit_ref).send(binding, timeout=timeout)

    def failure_diagnostic(self, binding, error, stage):
        """Read the recorded evidence without live owner/factory state.

        Constructing another execution here made a bounded read depend on the
        factory this execution was bound with, so a later owner change dropped
        the evidence the exception already carried. The binding and the
        exception are the whole input; no Unit, store or permission is read.
        """
        binding = self._binding(binding)
        from ordessa_engineering.adapters.native_records.recorded_dispatch import (
            failure_diagnostic)
        return failure_diagnostic(binding, error, stage)

    def capture(self, binding):
        binding = self._binding(binding)
        return self._recorded(
            decode_json(binding.unit_ref_bytes), live=False).capture(binding)



def _native_execution(service, runtime, *, services, records, blobs, query_factory,
                      effect_write_guard_factory):
    owner = getattr(runtime, "unit_execution_owner", None)
    owner_ports = getattr(getattr(owner, "admission", None), "owner_ports", None)
    original_manager = getattr(owner_ports, "unit_manager", None)
    if (type(service) is not EngineeringService or owner is None
            or type(owner) is not LocalUnitOwner
            or type(services) is not UnitServices
            or getattr(runtime, "units", None) is not owner.manager
            or original_manager is None
            or services.unit_manager is not original_manager
            or owner.records is not records):
        raise ApplicationError("DISPATCH_ORIGINAL_UNIT_OWNER_UNAVAILABLE")
    execution = _OriginalUnitDispatchExecution(
        owner, services, records, blobs, query_factory, effect_write_guard_factory,
    )
    return owner, execution


def _generation_unit_resolver(owner, service, execution, blobs):
    def resolve_generation_unit(context, work_binding, profile_ref):
        generation_owner = service.declared_generation_dispatch
        factory = getattr(generation_owner, "factory", None)
        if (factory is None or getattr(generation_owner, "access", None) is None
                or getattr(generation_owner, "blobs", None) is not blobs
                or getattr(generation_owner, "execution", None) is not execution):
            raise ApplicationError("WORK_ACTION_GENERATION_UNIT_UNAVAILABLE")
        permission = getattr(owner, "permission", None)
        profiles = getattr(owner, "profile_service", None)
        try:
            if type(profile_ref) is not ProfileRevisionRef:
                profile_ref = decode_revision_ref(profile_ref)
        except Exception:
            raise ApplicationError("WORK_ACTION_GENERATION_PROFILE_MISMATCH") from None
        if (type(profile_ref) is not ProfileRevisionRef or permission is None
                or profile_ref != getattr(permission, "profile_revision", None)
                or profiles is None):
            raise ApplicationError("WORK_ACTION_GENERATION_PROFILE_MISMATCH")
        try:
            profile = profiles.get(profile_ref.profile_id)
            revision = profiles.get_revision(profile_ref)
            if profile.archived_at is not None or revision.ref != profile_ref:
                raise ApplicationError("WORK_ACTION_GENERATION_PROFILE_MISMATCH")
        except ApplicationError:
            raise
        except Exception as error:
            raise ApplicationError("WORK_ACTION_GENERATION_PROFILE_UNAVAILABLE") from error

        work_id = getattr(work_binding, "work_id", None)
        if (type(work_id) is not str or not work_id
                or getattr(work_binding, "scope", None) != context.scope):
            raise ApplicationError("WORK_ACTION_GENERATION_WORK_IDENTITY_INVALID")
        action_id, step_id = _GENERATION_ACTION_ID, _GENERATION_STEP_ID
        # A miss under the current key must never authorise a re-send: this Work
        # step may already be recorded under the explicit historical folded form
        # written before the key fix. Both candidate keys are read, and a hit
        # keeps its own key and its own stored bytes. Two candidate rows carrying
        # this step are an ambiguity that must be reconciled by name, never
        # guessed.
        found = []
        with factory.begin(context.scope, "read") as uow:
            for key in work_dispatch_key_candidates(work_id, action_id, step_id):
                try:
                    found.append(
                        (key, uow.work_dispatch.get(key, step_id, 1, context.scope)))
                except ApplicationError as error:
                    if error.code != "NOT_FOUND":
                        raise
        if len(found) > 1:
            raise ApplicationError("WORK_ACTION_GENERATION_UNIT_RECONCILIATION_REQUIRED")
        if found:
            key, row = found[0]
            if row.get("dispatch_phase") != "completed":
                raise ApplicationError("WORK_ACTION_GENERATION_UNIT_RECONCILIATION_REQUIRED")
            try:
                prior = decode_dispatch(row["binding_bytes"])
                prior_work = prior.work if type(prior.work) is dict else {}
                unit_ref = decode_json(prior.unit_ref_bytes)
                agrees = (prior.scope == context.scope and prior.step_id == step_id
                          and prior.attempt == 1 and row.get("run_id") == key
                          and row.get("step_id") == step_id and row.get("attempt") == 1
                          and prior_work.get("work_id") == work_id
                          and prior_work.get("action_id") == action_id
                          and prior_work.get("step_id") == step_id
                          and prior_work.get("dispatch_key") == key)
            except Exception as error:
                raise ApplicationError("WORK_ACTION_GENERATION_UNIT_BINDING_INVALID") from error
            if not agrees:
                raise ApplicationError("WORK_ACTION_GENERATION_UNIT_RECONCILIATION_REQUIRED")
            # A historical completed record names the original Unit, but the
            # record alone is not proof that Unit still exists. Re-read the
            # original manager handle, its identity and its confirmed state
            # before handing the ref back; a missing or closed Unit is refused by
            # name, and never replaced by a freshly created one.
            try:
                unit = owner.manager.get(unit_ref)
                if (decode_json(safe_json(unit.identity).encode()) != unit_ref
                        or unit.snapshot()['state'] != 'confirmed'):
                    raise ValueError('Original completed dispatch Unit is not available')
            except Exception as error:
                raise ApplicationError(
                    "WORK_ACTION_GENERATION_UNIT_RECONCILIATION_REQUIRED") from error
            return unit_ref

        try:
            bootstrap = getattr(generation_owner.access, 'guard_unit_bootstrap', None)
            reserve = getattr(generation_owner, 'reserve_unit_bootstrap', None)
            complete = getattr(generation_owner, 'complete_unit_bootstrap', None)
            if not all(callable(port) for port in (bootstrap, reserve, complete)):
                raise ApplicationError("WORK_ACTION_GENERATION_BOOTSTRAP_AUTHORITY_UNAVAILABLE")
            reservation = reserve(context, work_binding, encode_revision_ref(profile_ref),
                                  permission.identity)
            if not reservation.created:
                try:
                    result = decode_json(reservation.entry.result_bytes)
                    if type(result) is not dict or set(result) != {'unit_ref'}:
                        raise ValueError('Original bootstrap result is invalid')
                    # Completion records the actual original Unit. A new owner
                    # that cannot read this handle must refuse, never create a
                    # substitute for a completed or unresolved bootstrap.
                    unit = owner.manager.get(result['unit_ref'])
                    if (decode_json(safe_json(unit.identity).encode()) != result['unit_ref']
                            or unit.snapshot()['state'] != 'confirmed'):
                        raise ValueError('Original bootstrap Unit is not available')
                    return result['unit_ref']
                except Exception as error:
                    raise ApplicationError(
                        'WORK_ACTION_GENERATION_UNIT_RECONCILIATION_REQUIRED') from error
            # initialize/session-new revalidate the original Unit permission
            # on the SDK thread. Keep that authority available while the
            # caller waits; Engineering cannot run under its suspended lease.
            with bootstrap(context, permission=permission):
                unit = owner.manager.create(owner.spec, owner.authorization())
            unit_ref = unit.identity
            if (not isinstance(unit_ref, Mapping)
                    or set(unit_ref) != {"environmentNamespace", "unitId",
                                         "ownerProviderRef", "sourceRevision"}):
                raise ValueError("Original Manager returned an invalid Unit identity")
            if (owner.manager.get(unit_ref) is not unit
                    or unit.snapshot()['state'] != 'confirmed'):
                raise ApplicationError('WORK_ACTION_GENERATION_UNIT_RECONCILIATION_REQUIRED')
            plain_ref = decode_json(safe_json(unit_ref).encode("utf-8"))
            complete(context, reservation, plain_ref)
            return plain_ref
        except ApplicationError:
            raise
        except Exception as error:
            raise ApplicationError("WORK_ACTION_GENERATION_UNIT_UNAVAILABLE") from error

    return resolve_generation_unit


def _implementation_unit_resolver(owner, access):
    """Select one existing original Unit; never bootstrap or replace it.

    The public Manager is the inventory. Its original owner revalidates the
    retained handle and current interaction permission; the dispatch adapter
    subsequently holds the original query/session selection fence at each cut.
    A Profile or Environment match is selection data, never a Work write grant.
    """
    def resolve_implementation_unit(context, work, profile_ref, authorization):
        access.require(context, 'engineering.executions.dispatch')
        permission = owner.permission
        if (type(work) is not WorkBinding or work.scope != context.scope
                or type(authorization) is not WorkPackageAuthorization
                or authorization.scope != context.scope
                or authorization.work_id != work.work_id
                or authorization.work_revision != work.revision
                or authorization.method_ref != work.method_ref
                or (permission.scope.realm_id, permission.scope.project_id)
                    != (context.scope.realm_id, context.scope.project_id)):
            raise ApplicationError('WORK_ACTION_IMPLEMENTATION_UNIT_BINDING_INVALID')
        try:
            if type(profile_ref) is not ProfileRevisionRef:
                if not isinstance(profile_ref, Mapping):
                    raise ValueError('Complete Profile revision reference required')
                profile_ref = decode_revision_ref(dict(profile_ref))
            if profile_ref != permission.profile_revision:
                raise ValueError('Profile differs from the original permission')
            profile = owner.profile_service.get(profile_ref.profile_id)
            revision = owner.profile_service.get_revision(profile_ref)
            if profile.archived_at is not None or revision.ref != profile_ref:
                raise ValueError('Original Profile is no longer available')
        except Exception as error:
            raise ApplicationError('WORK_ACTION_IMPLEMENTATION_PROFILE_UNAVAILABLE') from error
        environment = EnvironmentRef(profile_ref.environment_namespace, profile_ref.profile_id,
            Digest('sha256', profile_ref.digest.removeprefix('sha256:')))
        if any(environment not in scope.environment_refs
               for _, scope in authorization.scope_by_action):
            raise ApplicationError('ACTION_SCOPE_NOT_AUTHORIZED')
        expected_environment = {'environmentId': permission.environment_identity}
        candidates = []
        try:
            for unit in owner.manager.list():
                snapshot = unit.snapshot()
                definition = snapshot['definition']
                if (snapshot['state'] != 'confirmed'
                        or definition['agentId'] != permission.agent_id
                        or decode_revision_ref(dict(definition['profileRevision'])) != profile_ref
                        or dict(definition['environmentReference']) != expected_environment):
                    continue
                ref = decode_json(safe_json(unit.identity).encode('utf-8'))
                if (set(ref) != {'environmentNamespace', 'unitId',
                                 'ownerProviderRef', 'sourceRevision'}
                        or ref['environmentNamespace'] != profile_ref.environment_namespace
                        or snapshot['identity'] != unit.identity
                        or owner.manager.get(ref) is not unit):
                    raise ValueError('Original Unit identity changed')
                candidates.append((unit, ref))
        except Exception as error:
            raise ApplicationError('WORK_ACTION_IMPLEMENTATION_UNIT_UNAVAILABLE') from error
        if not candidates:
            raise ApplicationError('WORK_ACTION_IMPLEMENTATION_UNIT_UNAVAILABLE')
        if len(candidates) != 1:
            raise ApplicationError('WORK_ACTION_IMPLEMENTATION_UNIT_AMBIGUOUS')
        unit, ref = candidates[0]
        try:
            # This original-owner read checks current authenticated permission,
            # environment and live records. It creates no Unit or connection.
            owner.native_unit(unit, owner.authorization())
        except Exception as error:
            raise ApplicationError('WORK_ACTION_IMPLEMENTATION_UNIT_UNAVAILABLE') from error
        return ref

    return resolve_implementation_unit


def _continuation_unit_resolver(unit_owner, access_cell):
    """Create one fresh Unit for a claimed continuation, in the owner's order.

    The causal journal row is already claimed by the Service before this runs.
    Order is fixed: reserve the Unit bootstrap (only ``created=True`` may create
    a Unit) -> original ``guard_unit_bootstrap`` -> original Manager create ->
    verify the returned identity is the live confirmed Unit -> leave the guard ->
    complete the bootstrap -> return the plain UnitRef. No generation draft
    reservation is reused, no Unit is created before the claim, and no
    lifecycle ``complete`` is called from here.
    """

    def resolve_continuation_unit(context, candidate, inputs):
        from ordessa_engineering.application.usecases.changes.dispatch_continuation import (
            ContinuationCandidate, continuation_operation_id)
        owner = access_cell.get('owner')
        access = access_cell.get('access')
        permission = getattr(unit_owner, 'permission', None)
        reserve = getattr(owner, 'reserve_continuation_unit_bootstrap', None)
        complete = getattr(owner, 'complete_continuation_unit_bootstrap', None)
        bootstrap = getattr(access, 'guard_unit_bootstrap', None)
        if (type(candidate) is not ContinuationCandidate or permission is None
                or not all(callable(port) for port in (reserve, complete, bootstrap))):
            raise ApplicationError('CONTINUATION_UNIT_AUTHORITY_UNAVAILABLE')
        if (getattr(candidate, 'work', None) is None
                or candidate.work.scope != context.scope):
            raise ApplicationError('CONTINUATION_UNIT_AUTHORITY_UNAVAILABLE')
        # The Service hands this resolver the causal request: the same id the
        # journal claim was created with, never the caller's own request id.
        if context.request_id != continuation_operation_id(context.scope, candidate.origin):
            raise ApplicationError('CONTINUATION_UNIT_AUTHORITY_UNAVAILABLE')
        profile_ref = getattr(permission, 'profile_revision', None)
        owner_identity = getattr(permission, 'identity', None)
        if type(profile_ref) is not ProfileRevisionRef or owner_identity is None:
            raise ApplicationError('CONTINUATION_UNIT_PROFILE_MISMATCH')
        reservation = reserve(context, candidate, encode_revision_ref(profile_ref), owner_identity)
        if getattr(reservation, 'created', None) is not True:
            # An existing pending reservation never authorises a second Unit.
            raise ApplicationError('CONTINUATION_UNIT_RESERVATION_CONFLICT')
        with bootstrap(context, permission=permission):
            unit = unit_owner.manager.create(unit_owner.spec, unit_owner.authorization())
        unit_ref = unit.identity
        if (not isinstance(unit_ref, Mapping)
                or set(unit_ref) != {'environmentNamespace', 'unitId',
                                     'ownerProviderRef', 'sourceRevision'}):
            raise ApplicationError('CONTINUATION_UNIT_AUTHORITY_UNAVAILABLE')
        if (unit_owner.manager.get(unit_ref) is not unit
                or unit.snapshot()['state'] != 'confirmed'):
            raise ApplicationError('CONTINUATION_UNIT_AUTHORITY_UNAVAILABLE')
        # Public Unit identities are recursively sealed views. Detach the full
        # JSON value, including ownerProviderRef, before the Engineering codec.
        public_ref = decode_json(safe_json(unit_ref).encode('utf-8'))
        complete(context, reservation, public_ref)
        return public_ref

    return resolve_continuation_unit


def bind_engineering_native_dispatch(
    service: EngineeringService,
    runtime,
    *,
    services: UnitServices,
    records,
    blobs,
    effect_write_guard_factory=None,
    query_factory,
    selection,
    source_snapshots,
    history_sources,
    implementation_timeout=60,
    review_prompt_source=None,
    continuation=False,
):
    """Bind the public canonical dispatch port to this runtime's original owners.

    Caller supplies the exact query, selection, snapshot, and history ports
    already selected for the same Engineering service. This function creates
    no Unit, records store, permission, guard factory, or fallback route.
    """
    owner, execution = _native_execution(
        service, runtime, services=services, records=records, blobs=blobs,
        query_factory=query_factory,
        effect_write_guard_factory=effect_write_guard_factory,
    )

    resolve_generation_unit = _generation_unit_resolver(owner, service, execution, blobs)

    # The declared generation step reuses this very transport and Service's
    # retained Work dispatch owner. This attachment creates no Unit itself.
    service.attach_declared_generation_handles(
        blobs=blobs, execution=execution,
        unit_ref_resolver=resolve_generation_unit,
    )
    continuation_evidence = None
    continuation_unit_resolver = None
    if continuation:
        # The reader and the query port are the same-graph owners: the reader
        # over the service's own factory/records/blobs, the query port built on
        # the original owner + the access this binder will publish. The query is
        # resolved lazily because the access only exists after the binding.
        from ordessa_engineering.adapters.native_records import (
            NativeContinuationEvidenceReader,
        )
        from ordessa_engineering.adapters.native_records.local_bindings import (
            build_historical_dispatch_query_factory,
        )
        cells = {'owner': None, 'access': None}
        lazy_query = {}
        def historical_query(binding):
            factory = lazy_query.get('query')
            if factory is None:
                raise ApplicationError('CONTINUATION_EVIDENCE_AUTHORITY_UNAVAILABLE')
            return factory(binding)
        continuation_evidence = NativeContinuationEvidenceReader(
            service._factory, records, blobs, historical_query)
        continuation_unit_resolver = _continuation_unit_resolver(
            runtime.unit_execution_owner, cells)
        if (continuation_evidence.factory is not service._factory
                or continuation_evidence.records is not records
                or continuation_evidence.blobs is not blobs):
            raise ApplicationError('CONTINUATION_EVIDENCE_AUTHORITY_UNAVAILABLE')
    canonical_owner = bind_execution_dispatch(
        service,
        execution=execution,
        selection=selection,
        source_snapshots=source_snapshots,
        history_sources=history_sources,
        unit_ref_resolver=_implementation_unit_resolver(
            owner, service.declared_generation_dispatch.access),
        implementation_timeout=implementation_timeout,
        continuation_evidence=continuation_evidence,
        continuation_unit_resolver=continuation_unit_resolver,
    )
    if continuation_unit_resolver is not None:
        cells['owner'] = canonical_owner
        cells['access'] = canonical_owner.access
        lazy_query['query'] = build_historical_dispatch_query_factory(
            runtime.unit_execution_owner, canonical_owner.access)
    if execution.deferred_effect_write_guard_factory:
        # The fixed factory must consume the completed canonical Engineering
        # owner graph, then be installed once through the original Unit owner.
        factory = engineering_effect_write_guard_factory(
            canonical_owner, None, records, blobs,
            generation_dispatch=service.declared_generation_dispatch,
        )
        if review_prompt_source is not None:
            from ordessa_engineering.adapters.native_records import DeclaredUnitReviewRuntime
            if (type(review_prompt_source) is not DeclaredUnitReviewRuntime
                    or review_prompt_source.owner is not owner
                    or review_prompt_source.factory is not canonical_owner.factory
                    or review_prompt_source.access is not canonical_owner.access
                    or review_prompt_source.blobs is not blobs):
                raise ApplicationError('REVIEW_SOURCE_AUTHORITY_MISMATCH')
            factory = review_prompt_source.wrap_dispatch_factory(factory)
        owner.bind_effect_write_guard_factory(factory)
        execution.finalize_effect_write_guard_factory(factory)
    elif review_prompt_source is not None:
        raise ApplicationError('REVIEW_SOURCE_AUTHORITY_MISMATCH')
    return canonical_owner


def bind_engineering_native_generation(
    service: EngineeringService,
    runtime,
    *,
    services: UnitServices,
    records,
    blobs,
    query_factory,
    generation_timeout=60,
    format_rework=None,
):
    """Attach only the declared Work generation owner to the original Unit path.

    This is intentionally separate from the canonical MethodRun dispatcher:
    a schema-17 declared Work has no legacy MethodRunBindings owner. It reuses
    the same LocalUnitOwner, UnitServices, UnitRecords, blob authority and ACP
    transport, and creates no Unit during binding.
    """
    owner, execution = _native_execution(
        service, runtime, services=services, records=records, blobs=blobs,
        query_factory=query_factory,
        effect_write_guard_factory=getattr(
            getattr(runtime, "unit_execution_owner", None),
            "effect_write_guard_factory", None),
    )

    resolve_generation_unit = _generation_unit_resolver(owner, service, execution, blobs)

    service.attach_declared_generation_handles(
        blobs=blobs, execution=execution,
        unit_ref_resolver=resolve_generation_unit,
        generation_timeout=generation_timeout,
        format_rework=format_rework,
    )
    generation_owner = service.declared_generation_dispatch
    if (generation_owner is None
            or service.declared_generation_ready is not True
            or generation_owner.factory is None or generation_owner.access is None
            or generation_owner.blobs is not blobs
            or generation_owner.execution is not execution):
        raise ApplicationError("WORK_ACTION_GENERATION_OWNER_UNAVAILABLE")
    if execution.deferred_effect_write_guard_factory:
        factory = engineering_effect_write_guard_factory(
            None, None, records, blobs, generation_dispatch=generation_owner,
        )
        owner.bind_effect_write_guard_factory(factory)
        execution.finalize_effect_write_guard_factory(factory)
    else:
        # A pre-bound original hook cannot be widened to a new generation owner.
        # Keep the old hook and require the original one-time finalizer instead.
        raise ApplicationError("WORK_ACTION_GENERATION_EFFECT_FACTORY_NOT_DEFERRED")
    return generation_owner


__all__ = ["bind_engineering_native_dispatch", "bind_engineering_native_generation"]
