"""Bind the frozen case's original review/report ports to one explicit graph.

This is trusted product assembly for **one explicit declared-Work case**, moved
into the project from the private operator that Codex validated. Its assembly
factories select no reviewer, create no Grant and start no Unit; every owner
passed in is already the original one.

The optional report-correction adapter has explicit create/capture/close methods
over the public Unit API and a strictly read-only file callback. Only those
explicit methods perform native interaction. They never detach an Engineering
guard or introduce a process launcher, model client or record authority.

Two entry points, both pure:

``build_declared_work_case_ports``
    Build the declared-review plan factory, the native reviewer source, the
    review admission, the reviewer assignments, the declared review runner and
    the schema-17 report source over the caller's original owners.

``apply_declared_work_case_ports``
    The single ``replace(ports, ...)`` that installs those values, keeps the
    caller's dispatch binder and explicitly leaves the generation binder unset
    (this case is one declared implementation, not a second generation chain).

Call order in the explicit case (unchanged from the handed-off operator):

1. the chat binding configures ``ports`` on the already built graph;
2. this module builds the review/report owners (once);
3. the caller binds native dispatch (``bind_engineering_native_dispatch`` with
   ``review_prompt_source=case_ports.review_runtime``);
4. this module's ``apply_declared_work_case_ports`` installs everything in one
   ``replace``.

Deliberately absent: a default reviewer, a default Profile revision, a default
check command, a Grant, a Unit, model credentials, any fallback when a port is
missing. A missing input refuses with a typed code instead of guessing, which is
why the reviewer source stays a required argument until the original owner hands
over the helper that produced it.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from collections.abc import Mapping
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path

from ordessa_execution_agents.profiles import ProfileRevisionRef
from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_infrastructure.identifiers import RequestKey
from ordessa_engineering.adapters.decision.source_reviewer import DecisionReviewerSource
from ordessa_engineering.domain.common.models.identity import ActorRef
from ordessa_engineering.adapters.declared_implementation_review import (
    DeclaredImplementationReviewBindings,
)
from ordessa_engineering.adapters.native_records import DeclaredUnitReviewRuntime
from ordessa_engineering.adapters.native_records.declared_reviewer import (
    DeclaredUnitReviewerSource,
)
from ordessa_engineering.application.api import ApplicationError
from ordessa_engineering.application.assembly import (
    build_declared_unit_report_source,
    build_reviewer_assignment_usecases,
)
from ordessa_engineering.application.usecases.reviews.admission import (
    EngineeringReviewAdmission,
)

REVIEW_CAPABILITY = 'engineering.reviewer.unit'
DEFAULT_REVIEW_TIMEOUT = 1800


@dataclass(frozen=True, slots=True)
class DeclaredWorkCasePorts:
    """The exact original owners this case binds; carries no policy of its own."""

    review_plan_factory: object
    review_run: object
    review_admission: object
    reviewer_assignments: object
    submission_report_source: object
    review_runtime: object


def _plain(value):
    from ordessa_infrastructure.encoding.immutable_json import safe_json
    return json.loads(safe_json(value))


def _callables(value, names):
    return all(callable(getattr(value, name, None)) for name in names)


def _require_owner(owner, method_control, blobs, factory):
    """Every original owner must be the one this graph was built over."""
    if (factory is None or owner is None
            or getattr(method_control, 'factory', None) is not factory
            or getattr(blobs, 'authority_id', None) != getattr(factory, 'authority_id', None)
            or getattr(owner, 'records', None) is None
            or getattr(getattr(owner, 'profile_service', None), 'get_revision', None) is None
            or not callable(getattr(owner, 'authorize_acp_turn_query', None))):
        raise ApplicationError('DECLARED_WORK_CASE_OWNER_UNAVAILABLE')
    permission = getattr(owner, 'permission', None)
    revision = getattr(permission, 'profile_revision', None)
    if type(revision) is not ProfileRevisionRef:
        # The reviewer Profile revision is the frozen one on the original Unit
        # permission; it is never supplied by a caller or guessed here.
        raise ApplicationError('DECLARED_WORK_CASE_REVIEWER_PROFILE_UNAVAILABLE')
    if (not _callables(method_control, ('guard', 'resource_ref', 'read_resource'))
            or not _callables(blobs, ('read_verified', 'put_verified'))):
        raise ApplicationError('DECLARED_WORK_CASE_OWNER_UNAVAILABLE')
    return permission, revision


def _require_scope(scope, permission):
    if (getattr(scope, 'realm_id', None) is None or getattr(scope, 'project_id', None) is None
            or (scope.realm_id, scope.project_id)
               != (permission.scope.realm_id, permission.scope.project_id)):
        raise ApplicationError('DECLARED_WORK_CASE_SCOPE_MISMATCH')


def _require_reviewer_source(reviewer_source, *, factory, blobs, method_control,
                             source_materials, source_review_bindings, wire_scope,
                             caller, expected_selection):
    """The reviewer source is the base assembly's own DecisionReviewerSource.

    The explicit graph passes ``holder['reviewer']`` straight through: an
    original-caller/policy/evidence owner built over *this same* factory, blobs,
    Method control, source materials and review bindings. A type check alone is
    not enough - an empty shell or a reviewer built over another graph would
    pass it - so the graph identity, the host caller and the fixed selection are
    all bound here against values supplied by the owner handoff, never read back
    from the object's private state.

    ``expected_selection`` is the handoff's own ``(ActorRef, roles, trust_version)``
    tuple; the object must already be that reviewer, not merely look like one.
    Runtime trust (stopped source, swapped principal) is re-checked by
    ``verify_reviewer_before_use`` against the original owner's own guard.
    """
    if (type(reviewer_source) is not DecisionReviewerSource
            or not _callables(reviewer_source, ('verify_response', 'guard_trust'))):
        raise ApplicationError('DECLARED_WORK_CASE_REVIEWER_SOURCE_UNAVAILABLE')
    missing = tuple(name for name in ('factory', 'blobs', 'method_guard', 'materials',
                                      'bindings', 'scope', 'services', 'principal_id',
                                      'reviewer', 'roles', 'trust_version')
                    if not hasattr(reviewer_source, name))
    if missing:
        raise ApplicationError('DECLARED_WORK_CASE_REVIEWER_SOURCE_UNAVAILABLE')
    if (reviewer_source.factory is not factory
            or reviewer_source.blobs is not blobs
            or reviewer_source.method_guard is not method_control
            or reviewer_source.materials is not source_materials
            or reviewer_source.bindings is not source_review_bindings):
        raise ApplicationError('DECLARED_WORK_CASE_REVIEWER_GRAPH_MISMATCH')
    reviewer_scope = reviewer_source.scope
    if (getattr(reviewer_scope, 'realm_id', None), getattr(reviewer_scope, 'project_id', None)) \
            != (wire_scope.realm_id, wire_scope.project_id):
        raise ApplicationError('DECLARED_WORK_CASE_REVIEWER_SCOPE_MISMATCH')
    host_principal = getattr(caller, 'principal_id', None)
    if type(host_principal) is not str or not host_principal:
        raise ApplicationError('DECLARED_WORK_CASE_CALLER_UNAVAILABLE')
    if reviewer_source.principal_id != host_principal:
        raise ApplicationError('DECLARED_WORK_CASE_REVIEWER_PRINCIPAL_MISMATCH')
    if (type(expected_selection) is not tuple or len(expected_selection) != 3
            or type(expected_selection[0]) is not ActorRef
            or type(expected_selection[1]) is not tuple or not expected_selection[1]
            or type(expected_selection[2]) is not int):
        raise ApplicationError('DECLARED_WORK_CASE_REVIEWER_SELECTION_MISMATCH')
    actual = (reviewer_source.reviewer, reviewer_source.roles, reviewer_source.trust_version)
    if actual != expected_selection:
        raise ApplicationError('DECLARED_WORK_CASE_REVIEWER_SELECTION_MISMATCH')
    services = reviewer_source.services
    if (getattr(services, 'mode', None) != 'real'
            or getattr(getattr(services, 'evidence', None), 'durable', None) is not True):
        raise ApplicationError('DECLARED_WORK_CASE_REVIEWER_SERVICE_UNAVAILABLE')
    return reviewer_source


def verify_reviewer_before_use(reviewer_source, context):
    """Delegate reviewer trust to the original owner's public guard.

    ``DecisionReviewerSource.guard_trust`` re-verifies active state, context
    scope and principal, the fixed selection and the provider pins through the
    owner's own code path; an empty record tuple is enough to ask "is this
    reviewer still trusted for this context". No private member is touched and
    no part of the check is reimplemented here.
    """
    if type(reviewer_source) is not DecisionReviewerSource:
        raise ApplicationError('DECLARED_WORK_CASE_REVIEWER_SOURCE_UNAVAILABLE')
    try:
        with reviewer_source.guard_trust(context, ()):
            pass
    except BaseException as error:
        raise ApplicationError('DECLARED_WORK_CASE_REVIEWER_UNTRUSTED') from error
    return True


def _require_review_paths(review_paths):
    """The reviewer's read evidence must be one fixed set of real absolute paths."""
    if type(review_paths) is not tuple or not review_paths:
        raise ApplicationError('DECLARED_WORK_CASE_REVIEW_PATHS_INVALID')
    paths = tuple(Path(path) for path in review_paths)
    for path in paths:
        if (not path.is_absolute() or path.resolve() != path
                or any(part.is_symlink() for part in (path, *path.parents))):
            raise ApplicationError('DECLARED_WORK_CASE_REVIEW_PATHS_INVALID')
    return paths


def _reviewer_query(owner, access, wire_scope):
    """Original reviewer-unit read: one admitted Engineering context, no new store."""

    def query(context, ref, operation, digest):
        if access.current_context() is not context:
            raise ApplicationError('DECLARED_WORK_CASE_CONTEXT_REQUIRED')
        with access.guard_current_capability(context, wire_scope, REVIEW_CAPABILITY):
            key = hashlib.sha256(canonical_bytes({
                'request': context.request_id, 'unit': _plain(ref),
                'operation': operation, 'digest': digest,
                'reader_permission': owner.permission.identity})).hexdigest()
            request = RequestKey(
                owner.admission.environment_namespace,
                owner.permission.principal_scope,
                'review-read-' + key[:48])
            return owner.authorize_acp_turn_query(
                owner.authorization(), request, ref, operation,
                expected_prompt_input_digest=digest)

    return query


def _unit_query(query):
    """Reviewer-Unit reference read, pinned to this plan/version/fence only."""

    def unit_query(context, ref, plan, request, *, purpose):
        operation = 'review-unit-ref/' + purpose + '/' + plan.plan_digest.hex
        digest = 'sha256:' + hashlib.sha256(canonical_bytes({
            'ref': ref, 'plan': asdict(plan.plan_digest),
            'version': request.version, 'fence': request.fence})).hexdigest()
        ticket = query(context, ref, operation, digest)
        return ticket, ticket.facts['inputDigest']

    return unit_query


@dataclass(frozen=True)
class _HistoricalReviewAuthorIdentity:
    """An authorized immutable author identity, never a historical live Unit."""
    factory: object
    access: object
    records: object
    owner: object
    unit_query: object

    def __call__(self, context, ref, plan, request):
        if self.access.current_context() is not context:
            raise ApplicationError('UNIT_REVIEW_AUTHORITY_UNAVAILABLE')
        # The original owner verifies the current caller/profile and original
        # preparation before issuing this exact native read. Its owner-only
        # identity projection below preserves the historical execution fence.
        ticket, digest = self.unit_query(context, ref, plan, request, purpose='author')
        if ticket.facts.get('inputDigest') != digest:
            raise ApplicationError('UNIT_REVIEW_AUTHORITY_UNAVAILABLE')
        original = self.records.owner_read_unit_for_query(ref)
        return _plain(original.public_ref)


@dataclass(frozen=True)
class _ReportCorrectionPorts:
    """Finite owner reads; all format and business decisions stay in Engineering."""
    factory: object
    blobs: object
    records: object
    access: object
    owner: object
    scope: object
    paths: tuple
    sources: dict

    @contextmanager
    def _guard(self, context):
        if self.access.current_context() is not context:
            raise ApplicationError('REPORT_CORRECTION_CONTEXT_REQUIRED')
        for capability in ('engineering.work.invoke', 'engineering.submissions.record_report'):
            try:
                self.access.require(context, capability)
            except ApplicationError:
                continue
            with self.access.guard_current_capability(context, self.scope, capability):
                yield
            return
        raise ApplicationError('REPORT_CORRECTION_CONTEXT_REQUIRED')

    def query(self, context, unit_ref, operation_ref, prompt_digest):
        with self._guard(context):
            key = hashlib.sha256(canonical_bytes({
                'request': context.request_id, 'unit': _plain(unit_ref),
                'operation': operation_ref, 'digest': prompt_digest,
                # A reopen issues a new read under the CURRENT real owner.
                # Its native intent contains this permission identity; it
                # cannot replay an old reader's fixed query reservation.
                'reader_permission': self.owner.permission.identity})).hexdigest()
            request = RequestKey(self.owner.admission.environment_namespace,
                self.owner.permission.principal_scope, 'report-read-' + key[:48])
            return self.owner.authorize_acp_turn_query(
                self.owner.authorization(), request, unit_ref, operation_ref,
                expected_prompt_input_digest=prompt_digest)

    def read_unit(self, context, unit_ref):
        with self._guard(context):
            digest = 'sha256:' + hashlib.sha256(canonical_bytes(_plain(unit_ref))).hexdigest()
            invocation = self.query(context, unit_ref, 'report-correction-unit/' + digest[7:], digest)
            original = self.records.owner_read_unit_for_query(unit_ref)
            # authorize_acp_turn_query revalidates the ORIGINAL preparation's
            # profile_snapshot_ref/agent/environment against this permission.
            # The profile below is therefore not inferred from caller text.
            from ordessa_execution_agents.profiles import encode_revision_ref
            return {'unit_ref': _plain(original.public_ref),
                'profile_ref': encode_revision_ref(self.owner.permission.profile_revision),
                'stop_record': _plain(self.records.owner_read_termination(unit_ref['unitId'], 'stop')),
                'release_record': _plain(self.records.owner_read_termination(unit_ref['unitId'], 'release'))}

    def read_material(self, context, kind, locator):
        with self._guard(context):
            expected = None
            if kind == 'repository_file':
                if type(locator) is not str or locator not in {str(path) for path in self.paths}:
                    raise ApplicationError('REPORT_CORRECTION_MATERIAL_UNAVAILABLE')
                path = Path(locator)
            elif kind in ('original_journal', 'original_check_excerpt'):
                if locator != self.sources['origin_operation_ref']:
                    raise ApplicationError('REPORT_CORRECTION_MATERIAL_UNAVAILABLE')
                selected = self.sources[kind]
                path, expected = Path(selected['path']), selected['digest']['hex']
                if kind == 'original_journal':
                    # The finite path selection is not proof of its origin.
                    # Bind the journal directory to the actual recorded Unit's
                    # private profile roots, after an authorized owner read.
                    from ordessa_engineering.domain.changes.dispatch_codec import decode_dispatch
                    with self.factory.begin(context.scope, 'read') as uow:
                        row = uow.work_dispatch.by_operation(locator, context.scope)
                        binding = decode_dispatch(row['binding_bytes'])
                    ref = json.loads(binding.unit_ref_bytes)
                    invocation = self.query(context, ref, locator,
                        'sha256:' + binding.prompt_input_digest.hex)
                    unit = self.records.owner_read_unit_for_query(ref)
                    sessions = Path(unit.facts['privateRootFacts']['profile']) / 'sessions'
                    if path.suffix != '.jsonl' or not path.is_relative_to(sessions):
                        raise ApplicationError('REPORT_CORRECTION_MATERIAL_UNAVAILABLE')
            else:
                raise ApplicationError('REPORT_CORRECTION_MATERIAL_UNAVAILABLE')
            if (not path.is_absolute() or '..' in path.parts or path.resolve() != path
                    or any(part.is_symlink() for part in (path, *path.parents))):
                raise ApplicationError('REPORT_CORRECTION_MATERIAL_UNAVAILABLE')
            try:
                with path.open('rb') as handle:
                    raw = handle.read(8 * 1024 * 1024 + 1)
            except OSError as error:
                raise ApplicationError('REPORT_CORRECTION_MATERIAL_UNAVAILABLE') from error
            if (len(raw) > 8 * 1024 * 1024
                    or expected is not None and hashlib.sha256(raw).hexdigest() != expected):
                raise ApplicationError('REPORT_CORRECTION_MATERIAL_CHANGED')
            return raw


def _report_correction_ports(*, factory, blobs, access, wire_scope, owner, paths, sources):
    if sources is None:
        return None
    selected = _plain(sources)
    if (type(selected) is not dict or set(selected) != {
            'origin_operation_ref', 'original_journal', 'original_check_excerpt'}
            or type(selected['origin_operation_ref']) is not str
            or not selected['origin_operation_ref']):
        raise ApplicationError('REPORT_CORRECTION_MATERIAL_UNAVAILABLE')
    for name in ('original_journal', 'original_check_excerpt'):
        value = selected[name]
        if (type(value) is not dict or set(value) != {'path', 'digest'}
                or type(value['path']) is not str
                or type(value['digest']) is not dict
                or set(value['digest']) != {'algorithm', 'hex'}
                or value['digest']['algorithm'] != 'sha256'
                or type(value['digest']['hex']) is not str
                or len(value['digest']['hex']) != 64
                or any(c not in '0123456789abcdef' for c in value['digest']['hex'])):
            raise ApplicationError('REPORT_CORRECTION_MATERIAL_UNAVAILABLE')
        _require_review_paths((value['path'],))
    return _ReportCorrectionPorts(factory, blobs, owner.records, access, owner,
                                  wire_scope, paths, selected)


def report_correction_file_approval(*, runtime, permission, environment_instance, allowed_paths):
    """Keep the original permission/path gate, with only read callbacks admitted."""
    from .unit_file_callback_approval import UnitFileCallbackApproval
    from ordessa_units.api import UnitApiRefused
    paths = _require_review_paths(tuple(allowed_paths))

    @contextmanager
    def read_only(*, unit_ref, session_id, method, params):
        tool = params.get('toolCall') if isinstance(params, Mapping) else None
        if not (method == 'fs/read_text_file' or method == 'session/request_permission'
                and isinstance(tool, Mapping) and tool.get('kind') == 'read'):
            raise UnitApiRefused('Report correction permits only original file reads')
        yield

    return UnitFileCallbackApproval(runtime=runtime, permission=permission,
        environment_instance=environment_instance, allowed_paths=tuple(map(str, paths)),
        scope_guard=read_only)


class _ReportCorrectionUnitAssembly:
    """One read-only public Unit interaction, never an Engineering dispatch."""
    def __init__(self, owner, factory, access, blobs, context, timeout, *, operation_prefix,
                 before_native_prompt=None):
        if (access.current_context() is not context
                or context.scope.realm_id != owner.permission.scope.realm_id
                or context.scope.project_id != owner.permission.scope.project_id
                or context.principal_id != owner.permission.principal.principal_id):
            raise ApplicationError('REPORT_CORRECTION_CONTEXT_REQUIRED')
        access.require(context, 'engineering.work.invoke')
        self.owner, self.factory, self.access, self.blobs = owner, factory, access, blobs
        self.context, self.timeout = context, timeout
        self._operation_prefix = operation_prefix
        self._unit, self._params, self._operation = None, None, None
        self._creation_attempted = False
        self._sent, self._capture = False, None
        self._closed = None
        if before_native_prompt is not None and not callable(before_native_prompt):
            raise ApplicationError('REPORT_CORRECTION_SOURCE_INVALID')
        self._before_native_prompt = before_native_prompt

    def _current(self):
        # Qualification used the actual Work admission above. The standalone
        # Unit then uses its own live UnitRunPermission for every operation;
        # no Engineering authority lease may cover its worker-thread effects.
        # Final report admission rechecks the Work/Grant through the Service.
        if self.owner.effect_write_guard_factory is not None:
            raise ApplicationError('REPORT_CORRECTION_STANDALONE_OWNER_REQUIRED')
        self.owner.ensure_unit_creation_ready()

    def create_read_only_unit(self, params, operation_ref):
        self._current()
        if (self._creation_attempted or self._unit is not None or type(params) is not dict or not params
                or 'sessionId' in params or type(operation_ref) is not str
                or not operation_ref.startswith(self._operation_prefix)
                or len(operation_ref) != len(self._operation_prefix) + 64
                or any(c not in '0123456789abcdef' for c in operation_ref.rsplit('/', 1)[1])
                or any(name in params for name in ('on_request', 'before_write',
                    'effect_write_guard', 'effect_write_guard_factory'))):
            raise ApplicationError('REPORT_CORRECTION_INPUT_INVALID')
        self._creation_attempted = True
        unit = self.owner.manager.create(self.owner.spec, self.owner.authorization())
        self._unit, self._params, self._operation = unit, _plain(params), operation_ref
        return unit

    def capture_unit_output(self, unit, operation_ref):
        self._current()
        if unit is not self._unit or operation_ref != self._operation:
            raise ApplicationError('REPORT_CORRECTION_SOURCE_INVALID')
        if self._capture is not None:
            return dict(self._capture)
        if not self._sent:
            if self._before_native_prompt is not None:
                self._before_native_prompt(self.owner, unit)
            self._sent = True
            unit.interaction(self.owner.authorization()).prompt(
                self._params, timeout=self.timeout, operation_ref=operation_ref)
        # A repeated observation may query the original attempt; it must never
        # send again, including after an earlier response/capture failure.
        params = dict(self._params, sessionId=unit.snapshot()['sessionId'])
        digest = self.owner.records.acp_prompt_input_digest(unit.identity, params)
        request = RequestKey(self.owner.admission.environment_namespace,
            self.owner.permission.principal_scope,
            'report-capture-' + hashlib.sha256(operation_ref.encode()).hexdigest()[:48])
        query = self.owner.authorize_acp_turn_query(self.owner.authorization(), request,
            unit.identity, operation_ref, expected_prompt_input_digest=digest)
        from ordessa_engineering.application.usecases.changes.execution_capture import capture_execution_observation
        from ordessa_engineering.domain.common.models.values import Digest
        observation = capture_execution_observation(self.owner.records, self.blobs,
            authority_id=self.factory.authority_id, unit_ref=_plain(unit.identity),
            operation_ref=operation_ref, expected_prompt_digest=digest,
            query_invocation=query, max_receipt_bytes=self.owner.records.acp_turn_evidence_max_bytes)
        receipt = json.loads(self.blobs.read_verified(observation.blob_ref))
        summary = receipt.get('summary', {})
        if (observation.state != 'completed' or summary.get('successfulRpcResponse') is not True
                or type(summary.get('text')) is not str or not summary['text']):
            raise ApplicationError('REPORT_CORRECTION_RECONCILE_REQUIRED')
        try:
            raw = canonical_bytes(json.loads(summary['text']))
        except (ValueError, TypeError, UnicodeError) as error:
            raise ApplicationError('REPORT_CORRECTION_OUTPUT_INVALID') from error
        output = self.blobs.put_verified(raw, Digest('sha256', hashlib.sha256(raw).hexdigest()),
                                         'application/json')
        self._capture = {'unit_ref': _plain(unit.identity), 'operation_ref': operation_ref,
            'output_bytes': raw, 'prompt_input_digest': asdict(Digest('sha256', digest[7:])),
            'observation_ref': asdict(observation.blob_ref),
            'observation_revision': observation.revision}
        self._output = output
        return dict(self._capture)

    def confirm_unit_closed(self, unit):
        self._current()
        if unit is not self._unit:
            raise ApplicationError('REPORT_CORRECTION_SOURCE_INVALID')
        if self._closed is not None:
            return dict(self._closed)
        stop = _plain(self.owner.records.owner_read_termination(unit.identity['unitId'], 'stop'))
        release = _plain(self.owner.records.owner_read_termination(unit.identity['unitId'], 'release'))
        # The original owner-retention loop may already have closed this Unit.
        # Read that result without issuing a second native termination.
        if not (isinstance(stop, dict) and stop.get('state') == 'confirmed'
                and isinstance(release, dict) and release.get('state') == 'confirmed'):
            closed = unit.close(self.owner.authorization())
            if closed.get('state') != 'confirmed':
                raise ApplicationError('REPORT_CORRECTION_RECONCILE_REQUIRED')
            stop = _plain(self.owner.records.owner_read_termination(unit.identity['unitId'], 'stop'))
            release = _plain(self.owner.records.owner_read_termination(unit.identity['unitId'], 'release'))
        if (not isinstance(stop, dict) or stop.get('state') != 'confirmed'
                or not isinstance(release, dict) or release.get('state') != 'confirmed'):
            raise ApplicationError('REPORT_CORRECTION_RECONCILE_REQUIRED')
        from ordessa_engineering.domain.common.models.values import Digest
        # Preserve complete owner projections, including all identity fields.
        def digest(value):
            return asdict(Digest('sha256', hashlib.sha256(canonical_bytes(value)).hexdigest()))
        self._closed = {'stop_confirmed': True, 'release_confirmed': True,
            'output_ref': None if self._capture is None else asdict(self._output),
            'stop_record_digest': digest(stop), 'release_record_digest': digest(release)}
        return dict(self._closed)


def build_report_correction_unit_assembly(*, owner, factory, access, blobs, context, timeout=1800):
    return _build_report_unit_assembly(owner=owner, factory=factory, access=access,
        blobs=blobs, context=context, timeout=timeout, operation_prefix='report-format-rework/')


def build_report_content_rework_unit_assembly(*, owner, factory, access, blobs, context, timeout=1800,
                                            before_native_prompt=None):
    """Select the distinct, one-shot report-content operation purpose."""
    return _build_report_unit_assembly(owner=owner, factory=factory, access=access,
        blobs=blobs, context=context, timeout=timeout, operation_prefix='report-content-rework/',
        before_native_prompt=before_native_prompt)


def _build_report_unit_assembly(*, owner, factory, access, blobs, context, timeout, operation_prefix,
                                before_native_prompt=None):
    from ordessa_units.assembly import LocalUnitOwner
    from ordessa_engineering.application.contracts.commands import CommandContext
    if (type(owner) is not LocalUnitOwner or type(context) is not CommandContext
            or getattr(blobs, 'authority_id', None) != getattr(factory, 'authority_id', None)
            or owner.acp_turn_opt_in is not True or owner.manager is None
            or owner.permission.access_authority is not getattr(access, 'authority', None)
            or type(timeout) not in (int, float) or not 0 < timeout <= 3600):
        raise ApplicationError('REPORT_CORRECTION_SOURCE_UNAVAILABLE')
    _require_scope(context.scope, owner.permission)
    result = _ReportCorrectionUnitAssembly(owner, factory, access, blobs, context, timeout,
        operation_prefix=operation_prefix, before_native_prompt=before_native_prompt)
    result._current()
    return result


def build_declared_work_case_ports(
    *,
    factory,
    access,
    wire_scope,
    owner,
    method_control,
    blobs,
    source_materials,
    source_review_bindings,
    reviewer_source,
    expected_selection,
    caller,
    review_paths,
    before_review=None,
    timeout=DEFAULT_REVIEW_TIMEOUT,
    report_correction_sources=None,
    report_content_rework_approval=None,
    before_review_native_prompt=None,
) -> DeclaredWorkCasePorts:
    """Build this case's review/report owners over the caller's original graph.

    All inputs are trusted composition values: the original UoW factory, the
    original Engineering access authority, the original Unit owner (records,
    profile service, fixed permission), the original Method/Blob owners, the
    original review source ports and the base assembly's ``DecisionReviewerSource``
    (``holder['reviewer']`` in the explicit graph). Nothing is read from request
    JSON, configuration files or environment variables.
    """
    permission, revision = _require_owner(owner, method_control, blobs, factory)
    _require_scope(wire_scope, permission)
    if (getattr(source_materials, 'factory', None) is not factory
            or getattr(source_review_bindings, 'factory', None) is not factory):
        raise ApplicationError('DECLARED_WORK_CASE_SOURCE_UNAVAILABLE')
    reviewer_source = _require_reviewer_source(
        reviewer_source, factory=factory, blobs=blobs, method_control=method_control,
        source_materials=source_materials, source_review_bindings=source_review_bindings,
        wire_scope=wire_scope, caller=caller, expected_selection=expected_selection)
    review_paths = _require_review_paths(review_paths)
    if before_review is not None and not callable(before_review):
        raise ApplicationError('DECLARED_WORK_CASE_REVIEW_HOOK_INVALID')

    # One plan producer serves both roles: the declared review plan factory and
    # the admission's declared-submission binding port.
    plan_factory = DeclaredImplementationReviewBindings(
        factory, method_control, owner.profile_service, revision)
    query = _reviewer_query(owner, access, wire_scope)
    correction = _report_correction_ports(factory=factory, blobs=blobs, access=access,
        wire_scope=wire_scope, owner=owner, paths=review_paths, sources=report_correction_sources)
    report_source = build_declared_unit_report_source(
        factory, method_control=method_control, blobs=blobs, correction_ports=correction,
        content_rework_approval=report_content_rework_approval)
    source = DeclaredUnitReviewerSource(
        factory, access=access, scope=wire_scope, methods=method_control,
        bindings=plan_factory, records=owner.records, blobs=blobs,
        query_factory=query, source_reviewer=reviewer_source,
        review_paths=review_paths, report_source=report_source)
    unit_query = _unit_query(query)
    historical_author = (None if report_correction_sources is None else
        _HistoricalReviewAuthorIdentity(factory, access, owner.records, owner, unit_query))
    assignments = build_reviewer_assignment_usecases(
        factory, method_control=method_control, records=owner.records,
        expected_access=access, expected_scope=wire_scope,
        unit_query_factory=unit_query, author_identity_resolver=historical_author)

    def content_rework_review_guard(context, plan, request=None, *, prompt_context=None):
        targets = plan.requirement.expected_targets.targets
        from ordessa_engineering.domain.reviews.refs import SubmissionRef
        submission_targets = tuple(target for target in targets
            if type(target.ref) is SubmissionRef)
        from contextlib import nullcontext
        content_rework = getattr(report_source, 'content_rework', None)
        if content_rework is None or not submission_targets:
            return nullcontext()
        with factory.begin(context.scope, 'read') as uow:
            submissions = tuple(uow.submissions.resolve(target.ref)
                for target in submission_targets)
        matches = tuple(submission for submission in submissions
            if submission.checkpoint_ref is not None
            and content_rework._is_checkpoint(submission.checkpoint_ref))
        if matches:
            if len(targets) != 1 or len(matches) != 1:
                raise ApplicationError('DECLARED_WORK_CASE_REVIEW_TARGET_INVALID')
            return content_rework.guard_review(context, plan, matches[0],
                prompt_context=prompt_context, request=request)
        return nullcontext()

    def reviewer_assignment_guard(context, plan, request, *, prompt_context=None):
        return content_rework_review_guard(context, plan, request,
            prompt_context=prompt_context)

    def native_prompt_guard(context, plan, request, _assignment, permit):
        if permit is None:
            from contextlib import nullcontext
            return nullcontext()
        # The source prepares immutable references while assigning the reviewer.
        # Only the live approval guard is repeated here; the runtime checks the
        # claim/tail in its fresh read UoW alongside request/plan/binding state.
        return permit.guard_native_prompt(context, plan, request)

    admission = EngineeringReviewAdmission(
        factory, method_control, plan_factory, source,
        source_materials=source_materials,
        method_guard=method_control,
        source_review_bindings=source_review_bindings)
    runtime = DeclaredUnitReviewRuntime(
        factory=factory, access=access, owner=owner, blobs=blobs,
        methods=method_control, bindings=plan_factory, assignments=assignments,
        source=source, before_review=before_review, timeout=timeout,
        before_native_prompt=before_review_native_prompt,
        reviewer_assignment_guard=(reviewer_assignment_guard
            if report_content_rework_approval is not None else None),
        native_prompt_guard=(native_prompt_guard
            if report_content_rework_approval is not None else None))
    return DeclaredWorkCasePorts(
        review_plan_factory=plan_factory,
        review_run=runtime.run_review,
        review_admission=admission,
        reviewer_assignments=assignments,
        submission_report_source=report_source,
        review_runtime=runtime,
    )


def build_declared_report_history_query_factory(case_ports):
    """Read frozen report provenance under this reopen's current permission.

    Multiple immutable reports may refer to the same original business turn.
    Their native read reservation must retain the current reader identity,
    which is already part of the selected correction port's request key.
    """
    if type(case_ports) is not DeclaredWorkCasePorts:
        raise ApplicationError('REPORT_CORRECTION_SOURCE_UNAVAILABLE')
    correction = getattr(case_ports.submission_report_source, 'correction_ports', None)
    if (type(correction) is not _ReportCorrectionPorts
            or correction.owner is not case_ports.review_runtime.owner):
        raise ApplicationError('REPORT_CORRECTION_SOURCE_UNAVAILABLE')

    def query(binding):
        from ordessa_engineering.domain.changes.dispatch import DispatchBinding
        from ordessa_engineering.domain.changes.dispatch_codec import decode_dispatch
        context = correction.access.current_context()
        if (type(binding) is not DispatchBinding or binding.binding_version != 2
                or binding.subject.get('subject_kind') != 'frozen_package'
                or context is None or binding.scope != context.scope):
            raise ApplicationError('REPORT_CORRECTION_SOURCE_INVALID')
        with correction.factory.begin(context.scope, 'read') as uow:
            row = uow.work_dispatch.by_operation(binding.execution_operation_ref, context.scope)
            if row['dispatch_phase'] != 'completed' or decode_dispatch(row['binding_bytes']) != binding:
                raise ApplicationError('REPORT_CORRECTION_SOURCE_INVALID')
        unit = json.loads(binding.unit_ref_bytes)
        prompt = 'sha256:' + binding.prompt_input_digest.hex
        if correction.records.acp_turn_query_digest(unit, binding.execution_operation_ref, prompt) != binding.expected_query_digest:
            raise ApplicationError('REPORT_CORRECTION_SOURCE_INVALID')
        return correction.query(context, unit, binding.execution_operation_ref, prompt)

    return query


def apply_declared_work_case_ports(
    ports,
    *,
    case_ports: DeclaredWorkCasePorts,
    execution_records,
    execution_query_factory,
    execution_dispatch_binder,
):
    """Install this case's ports in one place, keeping the dispatch binder.

    ``execution_records``/``execution_query_factory``/``execution_dispatch_binder``
    stay caller-supplied: they come from the selected Unit owner and must be the
    *same* records/blobs this case's review runtime was built over (a build that
    only needs the review/report owners may pass ``None`` for the binder)
    (``build_local_dispatch_bindings`` + ``bind_engineering_native_dispatch``),
    which this module neither builds nor replaces. The generation binder is
    unset on purpose - this graph is one declared implementation.
    """
    if type(case_ports) is not DeclaredWorkCasePorts:
        raise ApplicationError('DECLARED_WORK_CASE_PORTS_UNAVAILABLE')
    if (execution_records is None or not callable(execution_query_factory)
            or (execution_dispatch_binder is not None
                and not callable(execution_dispatch_binder))):
        raise ApplicationError('DECLARED_WORK_CASE_DISPATCH_UNAVAILABLE')
    runtime = case_ports.review_runtime
    if execution_records is not getattr(getattr(runtime, 'owner', None), 'records', None):
        # A dispatch record owner from another graph would journal the receipt
        # outside this case's Unit owner.
        raise ApplicationError('DECLARED_WORK_CASE_RECORDS_GRAPH_MISMATCH')
    if getattr(ports, 'blobs', None) is not getattr(runtime, 'blobs', None):
        # The Blob authority carries the report/observation bytes; a different
        # one would split the same case across two store identities.
        raise ApplicationError('DECLARED_WORK_CASE_BLOB_GRAPH_MISMATCH')
    correction = getattr(case_ports.submission_report_source, 'correction_ports', None)
    if correction is not None:
        if (type(correction) is not _ReportCorrectionPorts
                or correction.owner is not runtime.owner
                or correction.records is not execution_records
                or correction.access is not runtime.access):
            raise ApplicationError('REPORT_CORRECTION_SOURCE_UNAVAILABLE')
        # The caller selects the original historical query for this explicit
        # recovery graph. Retain that exact callable in both Service and its
        # canonical dispatch binder; changing only one breaks owner identity.
    return replace(
        ports,
        declared_generation_binder=None,
        execution_dispatch_binder=execution_dispatch_binder,
        review_admission=case_ports.review_admission,
        reviewer_assignments=case_ports.reviewer_assignments,
        review_run=case_ports.review_run,
        review_plan_factory=case_ports.review_plan_factory,
        submission_report_source=case_ports.submission_report_source,
        execution_records=execution_records,
        execution_query_factory=execution_query_factory,
    )


__all__ = [
    'report_correction_file_approval',
    'build_report_correction_unit_assembly',
    'build_report_content_rework_unit_assembly',
    'DeclaredWorkCasePorts',
    'DEFAULT_REVIEW_TIMEOUT',
    'verify_reviewer_before_use',
    'apply_declared_work_case_ports',
    'build_declared_work_case_ports',
    'build_declared_report_history_query_factory',
]
