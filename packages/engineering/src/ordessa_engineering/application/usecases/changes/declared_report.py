"""Consume declared Work report bytes through original dispatch and method owners.

No MethodRun, repository snapshot, checkout scan, or execution effect is created.
The report is an authored assertion pending review, never engineering acceptance.
"""
from contextlib import contextmanager
from dataclasses import asdict
from decimal import Decimal
import hashlib
import json
import os

from jsonschema import Draft202012Validator
from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ...contracts.errors import ApplicationError
from ...contracts.execution_observations import MAX_EXECUTION_RECEIPT_BYTES
from .execution_capture import capture_execution_observation
from ..packages.authorization import resolve_work_package_authorization
from .report_source import VerifiedUnitReport
from ....domain.approvals.implementation import WorkPackageAuthorizationIntent
from ....domain.changes.dispatch import package_ref_projection
from ....domain.changes.dispatch_codec import decode_dispatch
from ....domain.changes.submission import Submission
from ....domain.changes.submission_binding import validate_submission_graph
from ....domain.common.mechanisms.codec import canonical_value, decode_blob_ref
from ....domain.common.mechanisms.hashing import record_digest
from ....domain.common.outcomes.diagnostics import ReferenceError
from ....domain.common.models.values import Digest
from ....domain.packages.models import PreparedPackagePayload


def resolve_declared_report_binding(uow, submission):
    """Exact immutable Work attempt lookup; never infer a legacy run or resend."""
    from ....domain.changes.agent_submission_report import AgentSubmissionReport
    if type(submission) is AgentSubmissionReport:
        from .agent_declared_report import resolve_agent_declared_report_binding
        return resolve_agent_declared_report_binding(uow, submission)
    if type(submission) is not Submission or submission.schema_version != 2 or submission.scope != uow.scope:
        raise ApplicationError('SUBMISSION_DISPATCH_BINDING_MISMATCH')
    try:
        row = uow.work_dispatch.by_operation(submission.execution_ref.operation_ref, uow.scope)
    except ApplicationError as error:
        if error.code == 'NOT_FOUND':
            raise ApplicationError('SUBMISSION_DISPATCH_BINDING_UNAVAILABLE') from error
        raise
    binding = decode_dispatch(row['binding_bytes'])
    execution = submission.execution_ref
    unit = {'environmentNamespace': execution.environment_namespace, 'unitId': execution.unit_id,
        'ownerProviderRef': decode_json(execution.owner_provider_ref_bytes), 'sourceRevision': execution.source_revision}
    if (binding.binding_version != 2 or binding.subject != {'subject_kind': 'frozen_package',
                'subject_ref': package_ref_projection(submission.package_ref)}
            or binding.scope != uow.scope or binding.package_ref != submission.package_ref
            or binding.approval_ref is None or submission.authorization_refs != (binding.approval_ref,)
            or binding.execution_operation_ref != execution.operation_ref
            or binding.unit_ref_bytes != canonical_bytes(unit)
            or binding.prompt_input_digest != execution.prompt_input_digest
            or binding.run_id != row['run_id'] or binding.step_id != row['step_id']
            or binding.attempt != row['attempt'] or binding.work['dispatch_key'] != row['run_id']
            or row['execution_operation_ref'] != binding.execution_operation_ref
            or row['dispatch_fence'] != binding.fence
            or row['dispatch_phase'] != 'completed'
            or row['result_blob_json'] != canonical_bytes(asdict(execution.captured_observation_ref)).decode('utf-8')
            or 'implementation_report' not in binding.required_results):
        raise ApplicationError('SUBMISSION_DISPATCH_BINDING_MISMATCH')
    # Repository reads validate the original digest; the comparisons above
    # correlate the row to its binding. Do not mint a new key for a historical row.
    grant = uow.authorization.get_grant(binding.approval_ref)
    if type(grant.intent) is not WorkPackageAuthorizationIntent or grant.intent.digest != binding.intent_digest:
        raise ApplicationError('SUBMISSION_DISPATCH_BINDING_MISMATCH')
    auth = grant.intent.authorization
    work = binding.work
    if (auth.work_id != work['work_id'] or auth.action_id != work['action_id']
            or auth.step_id != work['step_id'] or binding.step_id != auth.step_id
            or not set(a for a, _ in binding.action_instances) <= set(auth.actions)):
        raise ApplicationError('SUBMISSION_DISPATCH_BINDING_MISMATCH')
    facts = resolve_work_package_authorization(uow, auth)
    try:
        validate_submission_graph(submission, facts.package, grant, (), ())
    except ReferenceError as error:
        raise ApplicationError(error.code) from error
    # The report's row must still be the head of a verified causal chain: a
    # continuation attempt inherits the root's original Grant, so a report bound
    # to a re-pointed or broken chain is refused here as well as at the write.
    from .dispatch_continuation import resolve_continuation_root
    root = resolve_continuation_root(uow, binding)
    if root is not None and root.approval_ref != binding.approval_ref:
        raise ApplicationError('REPORT_CONTINUATION_ROOT_MISMATCH')
    return binding


REWORK_PLAN_CONTRACT = 'ordessa.declared-report-format-rework-plan/1'
REWORK_RULE = 'remove-json-object-type-only'
REWORK_CONTRACT = 'ordessa.declared-report-format-rework/1'
REWORK_PLAN_MEDIA_TYPE = 'application/vnd.ordessa.declared-report-rework-plan+json'
CORRECTION_CLAIM_OPERATION = 'engineering.report_correction.claim'
CORRECTION_CLAIM_PREFIX = 'report-correction-claim-'
CORRECTION_OPERATION_PREFIX = 'report-format-rework/'
CORRECTION_LIMITATION = ('selected original Pi journal observation; '
                         'not independently authenticated execution proof')
PARENT_INVOKE_OPERATION = 'engineering.work.invoke'
_SELECTOR_FIELDS = frozenset({'parent_operation_id', 'execution_operation_ref',
                              'expected_parent_version', 'expected_dispatch_version',
                              'expected_observation_revision'})
_EVIDENCE_FIELDS = frozenset({'files', 'check'})
_FILE_FIELDS = frozenset({'path', 'blob_ref'})
_CHECK_FIELDS = frozenset({'origin_operation_ref', 'journal_ref', 'excerpt_ref',
                           'tool_call_id', 'command_digest', 'limitation'})
_SUCCESSOR_CONTRACT = 'ordessa.declared-review-successor-source/1'
_CHECK_OBSERVATION_CONTRACT = 'ordessa.original-check-observation/1'
_SUCCESSOR_FIELDS = frozenset({'review_id', 'operation_ref',
                               'expected_observation_revision', 'observation_ref'})


def _sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def _digest_of(raw):
    return Digest('sha256', _sha256(raw))


def declared_review_operation_ref(plan, assignment):
    """Stable original-Records operation identity for a declared review."""
    try:
        return 'declared-review/' + record_digest('declared-unit-review-source', {
            'plan_digest': asdict(plan.plan_digest), 'assignment': asdict(assignment.ref)}).hex
    except (AttributeError, TypeError, ValueError):
        raise ApplicationError('SUBMISSION_REVIEW_BINDING_MISMATCH') from None


def _method_ref(value):
    from ....domain.artifacts.method_binding import MethodRef
    if type(value) is not dict:
        raise ApplicationError('SUBMISSION_REPORT_CORRECTION_INVALID')
    body = dict(value)
    body['snapshot_digest'] = _exact_digest(Digest(**body['snapshot_digest'])) \
        if type(body.get('snapshot_digest')) is dict else body.get('snapshot_digest')
    return MethodRef(**body)


def _execution_ref(origin, unit, binding):
    from ....domain.changes.submission import ExecutionRecordRef
    return ExecutionRecordRef(
        environment_namespace=unit['environmentNamespace'], unit_id=unit['unitId'],
        owner_provider_ref_bytes=canonical_bytes(unit['ownerProviderRef']),
        source_revision=unit['sourceRevision'],
        operation_ref=origin['execution_operation_ref'],
        prompt_input_digest=binding.prompt_input_digest,
        captured_observation_ref=decode_blob_ref(origin['observation_ref']))


def _as_ref(value):
    if type(value) is not None and hasattr(value, 'digest') and hasattr(value, 'storage_object_id'):
        return value
    return decode_blob_ref(value)


def _exact_digest(value):
    if type(value) is not Digest or value.algorithm != 'sha256' or len(value.hex) != 64:
        raise ApplicationError('SUBMISSION_REPORT_CORRECTION_INVALID')
    return value


def _decode_digest(value):
    """Decode the existing wire projection without accepting loose digests."""
    if type(value) is Digest:
        return _exact_digest(value)
    if type(value) is not dict or set(value) != {'algorithm', 'hex'}:
        raise ApplicationError('SUBMISSION_REPORT_CORRECTION_INVALID')
    try:
        return _exact_digest(Digest(**value))
    except Exception:
        raise ApplicationError('SUBMISSION_REPORT_CORRECTION_INVALID') from None


def _require_same_blob_bytes(blobs, ref, expected, code):
    """Require the supplied source bytes to be stored in this BlobStore too."""
    try:
        stored = blobs.read_verified(ref)
    except Exception:
        raise ApplicationError(code) from None
    if type(stored) is not bytes or stored != expected:
        raise ApplicationError(code)


def _strict_object(value, fields, code='SUBMISSION_REPORT_CORRECTION_INVALID'):
    if type(value) is not dict or set(value) != set(fields):
        raise ApplicationError(code)
    return value


def _profile(value):
    if type(value) is not dict or not value:
        raise ApplicationError('SUBMISSION_REPORT_CORRECTION_PROFILE_MISMATCH')
    # Profile references are public immutable projections. Require canonical
    # JSON values, but leave the profile owner's own schema authoritative.
    try:
        return decode_json(canonical_bytes(value))
    except Exception:
        raise ApplicationError('SUBMISSION_REPORT_CORRECTION_PROFILE_MISMATCH') from None


def _correction_params(plan, plan_ref, schema, rejected_raw):
    files = plan['evidence']['files']
    body = {
        'instruction': ('Read only the supplied paths. Do not edit files, run commands, '
                        'or access any other path. Return only the corrected implementation '
                        'report as strict JSON matching the supplied schema. Preserve the '
                        'rejected report values exactly and remove only its top-level type field.'),
        'report_correction_plan': plan,
        'plan_ref': asdict(plan_ref),
        'rejected_report_utf8': rejected_raw.decode('utf-8'),
        'implementation_report_schema': schema,
        'allowed_read_paths': sorted(item['path'] for item in files),
    }
    return {'prompt': [{'type': 'text', 'text': canonical_bytes(body).decode('utf-8')}]}


def _jsonl_records(raw, *, require_newline=True):
    if type(raw) is not bytes or not raw or len(raw) > MAX_EXECUTION_RECEIPT_BYTES:
        raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CHECK_MISMATCH')
    try:
        def pairs(items):
            value = {}
            for key, item in items:
                if key in value:
                    raise ValueError('duplicate native JSON key')
                value[key] = item
            return value

        def reject_constant(_value):
            raise ValueError('nonfinite native JSON number')

        text = raw.decode('utf-8', errors='strict')
        lines = text.splitlines(keepends=True)
        if not lines or (require_newline and any(not line.endswith('\n') for line in lines)):
            raise ValueError('JSONL requires complete newline terminated records')
        records = []
        for line in lines:
            body = line[:-1] if line.endswith('\n') else line
            if body.endswith('\r'):
                body = body[:-1]
            if not body:
                raise ValueError('empty JSONL record')
            # Pi journals contain native decimal usage/cost metadata. Keep
            # their exact source bytes; they are not canonical domain JSON.
            record = json.loads(body, object_pairs_hook=pairs,
                parse_float=Decimal, parse_constant=reject_constant)
            if type(record) is not dict:
                raise ValueError('JSONL record must be an object')
            records.append((body.encode('utf-8'), record))
        return records
    except ApplicationError:
        raise
    except Exception:
        raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CHECK_MISMATCH') from None


def _check_journal_evidence(journal_raw, excerpt_raw, check, journal_ref, excerpt_ref,
                            command_digest):
    """Bind the selected check excerpt to its exact original Pi permission call.

    This records source lineage only. It does not attest that the command ran or
    create test evidence.
    """
    if (_digest_of(journal_raw) != journal_ref.digest
            or len(journal_raw) != journal_ref.byte_length
            or _digest_of(excerpt_raw) != excerpt_ref.digest
            or len(excerpt_raw) != excerpt_ref.byte_length):
        raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CHECK_MISMATCH')
    records = _jsonl_records(journal_raw)
    selected = _jsonl_records(excerpt_raw, require_newline=False)
    if len(selected) != 1 or selected[0][0] not in {line for line, _ in records}:
        raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CHECK_MISMATCH')
    tool_id = check['tool_call_id']
    # Pi's persisted source is an outer message JSONL record, not ACP JSON-RPC.
    # Correlate it with the separate original UnitRecords receipt.
    calls, results = [], []
    for _line, record in records:
        message = record.get('message')
        if type(message) is not dict:
            continue
        content = message.get('content')
        if type(content) is not list:
            continue
        if message.get('role') == 'assistant':
            for item in content:
                args = item.get('arguments') if type(item) is dict else None
                if (type(item) is dict and item.get('type') == 'toolCall'
                        and item.get('id') == tool_id and item.get('name') == 'bash'
                        and type(args) is dict and type(args.get('command')) is str
                        and args['command']):
                    calls.append(args['command'])
        elif (message.get('role') == 'toolResult'
              and message.get('toolCallId') == tool_id
              and message.get('toolName') == 'bash'
              and message.get('isError') is False):
            results.append(record)
    if len(calls) != 1 or len(results) != 1:
        raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CHECK_MISMATCH')
    command = calls[0]
    if _digest_of(command.encode('utf-8')) != command_digest:
        raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CHECK_MISMATCH')
    excerpt = selected[0][1]
    if (excerpt.get('type') != results[0].get('type')
            or excerpt.get('id') != results[0].get('id')
            or excerpt.get('message') != results[0].get('message')
            or excerpt.get('parentId') != results[0].get('parentId')
            or excerpt.get('timestamp') != results[0].get('timestamp')):
        raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CHECK_MISMATCH')
    return command


def _check_native_permission(receipt, tool_id, command):
    # This confirms only the selected provider-side observation and its
    # host-recorded decision update. It is not authenticated execution proof.
    events = receipt.get('events')
    if type(events) is not list:
        raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CHECK_MISMATCH')
    requests, approvals = [], []
    for event in events:
        raw = event.get('raw') if type(event) is dict else None
        if type(raw) is not dict:
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CHECK_MISMATCH')
        method, params = raw.get('method'), raw.get('params', {})
        if method is None:
            # UnitRecords retains the provider-facing observation stream. The
            # host-to-provider permission reply is not part of this snapshot.
            continue
        if type(params) is not dict:
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CHECK_MISMATCH')
        if method == 'session/request_permission':
            tool = params.get('toolCall')
            raw_input = tool.get('rawInput') if type(tool) is dict else None
            options = params.get('options')
            if params.get('toolCallId') != tool_id:
                continue
            if (type(tool) is not dict or tool.get('toolCallId') != tool_id
                    or tool.get('kind') != 'execute' or params.get('approval') != 'command'
                    or type(raw_input) is not dict or raw_input.get('command') != command
                    or type(options) is not list
                    or sum(1 for item in options if type(item) is dict
                           and item.get('kind') == 'allow_once') != 1
                    or type(raw.get('id')) not in (str, int) or type(raw.get('id')) is bool):
                raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CHECK_MISMATCH')
            allowed_once = [item for item in options if type(item) is dict
                            and item.get('kind') == 'allow_once']
            permission_option_id = allowed_once[0].get('optionId')
            if type(permission_option_id) is not str or not permission_option_id:
                raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CHECK_MISMATCH')
            requests.append(params)
        elif method == 'session/update':
            update = params.get('update')
            observed_tool_id = params.get('toolCallId')
            if type(update) is dict and observed_tool_id is None:
                observed_tool_id = update.get('toolCallId')
            if observed_tool_id != tool_id:
                continue
            if type(update) is not dict or update.get('toolCallId') != tool_id:
                raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CHECK_MISMATCH')
            update_type = update.get('sessionUpdate')
            if update_type == 'tool_call':
                raw_input = update.get('rawInput')
                status = update.get('status')
                if (update.get('kind') not in (None, 'execute')
                        or status not in (None, 'pending', 'in_progress')
                        or (type(raw_input) is dict and raw_input.get('command') != command)):
                    raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CHECK_MISMATCH')
                continue
            if (update_type != 'tool_call_update'
                    or params.get('type') not in (None, 'tool_call_update')):
                raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CHECK_MISMATCH')
            status = params.get('status', update.get('status'))
            decision = params.get('permissionDecision', update.get('permissionDecision'))
            if status == 'in_progress' and decision is None:
                continue
            elif (status == 'completed' and decision == 'approved'
                  and update.get('status') == 'completed'):
                approvals.append(params)
            else:
                raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CHECK_MISMATCH')
    if len(requests) != 1 or len(approvals) != 1:
        raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CHECK_MISMATCH')


def _check_readonly_capture(receipt, allowed_paths):
    events = receipt.get('events')
    if type(events) is not list:
        raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CAPTURE_MISMATCH')
    allowed = set(allowed_paths)
    permissions = {}
    completed = {}
    tool_kinds = {}
    read_paths = []
    for event in events:
        raw = event.get('raw') if type(event) is dict else None
        if type(raw) is not dict:
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CAPTURE_MISMATCH')
        method, params = raw.get('method'), raw.get('params', {})
        if method is None:
            continue
        if type(params) is not dict:
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CAPTURE_MISMATCH')
        if method == 'fs/read_text_file':
            if params.get('path') not in allowed:
                raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CAPTURE_MISMATCH')
            read_paths.append(params['path'])
        elif method == 'session/request_permission':
            tool = params.get('toolCall')
            locations = tool.get('locations') if type(tool) is dict else None
            files = params.get('files')
            tool_id = params.get('toolCallId')
            options = params.get('options')
            if (params.get('approval') != 'file' or type(tool) is not dict
                    or tool.get('kind') != 'read'
                    or type(tool_id) is not str or not tool_id
                    or tool.get('toolCallId') != tool_id or tool_id in permissions
                    or type(locations) is not list or not locations
                    or type(files) is not list or not files
                    or type(options) is not list
                    or sum(1 for item in options if type(item) is dict
                           and item.get('kind') == 'allow_once') != 1
                    or any(type(item) is not dict or type(item.get('optionId')) is not str
                           or not item.get('optionId') for item in options)
                    or any(type(item) is not dict or item.get('path') not in allowed
                           for item in locations)
                    or {item['path'] for item in locations} != set(files)
                    or any(path not in allowed for path in files)):
                raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CAPTURE_MISMATCH')
            if tool_id in tool_kinds and tool_kinds[tool_id] not in (None, 'read'):
                raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CAPTURE_MISMATCH')
            tool_kinds[tool_id] = 'read'
            allow_once = next(item for item in options if item.get('kind') == 'allow_once')
            request_id = raw.get('id')
            if type(request_id) not in (str, int) or type(request_id) is bool:
                raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CAPTURE_MISMATCH')
            permissions[tool_id] = {'request_id': request_id, 'option_id': allow_once['optionId'],
                                    'paths': {item['path'] for item in locations},
                                    'final': False}
        elif method == 'session/update':
            update = params.get('update')
            if type(update) is not dict:
                raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CAPTURE_MISMATCH')
            update_type = update.get('sessionUpdate')
            if update_type == 'tool_call':
                tool_id = update.get('toolCallId')
                if (type(tool_id) is not str or not tool_id
                        or update.get('kind') not in (None, 'read')
                        or update.get('status') not in (None, 'pending', 'in_progress')
                        or tool_id in tool_kinds):
                    raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CAPTURE_MISMATCH')
                tool_kinds[tool_id] = update.get('kind')
            elif update_type == 'tool_call_update':
                tool_id = update.get('toolCallId')
                status = params.get('status', update.get('status'))
                decision = params.get('permissionDecision', update.get('permissionDecision'))
                if (type(tool_id) is not str or not tool_id
                        or tool_kinds.get(tool_id, update.get('kind')) not in (None, 'read')
                        or permissions.get(tool_id, {}).get('final')):
                    raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CAPTURE_MISMATCH')
                if status == 'completed' and decision == 'approved':
                    if (update.get('status', status) != 'completed'
                            or tool_id not in permissions):
                        raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CAPTURE_MISMATCH')
                    permissions[tool_id]['final'] = True
                    completed[tool_id] = True
                elif status == 'in_progress' and decision is None:
                    tool_kinds.setdefault(tool_id, update.get('kind'))
                else:
                    raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CAPTURE_MISMATCH')
            elif update_type in {
                    'user_message_chunk', 'agent_message_chunk', 'agent_thought_chunk',
                    'compaction_summary_chunk', 'usage_update', 'plan', 'plan_update',
                    'plan_removed', 'available_commands_update', 'current_mode_update',
                    'config_option_update', 'session_info_update', 'notice',
                    'compaction_update'}:
                if update_type in {'user_message_chunk', 'agent_message_chunk',
                                   'agent_thought_chunk', 'compaction_summary_chunk'}:
                    content = update.get('content')
                    if (type(content) is not dict or content.get('type') != 'text'
                            or type(content.get('text')) is not str):
                        raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CAPTURE_MISMATCH')
            else:
                raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CAPTURE_MISMATCH')
        else:
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CAPTURE_MISMATCH')
    approved_paths = set().union(*(permissions[tool_id]['paths'] for tool_id in completed)) \
        if completed else set()
    if (set(permissions) != set(completed)
            or any(not item['final'] for item in permissions.values())
            or set(tool_kinds) != set(permissions)
            or not set(read_paths).issubset(approved_paths)):
        raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CAPTURE_MISMATCH')


class DeclaredWorkReportSource:
    """Explicit schema17 report admission using the released declaration, not compilation."""
    declared_work_reports = True

    def __init__(self, factory, method_control, blobs, *, correction_ports=None):
        if (getattr(method_control, 'factory', None) is not factory
                or any(not callable(getattr(method_control, name, None))
                       for name in ('guard', 'resource_ref', 'read_resource'))
                or getattr(blobs, 'authority_id', None) != getattr(factory, 'authority_id', None)
                or any(not callable(getattr(blobs, name, None)) for name in ('read_verified', 'put_verified'))):
            raise ApplicationError('SUBMISSION_REPORT_AUTHORITY_MISMATCH')
        self.factory, self.methods, self.blobs = factory, method_control, blobs
        # An optional, trusted host-selected correction port set. When absent the
        # ordinary report path is unchanged and no correction is discoverable.
        if correction_ports is not None:
            self._validate_correction_ports(factory, blobs, correction_ports)
        self.correction_ports = correction_ports
        self.content_rework = None
        if correction_ports is not None:
            from .report_content_rework import ReportContentReworkSource
            self.content_rework = ReportContentReworkSource(self)

    @staticmethod
    def _validate_correction_ports(factory, blobs, ports):
        """The ports must be the same original graph; no default or fallback."""
        if (getattr(ports, 'factory', None) is not factory
                or getattr(ports, 'blobs', None) is not blobs
                or getattr(ports, 'records', None) is None
                or not callable(getattr(getattr(ports, 'access', None), 'require', None))
                or any(not callable(getattr(ports, name, None))
                       for name in ('query', 'read_unit', 'read_material'))):
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_UNAVAILABLE')
        DeclaredWorkReportSource._correction_paths(ports)

    @staticmethod
    def _correction_paths(ports):
        try:
            selected = ports.paths
            if type(selected) not in (tuple, list, frozenset):
                raise ValueError
            paths = tuple(os.fspath(path) for path in selected)
            if (not paths or len(paths) != len(set(paths))
                    or any(type(path) is not str or not path.startswith('/')
                           or path.startswith('//') or '\x00' in path
                           or os.path.normpath(path) != path for path in paths)):
                raise ValueError
        except (AttributeError, TypeError, ValueError):
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_UNAVAILABLE') from None
        return frozenset(paths)

    def _require_correction_file_set(self, files):
        if (type(files) is not list or not files
                or any(type(item) is not dict or set(item) != _FILE_FIELDS
                       or type(item.get('path')) is not str for item in files)):
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_INVALID')
        paths = [item['path'] for item in files]
        if (len(paths) != len(set(paths))
                or set(paths) != self._correction_paths(self.correction_ports)):
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_FILE_INVALID')

    def _require_registered_correction_access(self, context):
        """Authorize only the caller's real request, record, or invoke capability."""
        access = self.correction_ports.access
        last_denial = None
        for operation in ('engineering.reviews.request', 'engineering.reviews.record',
                          'engineering.submissions.record_report',
                          'engineering.work.invoke'):
            try:
                access.require(context, operation)
                return
            except ApplicationError as error:
                last_denial = error
        if last_denial is not None:
            raise last_denial
        raise ApplicationError('SUBMISSION_REPORT_CORRECTION_UNAVAILABLE')

    def _registered_correction(self, context, submission):
        """Read only immutable registered correction/source bytes, outside SQL I/O."""
        from ....application.contracts.commands import CommandContext
        from ....domain.changes.submission import Submission
        if (self.correction_ports is None or type(context) is not CommandContext
                or type(submission) is not Submission or submission.checkpoint_ref is None):
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_UNAVAILABLE')
        if not callable(getattr(self.correction_ports.access, 'require', None)):
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_UNAVAILABLE')
        self._require_registered_correction_access(context)
        # Resolve the exact registered Submission and its immutable dispatch
        # relation in one short read. BlobStore and native/material readers are
        # deliberately used only after the UoW closes.
        with self.factory.begin(context.scope, 'read') as uow:
            registered = uow.submissions.resolve(submission.ref)
            binding = resolve_declared_report_binding(uow, registered)
            package = uow.implementation.resolve_package(registered.package_ref)
        if (registered != submission or registered.scope != context.scope
                or registered.schema_version != 2
                or binding.execution_operation_ref != registered.execution_ref.operation_ref
                or package.ref != registered.package_ref):
            raise ApplicationError('SUBMISSION_REPORT_BINDING_MISMATCH')
        checkpoint_ref = registered.checkpoint_ref
        checkpoint_raw = self.blobs.read_verified(checkpoint_ref)
        _require_same_blob_bytes(self.blobs, checkpoint_ref, checkpoint_raw,
                                 'SUBMISSION_REPORT_BINDING_MISMATCH')
        checkpoint = decode_json(checkpoint_raw)
        if (type(checkpoint) is not dict or set(checkpoint) != {'contract', 'plan_ref', 'correction'}
                or checkpoint.get('contract') != REWORK_CONTRACT
                or type(checkpoint.get('correction')) is not dict
                or set(checkpoint['correction']) != {'unit_ref', 'operation_ref', 'prompt_input_digest',
                    'observation_ref', 'observation_revision', 'output_ref',
                    'stop_record_digest', 'release_record_digest'}):
            raise ApplicationError('SUBMISSION_REPORT_BINDING_MISMATCH')
        plan_ref = _as_ref(checkpoint['plan_ref'])
        plan_raw = self.blobs.read_verified(plan_ref)
        _require_same_blob_bytes(self.blobs, plan_ref, plan_raw,
                                 'SUBMISSION_REPORT_BINDING_MISMATCH')
        plan = decode_json(plan_raw)
        if (type(plan) is not dict or set(plan) != {'contract', 'rule', 'origin', 'evidence'}
                or plan.get('contract') != REWORK_PLAN_CONTRACT or plan.get('rule') != REWORK_RULE
                or type(plan.get('origin')) is not dict or type(plan.get('evidence')) is not dict
                or set(plan['evidence']) != {'files', 'check'}
                or type(plan['evidence']['check']) is not dict
                or set(plan['evidence']['check']) != _CHECK_FIELDS):
            raise ApplicationError('SUBMISSION_REPORT_BINDING_MISMATCH')
        origin, evidence, check, correction = (plan['origin'], plan['evidence'],
                                                plan['evidence']['check'], checkpoint['correction'])
        if (type(origin.get('parent_key')) is not dict
                or set(origin['parent_key']) != {'realm_id', 'principal_id', 'request_id'}
                or set(origin) != {'parent_key', 'parent_operation_id', 'parent_request_digest',
                    'parent_version', 'work_id', 'work_revision', 'work_digest', 'action_id',
                    'step_id', 'package_ref', 'method_ref', 'profile_ref', 'author_unit_ref',
                    'binding_digest', 'dispatch_version', 'execution_operation_ref',
                    'observation_ref', 'observation_revision', 'rejected_report_ref'}
                or origin.get('execution_operation_ref') != binding.execution_operation_ref
                or origin.get('package_ref') != asdict(binding.package_ref)
                or origin.get('method_ref') != asdict(package.payload.method_ref)
                or origin.get('author_unit_ref') != decode_json(binding.unit_ref_bytes)
                or _as_ref(correction.get('output_ref')) not in registered.output_refs
                or type(correction.get('operation_ref')) is not str
                or correction['operation_ref'] != CORRECTION_OPERATION_PREFIX + plan_ref.digest.hex
                or _decode_digest(correction.get('prompt_input_digest')) is None
                or _as_ref(correction.get('observation_ref')) is None
                or type(origin.get('observation_revision')) is not int
                or type(origin['observation_revision']) is bool
                or origin['observation_revision'] < 1):
            raise ApplicationError('SUBMISSION_REPORT_BINDING_MISMATCH')
        self._require_correction_file_set(evidence['files'])
        paths = [item['path'] for item in evidence['files']]
        if paths != sorted(paths):
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_FILE_INVALID')
        for item in evidence['files']:
            ref = _as_ref(item['blob_ref'])
            raw = self.blobs.read_verified(ref)
            if (type(raw) is not bytes or len(raw) != ref.byte_length
                    or _digest_of(raw) != ref.digest):
                raise ApplicationError('SUBMISSION_REPORT_CORRECTION_FILE_MISMATCH')

        original_ref = registered.execution_ref.captured_observation_ref
        if _as_ref(origin['observation_ref']) != original_ref:
            raise ApplicationError('SUBMISSION_REPORT_BINDING_MISMATCH')
        original_raw = self.blobs.read_verified(original_ref)
        _require_same_blob_bytes(self.blobs, original_ref, original_raw,
                                 'SUBMISSION_REPORT_BINDING_MISMATCH')
        original_receipt = canonical_value(original_raw, maximum=MAX_EXECUTION_RECEIPT_BYTES)
        if (original_receipt.get('contractVersion') != 'unit-acp-turn/1'
                or original_receipt.get('unitRef') != decode_json(binding.unit_ref_bytes)
                or original_receipt.get('operationRef') != binding.execution_operation_ref
                or original_receipt.get('inputDigest') != 'sha256:' + binding.prompt_input_digest.hex
                or original_receipt.get('revision') != origin['observation_revision']
                or original_receipt.get('state') != 'completed'
                or type(original_receipt.get('summary')) is not dict
                or original_receipt['summary'].get('successfulRpcResponse') is not True
                or registered.execution_ref.prompt_input_digest != binding.prompt_input_digest):
            raise ApplicationError('SUBMISSION_REPORT_BINDING_MISMATCH')
        request, response = original_receipt.get('request'), original_receipt.get('response')
        events = original_receipt.get('events')
        if (type(request) is not dict or type(request.get('raw')) is not dict
                or request['raw'].get('method') != 'session/prompt'
                or request['raw'].get('params') != original_receipt.get('input', {}).get('params')
                or type(response) is not dict or response.get('jsonrpc') != '2.0'
                or 'result' not in response or 'error' in response
                or type(request['raw'].get('id')) not in (str, int)
                or type(request['raw'].get('id')) is bool
                or canonical_bytes(response.get('id')) != canonical_bytes(request['raw'].get('id'))
                or type(events) is not list
                or response not in [event.get('raw') for event in events if type(event) is dict]):
            raise ApplicationError('SUBMISSION_REPORT_BINDING_MISMATCH')
        rejected_ref = _as_ref(origin['rejected_report_ref'])
        rejected_raw = self.blobs.read_verified(rejected_ref)
        _require_same_blob_bytes(self.blobs, rejected_ref, rejected_raw,
                                 'SUBMISSION_REPORT_BINDING_MISMATCH')
        rejected_text, _expected_report = self._rejected_report_body(
            original_receipt,
            {'expected_observation_revision': origin['observation_revision']})
        if rejected_text != rejected_raw:
            raise ApplicationError('SUBMISSION_REPORT_BINDING_MISMATCH')
        output_ref = _as_ref(correction['output_ref'])
        output_raw = self.blobs.read_verified(output_ref)
        if (len(registered.output_refs) != 1 or registered.output_refs[0] != output_ref
                or output_raw != registered.method_content.value_bytes
                or _digest_of(output_raw) != output_ref.digest
                or len(output_raw) != output_ref.byte_length):
            raise ApplicationError('SUBMISSION_REPORT_BINDING_MISMATCH')
        correction_receipt_ref = _as_ref(correction['observation_ref'])
        correction_raw = self.blobs.read_verified(correction_receipt_ref)
        _require_same_blob_bytes(self.blobs, correction_receipt_ref, correction_raw,
                                 'SUBMISSION_REPORT_BINDING_MISMATCH')
        correction_receipt = canonical_value(correction_raw, maximum=MAX_EXECUTION_RECEIPT_BYTES)
        correction_digest = _decode_digest(correction['prompt_input_digest'])
        if (correction_receipt.get('contractVersion') != 'unit-acp-turn/1'
                or correction_receipt.get('unitRef') != correction.get('unit_ref')
                or correction_receipt.get('operationRef') != correction['operation_ref']
                or correction_receipt.get('inputDigest') != 'sha256:' + correction_digest.hex
                or correction_receipt.get('revision') != correction.get('observation_revision')
                or correction_receipt.get('state') != 'completed'
                or correction_receipt.get('summary', {}).get('successfulRpcResponse') is not True):
            raise ApplicationError('SUBMISSION_REPORT_BINDING_MISMATCH')
        journal_ref, excerpt_ref = _as_ref(check['journal_ref']), _as_ref(check['excerpt_ref'])
        journal_raw = self.blobs.read_verified(journal_ref)
        excerpt_raw = self.blobs.read_verified(excerpt_ref)
        if (type(journal_raw) is not bytes or type(excerpt_raw) is not bytes
                or len(journal_raw) != journal_ref.byte_length
                or _digest_of(journal_raw) != journal_ref.digest
                or len(excerpt_raw) != excerpt_ref.byte_length
                or _digest_of(excerpt_raw) != excerpt_ref.digest
                or check.get('origin_operation_ref') != binding.execution_operation_ref
                or check.get('limitation') != CORRECTION_LIMITATION):
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CHECK_MISMATCH')
        selected_command = _check_journal_evidence(
            journal_raw, excerpt_raw, check, journal_ref, excerpt_ref,
            _decode_digest(check['command_digest']))
        _check_native_permission(original_receipt, check['tool_call_id'], selected_command)
        excerpt_value = _jsonl_records(excerpt_raw, require_newline=False)
        if len(excerpt_value) != 1:
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CHECK_MISMATCH')
        return {'checkpoint_ref': checkpoint_ref, 'plan_ref': plan_ref,
            'plan': plan, 'checkpoint': checkpoint, 'submission': registered,
            'binding': binding, 'package': package, 'original_receipt': original_receipt,
            'original_ref': original_ref, 'journal_ref': journal_ref,
            'excerpt_ref': excerpt_ref, 'journal_raw': journal_raw,
            'excerpt_raw': excerpt_raw, 'command': selected_command,
            'command_digest': _decode_digest(check['command_digest']),
            'tool_call_id': check['tool_call_id'], 'paths': tuple(paths)}

    def correction_review_evidence(self, context, submission):
        """Return the registered correction's bounded historical check observation."""
        from ....domain.changes.submission import Submission
        if type(submission) is not Submission:
            raise ApplicationError('SUBMISSION_REPORT_BINDING_MISMATCH')
        if submission.checkpoint_ref is None:
            return None
        if (self.content_rework is not None
                and self.content_rework._is_checkpoint(submission.checkpoint_ref)):
            return self.content_rework.review_evidence(context, submission)
        source = self._registered_correction(context, submission)
        return {'contract': _CHECK_OBSERVATION_CONTRACT,
            'checkpoint_ref': asdict(source['checkpoint_ref']),
            'plan_ref': asdict(source['plan_ref']),
            'origin_operation_ref': source['binding'].execution_operation_ref,
            'journal_ref': asdict(source['journal_ref']),
            'excerpt_ref': asdict(source['excerpt_ref']),
            'tool_call_id': source['tool_call_id'],
            'command_digest': asdict(source['command_digest']),
            'command_utf8': source['command'],
            'excerpt_utf8': source['excerpt_raw'].decode('utf-8', errors='strict'),
            'files': source['plan']['evidence']['files'],
            'limitation': CORRECTION_LIMITATION}

    def report_content_rework_materials(self, context, submission, *, method_guarded=False):
        """Expose supplemental material only for the registered new report."""
        if self.content_rework is None:
            return None
        return self.content_rework.review_materials(context, submission,
                                                    method_guarded=method_guarded)

    @staticmethod
    def _review_command_failure(receipt, allowed_paths):
        """Qualify one completed observation whose command effects were blocked."""
        events = receipt.get('events')
        if type(events) is not list:
            raise ApplicationError('SUBMISSION_REVIEW_SUCCESSOR_SOURCE_INVALID')
        permissions, reads, updates = {}, {}, {}
        response_ids = set()
        responses_seen = set()
        for event in events:
            raw = event.get('raw') if type(event) is dict else None
            if type(raw) is not dict:
                raise ApplicationError('SUBMISSION_REVIEW_SUCCESSOR_SOURCE_INVALID')
            method, params = raw.get('method'), raw.get('params', {})
            if method is None:
                if (type(raw.get('id')) not in (str, int) or type(raw.get('id')) is bool
                        or ('error' in raw) == ('result' in raw)
                        or not (type(raw.get('error')) is dict or type(raw.get('result')) is dict)
                        or raw.get('id') in responses_seen
                        or raw.get('id') not in response_ids and raw != receipt.get('response')):
                    raise ApplicationError('SUBMISSION_REVIEW_SUCCESSOR_SOURCE_INVALID')
                responses_seen.add(raw['id'])
                if raw['id'] in permissions.values() and type(raw.get('error')) is not dict:
                    outcome = raw['result'].get('outcome')
                    if type(outcome) is dict:
                        outcome = outcome.get('outcome')
                    if outcome not in ('cancelled', 'canceled', 'declined', 'denied'):
                        raise ApplicationError('SUBMISSION_REVIEW_SUCCESSOR_SOURCE_INVALID')
                continue
            if type(params) is not dict:
                raise ApplicationError('SUBMISSION_REVIEW_SUCCESSOR_SOURCE_INVALID')
            if method == 'session/request_permission':
                tool = params.get('toolCall')
                tool_id = params.get('toolCallId')
                if (params.get('approval') == 'file' and type(tool) is dict
                        and tool.get('kind') == 'read'):
                    files, locations = params.get('files'), tool.get('locations')
                    options = params.get('options')
                    if (type(files) is not list or not files
                            or type(tool_id) is not str or not tool_id
                            or tool_id in reads or tool_id in permissions
                            or type(raw.get('id')) not in (str, int) or type(raw.get('id')) is bool
                            or raw['id'] in response_ids
                            or tool.get('toolCallId') != params.get('toolCallId')
                            or any(path not in allowed_paths for path in files)
                            or type(locations) is not list or not locations
                            or any(type(item) is not dict or item.get('path') not in allowed_paths
                                   for item in locations)
                            or {item['path'] for item in locations} != set(files)
                            or type(options) is not list
                            or sum(1 for item in options if type(item) is dict
                                   and item.get('kind') == 'allow_once') != 1):
                        raise ApplicationError('SUBMISSION_REVIEW_SUCCESSOR_SOURCE_INVALID')
                    reads[tool_id] = raw['id']
                    response_ids.add(raw['id'])
                    continue
                if (params.get('approval') != 'command' or type(tool) is not dict
                        or tool.get('kind') != 'execute' or tool.get('toolCallId') != tool_id
                        or type(tool_id) is not str or not tool_id
                        or tool_id in permissions or tool_id in reads
                        or type(tool.get('rawInput')) is not dict
                        or type(tool['rawInput'].get('command')) is not str
                        or not tool['rawInput']['command']
                        or type(params.get('options')) is not list
                        or sum(1 for item in params['options'] if type(item) is dict
                               and item.get('kind') == 'allow_once') != 1
                        or type(raw.get('id')) not in (str, int) or type(raw.get('id')) is bool
                        or raw['id'] in response_ids):
                    raise ApplicationError('SUBMISSION_REVIEW_SUCCESSOR_SOURCE_INVALID')
                permissions[tool_id] = raw['id']
                response_ids.add(raw['id'])
            elif method == 'session/update':
                update = params.get('update')
                tool_id = params.get('toolCallId')
                if type(update) is dict and tool_id is None:
                    tool_id = update.get('toolCallId')
                if type(update) is not dict:
                    raise ApplicationError('SUBMISSION_REVIEW_SUCCESSOR_SOURCE_INVALID')
                if update.get('sessionUpdate') in {'agent_message_chunk', 'usage_update'}:
                    continue
                if update.get('sessionUpdate') not in {'tool_call', 'tool_call_update'}:
                    raise ApplicationError('SUBMISSION_REVIEW_SUCCESSOR_SOURCE_INVALID')
                if (type(tool_id) is not str or not tool_id
                        or update.get('toolCallId') != tool_id
                        or params.get('type') not in (None, update.get('sessionUpdate'))):
                    raise ApplicationError('SUBMISSION_REVIEW_SUCCESSOR_SOURCE_INVALID')
                status = params.get('status', update.get('status'))
                decision = params.get('permissionDecision', update.get('permissionDecision'))
                approval = params.get('approval')
                gate = (params.get('delta') == 'Blocked by acp-adapter approved check command gate'
                    and update.get('content') == [{'type': 'content', 'content': {
                        'type': 'text', 'text': 'Blocked by acp-adapter approved check command gate'}}])
                if (status not in {'in_progress', 'completed', 'failed', 'cancelled', 'canceled'}
                        or update.get('status') != status
                        or approval not in (None, 'file', 'command')
                        or updates.get(tool_id) and updates[tool_id][-1][0] != 'in_progress'):
                    raise ApplicationError('SUBMISSION_REVIEW_SUCCESSOR_SOURCE_INVALID')
                updates.setdefault(tool_id, []).append((status, decision, approval, gate))
            elif method == 'terminal/command' or (type(method) is str and method.startswith('terminal/')):
                raise ApplicationError('SUBMISSION_REVIEW_SUCCESSOR_SOURCE_INVALID')
            elif method == 'fs/read_text_file':
                if params.get('path') not in allowed_paths:
                    raise ApplicationError('SUBMISSION_REVIEW_SUCCESSOR_SOURCE_INVALID')
            elif type(method) is str and method.startswith('fs/') and method != 'fs/read_text_file':
                raise ApplicationError('SUBMISSION_REVIEW_SUCCESSOR_SOURCE_INVALID')
            else:
                raise ApplicationError('SUBMISSION_REVIEW_SUCCESSOR_SOURCE_INVALID')
        # This bounded recovery requires an actual command permission refusal.
        # A gate-only observation is intentionally outside its qualification.
        if not permissions or not set(permissions).union(reads) <= set(updates):
            raise ApplicationError('SUBMISSION_REVIEW_SUCCESSOR_SOURCE_INVALID')
        for tool_id, states in updates.items():
            status, decision, approval, gate = states[-1]
            if any(s != 'in_progress' or d is not None for s,d,_a,_g in states[:-1]):
                raise ApplicationError('SUBMISSION_REVIEW_SUCCESSOR_SOURCE_INVALID')
            if tool_id in reads:
                valid = (status == 'completed' and decision == 'approved' and approval == 'file'
                    and all(a in (None, 'file') for _s,_d,a,_g in states))
            elif tool_id in permissions:
                valid = (status in {'failed', 'cancelled', 'canceled'}
                    and decision in ('cancelled', 'canceled', 'declined', 'denied')
                    and all(a in (None, 'command') for _s,_d,a,_g in states))
            else:
                # Pi may reject a command at its approved-command gate before
                # requesting permission. Only that exact native failure is known.
                valid = (status == 'failed' and decision is None and gate
                    and all(a == 'command' for _s,_d,a,_g in states))
            if not valid:
                raise ApplicationError('SUBMISSION_REVIEW_SUCCESSOR_SOURCE_INVALID')
        return True

    def qualify_review_successor(self, context, *, checkpoint_ref, submission_ref, predecessor):
        """Cold-read and bind one rejected completed reviewer observation for a successor."""
        from ....application.contracts.commands import CommandContext
        from ....domain.reviews.refs import SubmissionRef
        from ....domain.common.models.refs import BlobRef
        if (self.correction_ports is None or type(context) is not CommandContext
                or type(submission_ref) is not SubmissionRef
                or type(predecessor) is not dict or set(predecessor) != _SUCCESSOR_FIELDS
                or type(predecessor.get('review_id')) is not str or not predecessor['review_id']
                or type(predecessor.get('operation_ref')) is not str or not predecessor['operation_ref']
                or type(predecessor.get('expected_observation_revision')) is not int
                or type(predecessor.get('expected_observation_revision')) is bool
                or predecessor['expected_observation_revision'] < 1):
            raise ApplicationError('SUBMISSION_REVIEW_SUCCESSOR_SOURCE_INVALID')
        access = self.correction_ports.access
        if not callable(getattr(access, 'require', None)):
            raise ApplicationError('SUBMISSION_REVIEW_SUCCESSOR_SOURCE_UNAVAILABLE')
        access.require(context, 'engineering.work.invoke')
        supplied_observation = _as_ref(predecessor['observation_ref'])
        if type(supplied_observation) is not BlobRef:
            raise ApplicationError('SUBMISSION_REVIEW_SUCCESSOR_SOURCE_INVALID')
        # All owner SQL reads close before BlobStore, UnitRecords, or termination I/O.
        with self.factory.begin(context.scope, 'read') as uow:
            submission = uow.submissions.resolve(submission_ref)
            binding = resolve_declared_report_binding(uow, submission)
            package = uow.implementation.resolve_package(submission.package_ref)
            plan = uow.reviews.get_plan(predecessor['review_id'])
            request = uow.reviews.get_request(predecessor['review_id'])
            assignment, control = uow.reviewer_assignments.active_for_review(predecessor['review_id'])
        if (submission.checkpoint_ref is None or _as_ref(checkpoint_ref) != submission.checkpoint_ref
                or plan.scope != context.scope or plan.review_id != predecessor['review_id']
                or request.state != 'requested' or request.version != assignment.request_version
                or request.fence != assignment.fence or assignment.plan_digest != plan.plan_digest
                or control.state != 'active' or control.ref != assignment.ref
                or assignment.method_ref != plan.requirement.method_ref
                or assignment.roles != tuple(sorted(plan.reviewer_requirements))
                or package.payload.method_ref != plan.requirement.method_ref
                or assignment.author_unit_ref_bytes != binding.unit_ref_bytes):
            raise ApplicationError('SUBMISSION_REVIEW_SUCCESSOR_SOURCE_INVALID')
        source = self._registered_correction(context, submission)
        if (source['checkpoint_ref'] != submission.checkpoint_ref
                or _as_ref(checkpoint_ref) != source['checkpoint_ref']):
            raise ApplicationError('SUBMISSION_REVIEW_SUCCESSOR_SOURCE_INVALID')
        targets = plan.requirement.expected_targets.targets
        primary = tuple(item for item in targets if item.role == 'primary')
        if (len(targets) != 1 or len(primary) != 1
                or primary[0].ref != submission_ref
                or plan.requirement.method_ref != package.payload.method_ref
                or plan.requirement.schema_version != 2
                or plan.requirement.purpose != 'acceptance'):
            raise ApplicationError('SUBMISSION_REVIEW_SUCCESSOR_SOURCE_INVALID')
        unit_ref = assignment.reviewer_unit_ref
        author_ref = decode_json(binding.unit_ref_bytes)
        if (unit_ref == author_ref
                or (unit_ref['environmentNamespace'], unit_ref['unitId']) ==
                   (author_ref['environmentNamespace'], author_ref['unitId'])):
            raise ApplicationError('SUBMISSION_REVIEW_SUCCESSOR_SOURCE_INVALID')
        operation_ref = declared_review_operation_ref(plan, assignment)
        if predecessor['operation_ref'] != operation_ref:
            raise ApplicationError('SUBMISSION_REVIEW_SUCCESSOR_SOURCE_INVALID')
        prompt_digest = self.correction_ports.records.acp_prompt_input_digest(unit_ref,
            self._read_predecessor_params(supplied_observation))
        invocation = self.correction_ports.query(context, unit_ref, operation_ref, prompt_digest)
        captured = capture_execution_observation(
            self.correction_ports.records, self.blobs, authority_id=self.factory.authority_id,
            unit_ref=unit_ref, operation_ref=operation_ref,
            expected_prompt_digest=prompt_digest, query_invocation=invocation,
            max_receipt_bytes=self.correction_ports.records.acp_turn_evidence_max_bytes)
        if (captured.blob_ref != supplied_observation
                or captured.revision != predecessor['expected_observation_revision']
                or captured.state != 'completed'):
            raise ApplicationError('SUBMISSION_REVIEW_SUCCESSOR_SOURCE_INVALID')
        receipt_raw = self.blobs.read_verified(supplied_observation)
        _require_same_blob_bytes(self.blobs, supplied_observation, receipt_raw,
                                 'SUBMISSION_REVIEW_SUCCESSOR_SOURCE_INVALID')
        receipt = canonical_value(receipt_raw, maximum=MAX_EXECUTION_RECEIPT_BYTES)
        params = receipt.get('input', {}).get('params') if type(receipt.get('input')) is dict else None
        expected_binding = {'ordessa.declared-unit-review': {
            'plan': asdict(plan), 'request_version': assignment.request_version,
            'fence': assignment.fence, 'assignment_ref': asdict(assignment.ref),
            'reviewer_unit_ref': assignment.reviewer_unit_ref, 'author_unit_ref': author_ref}}
        if (type(params) is not dict or type(params.get('prompt')) is not list
                or not params['prompt'] or type(params['prompt'][0]) is not dict
                or set(params['prompt'][0]) != {'type', 'text'}
                or params['prompt'][0].get('type') != 'text'
                or type(params['prompt'][0].get('text')) is not str
                or params['prompt'][0]['text'] != canonical_bytes(expected_binding).decode('utf-8')
                or receipt.get('unitRef') != unit_ref or receipt.get('operationRef') != operation_ref
                or receipt.get('inputDigest') != prompt_digest
                or receipt.get('revision') != predecessor['expected_observation_revision']
                or receipt.get('state') != 'completed'
                or receipt.get('input') != {'unitRef': unit_ref, 'params': params}
                or type(receipt.get('summary')) is not dict
                or receipt['summary'].get('successfulRpcResponse') is not True
                or receipt['summary'].get('stopReason') != 'end_turn'
                or type(receipt.get('request')) is not dict
                or type(receipt['request'].get('raw')) is not dict
                or receipt['request']['raw'].get('method') != 'session/prompt'
                or receipt['request']['raw'].get('params') != params
                or type(receipt.get('response')) is not dict
                or receipt['response'].get('jsonrpc') != '2.0'
                or 'result' not in receipt['response'] or 'error' in receipt['response']
                or canonical_bytes(receipt['response'].get('id')) !=
                   canonical_bytes(receipt['request']['raw'].get('id'))
                or receipt['response'] not in [event.get('raw') for event in receipt.get('events', [])
                                                if type(event) is dict]):
            raise ApplicationError('SUBMISSION_REVIEW_SUCCESSOR_SOURCE_INVALID')
        self._review_command_failure(receipt, set(source['paths']))
        closed = self.correction_ports.read_unit(context, unit_ref)
        if (type(closed) is not dict or set(closed) !=
                {'unit_ref', 'profile_ref', 'stop_record', 'release_record'}
                or closed['unit_ref'] != unit_ref
                or _profile(closed['profile_ref']) != source['plan']['origin']['profile_ref']):
            raise ApplicationError('SUBMISSION_REVIEW_SUCCESSOR_SOURCE_INVALID')
        for name in ('stop_record', 'release_record'):
            record = closed[name]
            if (type(record) is not dict or record.get('state') != 'confirmed'
                    or record.get('identity', {}).get('unitRef') != unit_ref):
                raise ApplicationError('SUBMISSION_REVIEW_SUCCESSOR_SOURCE_INVALID')
        proof = {'contract': _SUCCESSOR_CONTRACT,
            'checkpoint_ref': asdict(source['checkpoint_ref']),
            'submission_ref': asdict(submission_ref), 'predecessor': {
                'review_id': predecessor['review_id'], 'operation_ref': predecessor['operation_ref'],
                'expected_observation_revision': predecessor['expected_observation_revision'],
                'observation_ref': asdict(supplied_observation)},
            'plan_digest': asdict(plan.plan_digest),
            'request_version': request.version, 'fence': request.fence,
            'assignment_ref': asdict(assignment.ref), 'unit_ref': unit_ref,
            'prompt_input_digest': prompt_digest,
            'stop_record_digest': asdict(_digest_of(canonical_bytes(closed['stop_record']))),
            'release_record_digest': asdict(_digest_of(canonical_bytes(closed['release_record']))),
            'reason': 'read-only-evidence-policy-rejected'}
        proof_raw = canonical_bytes(proof)
        proof_ref = self.blobs.put_verified(proof_raw, _digest_of(proof_raw), 'application/json')
        if (type(proof_ref) is not type(supplied_observation)
                or proof_ref.digest != _digest_of(proof_raw) or proof_ref.byte_length != len(proof_raw)
                or self.blobs.read_verified(proof_ref) != proof_raw):
            raise ApplicationError('SUBMISSION_REVIEW_SUCCESSOR_SOURCE_INVALID')
        return {'proof_ref': asdict(proof_ref), 'proof': proof}

    def _read_predecessor_params(self, observation_ref):
        receipt_raw = self.blobs.read_verified(observation_ref)
        receipt = canonical_value(receipt_raw, maximum=MAX_EXECUTION_RECEIPT_BYTES)
        input_frame = receipt.get('input')
        params = input_frame.get('params') if type(input_frame) is dict else None
        if type(params) is not dict:
            raise ApplicationError('SUBMISSION_REVIEW_SUCCESSOR_SOURCE_INVALID')
        return params

    def _origin_row(self, uow, context, work, selector, invoke_digest):
        """Strict RC1 origin: original pending parent + completed business attempt."""
        from ....application.contracts.commands import CommandContext
        from ....application.contracts.work_context import WorkBinding
        if (type(context) is not CommandContext or type(work) is not WorkBinding
                or type(selector) is not dict or type(invoke_digest) is not Digest
                or set(selector) != _SELECTOR_FIELDS):
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_INVALID')
        parent_id, op_ref = selector['parent_operation_id'], selector['execution_operation_ref']
        if (type(parent_id) is not str or not parent_id or type(op_ref) is not str or not op_ref
                or any(type(selector[name]) is not int or type(selector[name]) is bool
                       for name in ('expected_parent_version', 'expected_dispatch_version',
                                    'expected_observation_revision'))
                or selector['expected_parent_version'] < 0
                or selector['expected_dispatch_version'] < 1
                or selector['expected_observation_revision'] < 1):
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_INVALID')
        entry = uow.commands.find_operation(context.scope, parent_id,
                                            operation=PARENT_INVOKE_OPERATION)
        if (entry is None or entry.state != 'pending'
                or entry.request_digest != invoke_digest
                or entry.version != selector['expected_parent_version']
                or entry.project_id != context.scope.project_id
                or entry.key.realm_id != context.scope.realm_id
                or entry.key.principal_id != context.principal_id
                or entry.key.request_id != context.request_id):
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_PARENT_MISMATCH')
        try:
            row = uow.work_dispatch.by_operation(op_ref, context.scope)
        except ApplicationError as error:
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_ORIGIN_UNAVAILABLE') from error
        binding = decode_dispatch(row['binding_bytes'])
        if (binding.binding_version != 2 or binding.scope != context.scope
                or binding.work is None or binding.work.get('work_id') != work.work_id
                or binding.work.get('step_id') != binding.step_id
                or binding.execution_operation_ref != op_ref
                or row['execution_operation_ref'] != op_ref
                or row['dispatch_version'] != selector['expected_dispatch_version']
                or row['dispatch_phase'] != 'completed'
                or row['result_blob_json'] is None):
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_ORIGIN_MISMATCH')
        grant = uow.authorization.get_grant(binding.approval_ref)
        control = uow.authorization.get_control(grant.ref)
        budget = uow.authorization.action_budget(grant.ref)
        authorization = grant.intent.authorization
        if (binding.intent_digest != grant.intent.digest or control.get('state') != 'granted'
                or control.get('revoked_at') is not None
                or not grant.intent.not_before <= context.received_at < grant.intent.expires_at
                or authorization.work_id != work.work_id
                or authorization.work_revision != work.revision
                or authorization.action_id != binding.work['action_id']
                or authorization.step_id != binding.step_id
                or authorization.method_ref != work.method_ref
                or authorization.package_ref != binding.package_ref):
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_GRANT_MISMATCH')
        slots = {item['action']: item for item in budget['actions']}
        for action, _instance in binding.action_instances:
            slot = slots.get(action)
            if slot is None or slot.get('limit') != 1 or slot.get('consumed') != 1:
                # The correction reuses the original budget; it never refunds or
                # consumes a second time.
                raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CONSUMPTION_MISMATCH')
        observation_ref = decode_blob_ref(decode_json(row['result_blob_json']))
        return row, binding, grant, observation_ref

    def _rejected_report(self, context, receipt, selector):
        from ....domain.common.mechanisms.codec import canonical_value as _cv
        try:
            body = _cv(receipt, maximum=MAX_EXECUTION_RECEIPT_BYTES)
        except (ValueError, TypeError):
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_OUTPUT_INVALID') from None
        return self._rejected_report_body(body, selector)

    @staticmethod
    def _rejected_report_body(body, selector):
        """Extract from receipt bytes already decoded in this same call."""
        summary = body.get('summary') or {}
        if (body.get('state') != 'completed' or body.get('revision') != selector['expected_observation_revision']
                or type(summary.get('text')) is not str or not summary['text']):
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_OUTPUT_INVALID')
        raw = summary['text'].encode('utf-8')
        try:
            value = decode_json(raw)
        except (ValueError, TypeError, UnicodeError):
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_OUTPUT_INVALID') from None
        if type(value) is not dict or value.get('type') != 'json_object':
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_RULE_MISMATCH')
        without = dict(value)
        without.pop('type')
        return raw, without

    def prepare_correction(self, context, *, work, selector, invoke_digest, evidence):
        """Qualify the original graph and reserve the one correction claim.

        Returns ``state='ready'`` only after the claim row is committed; an
        existing pending claim never creates a Unit or a second claim.
        """
        from ....application.contracts.commands import CommandContext
        from ....application.contracts.work_context import WorkBinding
        from ...contracts.commands import CommandKey
        if self.correction_ports is None:
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_UNAVAILABLE')
        if (type(context) is not CommandContext or type(work) is not WorkBinding
                or type(selector) is not dict or set(selector) != _SELECTOR_FIELDS
                or type(invoke_digest) is not Digest or type(evidence) is not dict
                or set(evidence) != _EVIDENCE_FIELDS):
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_INVALID')
        files, check = evidence['files'], evidence['check']
        if (type(files) is not list or not files or type(check) is not dict
                or set(check) != _CHECK_FIELDS
                or check.get('limitation') != CORRECTION_LIMITATION
                or type(check.get('tool_call_id')) is not str or not check['tool_call_id']
                or check.get('origin_operation_ref') != selector['execution_operation_ref']):
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_INVALID')
        self._require_correction_file_set(files)
        seen_paths = set()
        for item in files:
            if (type(item) is not dict or set(item) != _FILE_FIELDS
                    or type(item['path']) is not str or not item['path']):
                raise ApplicationError('SUBMISSION_REPORT_CORRECTION_INVALID')
            path = item['path']
            if (not path.startswith('/') or '/../' in path or path.endswith('/..')
                    or path in seen_paths or os.path.islink(path)):
                raise ApplicationError('SUBMISSION_REPORT_CORRECTION_FILE_INVALID')
            seen_paths.add(path)
            raw = self.correction_ports.read_material(context, 'repository_file', path)
            ref = _as_ref(item['blob_ref'])
            if (type(raw) is not bytes or _digest_of(raw) != ref.digest
                    or len(raw) != ref.byte_length):
                raise ApplicationError('SUBMISSION_REPORT_CORRECTION_FILE_MISMATCH')
            _require_same_blob_bytes(
                self.blobs, ref, raw, 'SUBMISSION_REPORT_CORRECTION_FILE_MISMATCH')
        journal_raw = self.correction_ports.read_material(
            context, 'original_journal', selector['execution_operation_ref'])
        excerpt_raw = self.correction_ports.read_material(
            context, 'original_check_excerpt', selector['execution_operation_ref'])
        journal_ref = _as_ref(check['journal_ref'])
        excerpt_ref = _as_ref(check['excerpt_ref'])
        command_digest = _decode_digest(check['command_digest'])
        if (type(journal_raw) is not bytes or _digest_of(journal_raw) != journal_ref.digest
                or type(excerpt_raw) is not bytes or _digest_of(excerpt_raw) != excerpt_ref.digest
                or excerpt_raw not in journal_raw):
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CHECK_MISMATCH')
        _require_same_blob_bytes(
            self.blobs, journal_ref, journal_raw, 'SUBMISSION_REPORT_CORRECTION_CHECK_MISMATCH')
        _require_same_blob_bytes(
            self.blobs, excerpt_ref, excerpt_raw, 'SUBMISSION_REPORT_CORRECTION_CHECK_MISMATCH')
        selected_command = _check_journal_evidence(
            journal_raw, excerpt_raw, check, journal_ref, excerpt_ref, command_digest)
        with self.factory.begin(context.scope, 'read') as uow:
            row, binding, grant, observation_ref = self._origin_row(
                uow, context, work, selector, invoke_digest)
        # BlobStore, UnitRecords and host-material ports are deliberately used
        # only after the SQL read transaction has closed.
        receipt = self.blobs.read_verified(observation_ref)
        rejected_raw, _expected = self._rejected_report(context, receipt, selector)
        from ....application.usecases.changes.execution_capture import capture_execution_observation
        unit_ref = decode_json(binding.unit_ref_bytes)
        query_invocation = self.correction_ports.query(
            context, unit_ref, binding.execution_operation_ref,
            'sha256:' + binding.prompt_input_digest.hex)
        actual = capture_execution_observation(
            self.correction_ports.records, self.blobs,
            authority_id=self.factory.authority_id, unit_ref=unit_ref,
            operation_ref=binding.execution_operation_ref,
            expected_prompt_digest='sha256:' + binding.prompt_input_digest.hex,
            query_invocation=query_invocation, max_receipt_bytes=MAX_EXECUTION_RECEIPT_BYTES)
        if (actual.blob_ref != observation_ref or actual.state != 'completed'
                or actual.revision != selector['expected_observation_revision']
                or actual.query_digest != binding.expected_query_digest):
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_ORIGIN_MISMATCH')
        closed_author = self.correction_ports.read_unit(context, unit_ref)
        if (type(closed_author) is not dict
                or set(closed_author) != {'unit_ref', 'profile_ref', 'stop_record', 'release_record'}
                or closed_author['unit_ref'] != unit_ref):
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_PROFILE_MISMATCH')
        profile_ref = _profile(closed_author['profile_ref'])
        authorization = grant.intent.authorization
        if not any(
                environment.environment_id == profile_ref.get('environmentNamespace')
                and environment.profile_id == profile_ref.get('profileId')
                and 'sha256:' + environment.profile_digest.hex == profile_ref.get('contentDigest')
                for _action, scope in authorization.scope_by_action
                for environment in scope.environment_refs):
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_PROFILE_MISMATCH')
        _check_native_permission(decode_json(receipt), check['tool_call_id'], selected_command)
        rejected_ref = self.blobs.put_verified(
            rejected_raw, _digest_of(rejected_raw),
            'application/vnd.ordessa.declared-report-rejected+json')
        plan = {
            'contract': REWORK_PLAN_CONTRACT, 'rule': REWORK_RULE,
            'origin': {
                'parent_key': {'realm_id': context.scope.realm_id,
                               'principal_id': context.principal_id,
                               'request_id': context.request_id},
                'parent_operation_id': selector['parent_operation_id'],
                'parent_request_digest': asdict(invoke_digest),
                'parent_version': selector['expected_parent_version'],
                'work_id': work.work_id, 'work_revision': work.revision,
                'work_digest': asdict(grant.intent.authorization.work_digest),
                'action_id': binding.work['action_id'], 'step_id': binding.step_id,
                'package_ref': asdict(binding.package_ref),
                'method_ref': asdict(work.method_ref),
                'profile_ref': profile_ref,
                'author_unit_ref': decode_json(binding.unit_ref_bytes),
                'binding_digest': asdict(binding.digest),
                'dispatch_version': row['dispatch_version'],
                'execution_operation_ref': selector['execution_operation_ref'],
                'observation_ref': asdict(observation_ref),
                'observation_revision': selector['expected_observation_revision'],
                'rejected_report_ref': asdict(rejected_ref),
            },
            'evidence': {'files': [dict(item, blob_ref=asdict(_as_ref(item['blob_ref'])))
                                   for item in sorted(files, key=lambda file: file['path'])],
                         'check': dict(check, journal_ref=asdict(journal_ref),
                                       excerpt_ref=asdict(excerpt_ref),
                                       command_digest=asdict(command_digest))},
        }
        method_ref = _method_ref(plan['origin']['method_ref'])
        with self.methods.guard(context, method_ref):
            schema_ref = self.methods.resource_ref(
                context, method_ref, 'implementation-report-schema')
            schema = decode_json(self.methods.read_resource(context, schema_ref))
        plan_bytes = canonical_bytes(plan)
        plan_ref = self.blobs.put_verified(plan_bytes, _digest_of(plan_bytes),
                                           REWORK_PLAN_MEDIA_TYPE)
        correction_params = _correction_params(plan, plan_ref, schema, rejected_raw)
        hex_digest = plan_ref.digest.hex
        key = CommandKey(context.scope.realm_id, context.principal_id,
                         CORRECTION_CLAIM_PREFIX + hex_digest[:48])
        operation_id = CORRECTION_OPERATION_PREFIX + hex_digest
        claim_digest = record_digest('report-correction-claim', {
            'plan_ref': asdict(plan_ref),
            'parent_key': plan['origin']['parent_key'],
            'parent_operation_id': plan['origin']['parent_operation_id'],
            'parent_request_digest': asdict(invoke_digest),
            'execution_operation_ref': plan['origin']['execution_operation_ref'],
            'rule': REWORK_RULE,
        })
        registered = None
        with self.factory.begin(context.scope) as uow:
            current_row, current_binding, current_grant, current_observation_ref = self._origin_row(
                uow, context, work, selector, invoke_digest)
            if (current_binding.digest != binding.digest
                    or current_row['dispatch_version'] != row['dispatch_version']
                    or current_observation_ref != observation_ref
                    or current_grant.intent.digest != grant.intent.digest):
                raise ApplicationError('SUBMISSION_REPORT_CORRECTION_ORIGIN_MISMATCH')
            existing = uow.commands.find_operation(context.scope, operation_id,
                                                   operation=CORRECTION_CLAIM_OPERATION)
            if existing is not None:
                if (existing.key != key or existing.request_digest != claim_digest):
                    raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CLAIM_MISMATCH')
                if existing.state == 'completed':
                    prior = decode_json(existing.result_bytes)
                    if (type(prior) is not dict or set(prior) != {'plan_ref', 'submission_ref'}
                            or _as_ref(prior['plan_ref']) != plan_ref):
                        raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CLAIM_MISMATCH')
                    from ....domain.reviews.target_codec import decode_subject_ref
                    from ....domain.reviews.refs import SubmissionRef
                    subject = decode_subject_ref(prior['submission_ref'])
                    if type(subject) is not SubmissionRef:
                        raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CLAIM_MISMATCH')
                    submission = uow.submissions.resolve(subject)
                    stored_binding = resolve_declared_report_binding(uow, submission)
                    registered = (subject, submission, stored_binding)
                else:
                    return {'plan_ref': asdict(plan_ref), 'operation_ref': operation_id,
                            'created': False, 'state': 'pending_query_only',
                            'params': None, 'submission_ref': None}
            else:
                try:
                    reserved = uow.commands.reserve(
                        key, project_id=context.scope.project_id,
                        operation=CORRECTION_CLAIM_OPERATION, operation_id=operation_id,
                        request_digest=claim_digest)
                except ApplicationError as error:
                    raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CLAIM_MISMATCH') from error
                if not reserved.created:
                    raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CLAIM_MISMATCH')
                uow.commit()
        if registered is not None:
            subject, submission, stored_binding = registered
            if submission.checkpoint_ref is None:
                raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CLAIM_MISMATCH')
            stored_checkpoint = decode_json(self.blobs.read_verified(submission.checkpoint_ref))
            if (stored_checkpoint.get('contract') != REWORK_CONTRACT
                    or _as_ref(stored_checkpoint.get('plan_ref')) != plan_ref
                    or submission.execution_ref.operation_ref
                        != plan['origin']['execution_operation_ref']
                    or stored_binding.execution_operation_ref
                        != plan['origin']['execution_operation_ref']):
                raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CLAIM_MISMATCH')
            return {'plan_ref': asdict(plan_ref), 'operation_ref': operation_id,
                    'created': False, 'state': 'report_registered',
                    'params': None, 'submission_ref': asdict(subject)}
        return {'plan_ref': asdict(plan_ref), 'operation_ref': operation_id,
                'created': True, 'state': 'ready', 'params': correction_params,
                'submission_ref': None}

    def _validate_correction(self, context, *, checkpoint_ref):
        """Re-verify a correction and return its private native correction capture."""
        from ....application.contracts.commands import CommandContext
        from ....domain.common.mechanisms.codec import canonical_value as _cv
        if self.correction_ports is None or type(context) is not CommandContext:
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_UNAVAILABLE')
        envelope = decode_json(self.blobs.read_verified(checkpoint_ref))
        if (type(envelope) is not dict or set(envelope) != {'contract', 'plan_ref', 'correction'}
                or envelope['contract'] != REWORK_CONTRACT):
            raise ApplicationError('SUBMISSION_REPORT_BINDING_MISMATCH')
        correction = envelope['correction']
        if (type(correction) is not dict
                or set(correction) != {'unit_ref', 'operation_ref', 'prompt_input_digest',
                                       'observation_ref', 'observation_revision', 'output_ref',
                                       'stop_record_digest', 'release_record_digest'}
                or any(type(correction[name]) is not int or type(correction[name]) is bool
                       for name in ('observation_revision',))
                or correction['observation_revision'] < 1):
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_INVALID')
        plan_ref = _as_ref(envelope['plan_ref'])
        plan = decode_json(self.blobs.read_verified(plan_ref))
        if (type(plan) is not dict or set(plan) != {'contract', 'rule', 'origin', 'evidence'}
                or plan['contract'] != REWORK_PLAN_CONTRACT or plan['rule'] != REWORK_RULE):
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_INVALID')
        evidence = plan['evidence']
        if (type(evidence) is not dict or set(evidence) != {'files', 'check'}
                or type(evidence['files']) is not list or not evidence['files']
                or type(evidence['check']) is not dict
                or set(evidence['check']) != _CHECK_FIELDS):
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_INVALID')
        self._require_correction_file_set(evidence['files'])
        origin = plan['origin']
        if (type(origin) is not dict
                or set(origin) != {'parent_key', 'parent_operation_id', 'parent_request_digest',
                    'parent_version', 'work_id', 'work_revision', 'work_digest', 'action_id',
                    'step_id', 'package_ref', 'method_ref', 'profile_ref', 'author_unit_ref',
                    'binding_digest', 'dispatch_version', 'execution_operation_ref',
                    'observation_ref', 'observation_revision', 'rejected_report_ref'}
                or type(origin['parent_key']) is not dict
                or set(origin['parent_key']) != {'realm_id', 'principal_id', 'request_id'}):
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_INVALID')
        rejected = _as_ref(origin['rejected_report_ref'])
        output_ref = _as_ref(correction['output_ref'])
        observation_ref = _as_ref(correction['observation_ref'])
        receipt = self.blobs.read_verified(observation_ref)
        body = _cv(receipt, maximum=MAX_EXECUTION_RECEIPT_BYTES)
        summary = body.get('summary') or {}
        unit_ref = correction['unit_ref']
        prompt_digest = _decode_digest(correction['prompt_input_digest'])
        if (body.get('contractVersion') != 'unit-acp-turn/1'
                or body.get('unitRef') != unit_ref
                or type(correction['operation_ref']) is not str
                or correction['operation_ref'] != CORRECTION_OPERATION_PREFIX + plan_ref.digest.hex
                or body.get('operationRef') != correction['operation_ref']
                or body.get('state') != 'completed'
                or body.get('revision') != correction['observation_revision']
                or body.get('inputDigest') != 'sha256:' + prompt_digest.hex
                or type(summary.get('text')) is not str or not summary['text']):
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CAPTURE_MISMATCH')
        new_raw = canonical_bytes(decode_json(summary['text'].encode('utf-8')))
        if self.blobs.read_verified(output_ref) != new_raw:
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CAPTURE_MISMATCH')
        method_ref = _method_ref(plan['origin']['method_ref'])
        with self.methods.guard(context, method_ref) as declaration:
            exact = self.methods.resource_ref(context, method_ref, 'implementation-report-schema')
            schema = decode_json(self.methods.read_resource(context, exact))
            new_value = decode_json(new_raw)
            if not Draft202012Validator(schema).is_valid(new_value):
                raise ApplicationError('SUBMISSION_REPORT_SCHEMA_MISMATCH')
        rejected_raw = self.blobs.read_verified(rejected)
        old_value = decode_json(rejected_raw)
        if type(old_value) is not dict or old_value.get('type') != 'json_object':
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_RULE_MISMATCH')
        expected = dict(old_value)
        expected.pop('type')
        if canonical_bytes(expected) != new_raw:
            # Only the ruled-out top-level type may differ; any business drift
            # is a different report, not a format correction.
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CONTENT_MISMATCH')
        _check_readonly_capture(body, [item['path'] for item in evidence['files']])
        expected_params = _correction_params(plan, plan_ref, schema, rejected_raw)
        input_frame = body.get('input')
        if (type(input_frame) is not dict or set(input_frame) != {'unitRef', 'params'}
                or input_frame.get('unitRef') != unit_ref
                or type(input_frame.get('params')) is not dict):
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CAPTURE_MISMATCH')
        actual_params = dict(input_frame['params'])
        native = body.get('nativeBinding')
        native_session = native.get('sessionId') if type(native) is dict else None
        input_session = actual_params.pop('sessionId', native_session)
        if (type(native) is not dict or type(native.get('sessionId')) is not str
                or input_session != native['sessionId']
                or actual_params != expected_params):
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_PROMPT_MISMATCH')
        closed = self.correction_ports.read_unit(context, unit_ref)
        if (type(closed) is not dict or set(closed) != {'unit_ref', 'profile_ref',
                                                        'stop_record', 'release_record'}
                or closed['unit_ref'] != unit_ref
                or unit_ref == origin['author_unit_ref']
                or _profile(closed['profile_ref']) != origin['profile_ref']):
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_UNIT_MISMATCH')
        for name in ('stop_record', 'release_record'):
            record = closed[name]
            if (type(record) is not dict or record.get('state') != 'confirmed'
                    or record.get('identity', {}).get('unitRef') != unit_ref):
                raise ApplicationError('SUBMISSION_REPORT_CORRECTION_UNIT_OPEN')
        for name in ('stop_record_digest', 'release_record_digest'):
            if _decode_digest(correction[name]) != _digest_of(canonical_bytes(
                    closed['stop_record' if name == 'stop_record_digest' else 'release_record'])):
                raise ApplicationError('SUBMISSION_REPORT_CORRECTION_UNIT_MISMATCH')
        from ....application.usecases.changes.execution_capture import capture_execution_observation
        invocation = self.correction_ports.query(
            context, unit_ref, correction['operation_ref'], 'sha256:' + prompt_digest.hex)
        correction_capture = capture_execution_observation(
            self.correction_ports.records, self.blobs, authority_id=self.factory.authority_id,
            unit_ref=unit_ref, operation_ref=correction['operation_ref'],
            expected_prompt_digest='sha256:' + prompt_digest.hex,
            query_invocation=invocation, max_receipt_bytes=MAX_EXECUTION_RECEIPT_BYTES)
        if (correction_capture.blob_ref != observation_ref
                or correction_capture.revision != correction['observation_revision']
                or correction_capture.query_digest != self.correction_ports.records.acp_turn_query_digest(
                    unit_ref, correction['operation_ref'], 'sha256:' + prompt_digest.hex)
                or correction_capture.state != 'completed'):
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CAPTURE_MISMATCH')
        with self.factory.begin(context.scope, 'read') as uow:
            row = uow.work_dispatch.by_operation(origin['execution_operation_ref'], context.scope)
            binding = decode_dispatch(row['binding_bytes'])
            parent = uow.commands.find_operation(
                context.scope, origin['parent_operation_id'], operation=PARENT_INVOKE_OPERATION)
            package = uow.implementation.resolve_package(binding.package_ref)
            current_grant = uow.authorization.get_grant(binding.approval_ref)
            current_control = uow.authorization.get_control(current_grant.ref)
            current_budget = uow.authorization.action_budget(current_grant.ref)
            current_authorization = current_grant.intent.authorization
            action_slots = {item['action']: item for item in current_budget['actions']}
            budget_current = all(
                action in action_slots
                and action_slots[action].get('limit') == 1
                and action_slots[action].get('consumed') == 1
                for action, _instance in binding.action_instances)
            if (binding.digest != _decode_digest(origin['binding_digest'])
                    or row['dispatch_version'] != origin['dispatch_version']
                    or row['dispatch_phase'] != 'completed'
                    or row['execution_operation_ref'] != origin['execution_operation_ref']
                    or binding.work['work_id'] != origin['work_id']
                    or binding.scope != context.scope
                    or binding.work['action_id'] != origin['action_id']
                    or binding.step_id != origin['step_id']
                    or asdict(binding.package_ref) != origin['package_ref']
                    or _decode_digest(origin['work_digest']) != current_authorization.work_digest
                    or current_authorization.work_id != origin['work_id']
                    or current_authorization.work_revision != origin['work_revision']
                    or current_authorization.action_id != origin['action_id']
                    or current_authorization.step_id != origin['step_id']
                    or current_authorization.package_ref != binding.package_ref
                    or current_grant.intent.digest != binding.intent_digest
                    or current_control.get('state') != 'granted'
                    or current_control.get('revoked_at') is not None
                    or not current_grant.intent.not_before <= context.received_at
                        < current_grant.intent.expires_at
                    or not budget_current
                    or current_authorization.method_ref != _method_ref(origin['method_ref'])
                    or asdict(package.payload.method_ref) != origin['method_ref']
                    or parent is None
                    or parent.request_digest != _decode_digest(origin['parent_request_digest'])
                    or parent.version != origin['parent_version']
                    or parent.state not in {'pending', 'completed'}
                    or parent.project_id != context.scope.project_id
                    or origin['parent_key'].get('realm_id') != context.scope.realm_id
                    or origin['parent_key'].get('principal_id') != context.principal_id
                    or parent.key.realm_id != origin['parent_key'].get('realm_id')
                    or parent.key.principal_id != origin['parent_key'].get('principal_id')
                    or parent.key.request_id != origin['parent_key'].get('request_id')):
                raise ApplicationError('SUBMISSION_REPORT_CORRECTION_ORIGIN_MISMATCH')
        # Re-read all records/blobs and selected source materials only after the
        # SQL owner transaction closes. SQL facts above remain current and are
        # still checked as one consistent owner snapshot.
        original_unit = decode_json(binding.unit_ref_bytes)
        original_query = self.correction_ports.query(
            context, original_unit, binding.execution_operation_ref,
            'sha256:' + binding.prompt_input_digest.hex)
        original_capture = capture_execution_observation(
            self.correction_ports.records, self.blobs,
            authority_id=self.factory.authority_id, unit_ref=original_unit,
            operation_ref=binding.execution_operation_ref,
            expected_prompt_digest='sha256:' + binding.prompt_input_digest.hex,
            query_invocation=original_query, max_receipt_bytes=MAX_EXECUTION_RECEIPT_BYTES)
        if (original_capture.blob_ref != _as_ref(origin['observation_ref'])
                or original_capture.revision != origin['observation_revision']
                or original_capture.query_digest != binding.expected_query_digest
                or original_capture.state != 'completed'):
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_ORIGIN_MISMATCH')
        original_receipt = self.blobs.read_verified(original_capture.blob_ref)
        rejected_raw, _expected_report = self._rejected_report(
            context, original_receipt,
            {'expected_observation_revision': origin['observation_revision']})
        if self.blobs.read_verified(rejected) != rejected_raw:
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_ORIGIN_MISMATCH')
        author = self.correction_ports.read_unit(context, original_unit)
        if (type(author) is not dict
                or set(author) != {'unit_ref', 'profile_ref', 'stop_record', 'release_record'}
                or author['unit_ref'] != original_unit
                or _profile(author['profile_ref']) != origin['profile_ref']):
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_PROFILE_MISMATCH')
        for item in evidence['files']:
            path = item['path']
            if (not path.startswith('/') or '/../' in path or path.endswith('/..')
                    or os.path.islink(path)):
                raise ApplicationError('SUBMISSION_REPORT_CORRECTION_FILE_INVALID')
            ref = _as_ref(item['blob_ref'])
            raw_file = self.correction_ports.read_material(context, 'repository_file', path)
            if (type(raw_file) is not bytes or len(raw_file) != ref.byte_length
                    or _digest_of(raw_file) != ref.digest
                    or self.blobs.read_verified(ref) != raw_file):
                raise ApplicationError('SUBMISSION_REPORT_CORRECTION_FILE_MISMATCH')
        check = evidence['check']
        if (check.get('origin_operation_ref') != binding.execution_operation_ref
                or check.get('limitation') != CORRECTION_LIMITATION):
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CHECK_MISMATCH')
        journal_raw = self.correction_ports.read_material(
            context, 'original_journal', binding.execution_operation_ref)
        excerpt_raw = self.correction_ports.read_material(
            context, 'original_check_excerpt', binding.execution_operation_ref)
        journal_ref, excerpt_ref = _as_ref(check['journal_ref']), _as_ref(check['excerpt_ref'])
        command_digest = _decode_digest(check['command_digest'])
        command = _check_journal_evidence(
            journal_raw, excerpt_raw, check, journal_ref, excerpt_ref, command_digest)
        _check_native_permission(decode_json(original_receipt), check['tool_call_id'], command)
        return plan, binding, original_capture, correction_capture

    def validate_correction(self, context, *, checkpoint_ref):
        """Public contract returns the original binding and original capture."""
        plan, binding, original_capture, _correction_capture = self._validate_correction(
            context, checkpoint_ref=checkpoint_ref)
        return plan, binding, original_capture

    def correction_record(self, context, *, checkpoint_ref):
        """Build the one stable Submission projection for this correction."""
        from ....application.contracts.commands import CommandContext
        from ....domain.artifacts.models import MethodContent
        from ....domain.changes.models import ChangeSet
        from ....domain.changes.submission import ExecutionRecordRef, Submission, SubmissionCoverage
        from ....domain.reviews.refs import SubmissionRef
        if type(context) is not CommandContext:
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_INVALID')
        plan, binding, observation_ref, correction_capture = self._validate_correction(
            context, checkpoint_ref=checkpoint_ref)
        origin = plan['origin']
        with self.factory.begin(context.scope, 'read') as uow:
            grant = uow.authorization.get_grant(binding.approval_ref)
            facts = resolve_work_package_authorization(uow, grant.intent.authorization)
            payload = facts.package.payload
        submission_id = 'work-report-' + _sha256(origin['execution_operation_ref'].encode())[:40]
        execution = binding.execution_operation_ref
        unit = origin['author_unit_ref']
        raw = self.blobs.read_verified(decode_blob_ref(
            decode_json(self.blobs.read_verified(checkpoint_ref))['correction']['output_ref']))
        output_ref = decode_blob_ref(
            decode_json(self.blobs.read_verified(checkpoint_ref))['correction']['output_ref'])
        # _validate_correction has already compared this frozen owner method
        # to both the original binding grant and the package's method binding.
        with self.methods.guard(context, payload.method_ref):
            exact = self.methods.resource_ref(context, payload.method_ref,
                                              'implementation-report-schema')
        record = Submission(
            scope=context.scope, submission_id=submission_id,
            created_at=context.received_at, created_by=context.authenticated_actor,
            change_set=ChangeSet((payload.change_ref,)),
            authorization_refs=(grant.ref,), package_ref=binding.package_ref,
            execution_ref=_execution_ref(origin, unit, binding),
            baseline_snapshots=(), resulting_snapshots=(), commit_refs=(), file_changes=(),
            output_refs=(output_ref,),
            test_evidence=(), effect_observations=(),
            coverage=(SubmissionCoverage(payload.change_ref, (output_ref,), (), (), 'implemented'),),
            source_refs=(payload.baseline, payload.candidate),
            method_content=MethodContent.from_value(exact, decode_json(raw),
                                                   rendered_body_ref=output_ref),
            checkpoint_ref=checkpoint_ref, schema_version=2)
        from ....domain.changes.submission_codec import submission_projection
        return decode_json(canonical_bytes(submission_projection(record)))

    def finish_correction_claim(self, context, *, plan_ref, submission_ref):
        """Complete the exact still-pending claim with its final reference."""
        from ...contracts.commands import CommandContext, CommandKey
        if self.correction_ports is None or type(context) is not CommandContext:
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_UNAVAILABLE')
        plan_ref = _as_ref(plan_ref)
        from ....domain.reviews.refs import SubmissionRef
        if type(submission_ref) is not SubmissionRef:
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CLAIM_MISMATCH')
        plan = decode_json(self.blobs.read_verified(plan_ref))
        if (type(plan) is not dict or set(plan) != {'contract', 'rule', 'origin', 'evidence'}
                or plan.get('contract') != REWORK_PLAN_CONTRACT
                or plan.get('rule') != REWORK_RULE
                or type(plan.get('origin')) is not dict):
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CLAIM_MISMATCH')
        origin = plan['origin']
        if (origin.get('parent_key', {}).get('realm_id') != context.scope.realm_id
                or origin.get('parent_key', {}).get('principal_id') != context.principal_id):
            raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CLAIM_MISMATCH')
        hex_digest = plan_ref.digest.hex
        operation_id = CORRECTION_OPERATION_PREFIX + hex_digest
        key = CommandKey(context.scope.realm_id, context.principal_id,
                         CORRECTION_CLAIM_PREFIX + hex_digest[:48])
        request_digest = record_digest('report-correction-claim', {
            'plan_ref': asdict(plan_ref), 'parent_key': origin['parent_key'],
            'parent_operation_id': origin['parent_operation_id'],
            'parent_request_digest': origin['parent_request_digest'],
            'execution_operation_ref': origin['execution_operation_ref'],
            'rule': REWORK_RULE})
        result_bytes = canonical_bytes({'plan_ref': asdict(plan_ref),
                                        'submission_ref': asdict(submission_ref)})
        with self.factory.begin(context.scope) as uow:
            entry = uow.commands.find_operation(context.scope, operation_id,
                                                operation=CORRECTION_CLAIM_OPERATION)
            if (entry is None or entry.key != key
                    or entry.request_digest != request_digest
                    or entry.project_id != context.scope.project_id):
                raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CLAIM_MISMATCH')
            if entry.state == 'completed':
                if entry.result_bytes != result_bytes:
                    raise ApplicationError('SUBMISSION_REPORT_CORRECTION_CLAIM_MISMATCH')
                return
            uow.commands.complete(entry.key, expected_version=entry.version,
                                  result_bytes=result_bytes, state='completed')
            uow.commit()

    @contextmanager
    def guard_report(self, context, package, submission, captured):
        if (submission.checkpoint_ref is not None and self.content_rework is not None
                and self.content_rework._is_checkpoint(submission.checkpoint_ref)):
            with self.content_rework.guard_report(context, package, submission, captured) as report:
                yield report
            return
        if (type(package.payload) is not PreparedPackagePayload or submission.schema_version != 2
                or context.scope != submission.scope or package.scope != context.scope):
            raise ApplicationError('SUBMISSION_REPORT_BINDING_MISMATCH')
        method = package.payload.method_ref
        with self.methods.guard(context, method) as declaration:
            with self.factory.begin(context.scope, 'read') as uow:
                binding = resolve_declared_report_binding(uow, submission)
                if uow.implementation.resolve_package(binding.package_ref) != package:
                    raise ApplicationError('SUBMISSION_REPORT_BINDING_MISMATCH')
                grant = uow.authorization.get_grant(binding.approval_ref)
            actions = tuple(a for a in declaration.actions if a.action_id == binding.work['action_id'])
            steps = () if len(actions) != 1 else tuple(s for s in actions[0].steps if s.step_id == binding.step_id)
            if (len(steps) != 1 or steps[0].name != 'implement-approved-package'
                    or steps[0].kind != 'invoke' or 'implementation_report' not in steps[0].outputs
                    or not any(r.resource_id == 'implementation-report-schema' for r in actions[0].resources)):
                raise ApplicationError('SUBMISSION_REPORT_METHOD_MISMATCH')
            exact = self.methods.resource_ref(context, method, 'implementation-report-schema')
            schema = decode_json(self.methods.read_resource(context, exact))
            content = submission.method_content
            if content.schema_ref != exact or not Draft202012Validator(schema).is_valid(content.value):
                raise ApplicationError('SUBMISSION_REPORT_SCHEMA_MISMATCH')
            receipt = canonical_value(self.blobs.read_verified(captured.blob_ref), maximum=MAX_EXECUTION_RECEIPT_BYTES)
            summary = receipt.get('summary')
            if (captured.state != 'completed' or receipt.get('state') != 'completed'
                    or captured.query_digest != binding.expected_query_digest
                    or captured.operation_ref != binding.execution_operation_ref
                    or captured.expected_prompt_digest != 'sha256:' + binding.prompt_input_digest.hex
                    or captured.blob_ref != submission.execution_ref.captured_observation_ref
                    or captured.authority_id != self.factory.authority_id
                    or type(summary) is not dict or summary.get('successfulRpcResponse') is not True
                    or summary.get('modelQualityVerified') is not False
                    or type(summary.get('text')) is not str or not summary['text']):
                raise ApplicationError('SUBMISSION_REPORT_OUTPUT_UNAVAILABLE')
            # UnitRecords owns ACP validation. Retain its native confirmation
            # here as well: an absent response cannot be replaced by a summary
            # flag or by the report's self-declared completed status.
            params = decode_json(self.blobs.read_verified(binding.prompt_ref))
            request, response, events = receipt.get('request'), receipt.get('response'), receipt.get('events')
            native = receipt.get('nativeBinding')
            if (receipt.get('contractVersion') != 'unit-acp-turn/1'
                    or receipt.get('unitRef') != decode_json(binding.unit_ref_bytes)
                    or receipt.get('operationRef') != binding.execution_operation_ref
                    or receipt.get('inputDigest') != 'sha256:' + binding.prompt_input_digest.hex
                    or receipt.get('input') != {'unitRef': decode_json(binding.unit_ref_bytes), 'params': params}
                    or type(native) is not dict or not native.get('sessionId')
                    or native.get('sessionId') != params.get('sessionId')
                    or type(request) is not dict or type(request.get('raw')) is not dict
                    or type(response) is not dict or type(events) is not list):
                raise ApplicationError('SUBMISSION_REPORT_OUTPUT_UNAVAILABLE')
            raw_request = request['raw']
            if (raw_request.get('jsonrpc') != '2.0' or raw_request.get('method') != 'session/prompt'
                    or raw_request.get('params') != params or type(raw_request.get('id')) not in (str, int)
                    or response.get('jsonrpc') != '2.0' or 'result' not in response or 'error' in response
                    or canonical_bytes(response.get('id')) != canonical_bytes(raw_request['id'])
                    or response not in [event.get('raw') for event in events if type(event) is dict]
                    or type(summary.get('eventCount')) is not int or summary['eventCount'] != len(events)):
                raise ApplicationError('SUBMISSION_REPORT_OUTPUT_UNAVAILABLE')
            try:
                raw = canonical_bytes(decode_json(summary['text'].encode('utf-8')))
            except (TypeError, ValueError, UnicodeError):
                raise ApplicationError('SUBMISSION_REPORT_OUTPUT_INVALID') from None
            correction_output = None
            if submission.checkpoint_ref is None:
                if raw != content.value_bytes or self.blobs.read_verified(submission.output_refs[0]) != raw:
                    raise ApplicationError('SUBMISSION_REPORT_OUTPUT_MISMATCH')
            else:
                try:
                    correction_plan, correction_binding, original_capture, correction_capture = \
                        self._validate_correction(context, checkpoint_ref=submission.checkpoint_ref)
                    checkpoint = decode_json(self.blobs.read_verified(submission.checkpoint_ref))
                    correction = checkpoint['correction']
                    correction_output = _as_ref(correction['output_ref'])
                    raw = self.blobs.read_verified(correction_output)
                except ApplicationError:
                    raise
                except Exception:
                    raise ApplicationError('SUBMISSION_REPORT_BINDING_MISMATCH') from None
                if (correction_binding != binding or original_capture != captured
                        or correction_output not in submission.output_refs
                        or len(submission.output_refs) != 1
                        or self.blobs.read_verified(correction_output) != raw
                        or raw != content.value_bytes
                        or correction_capture.blob_ref != _as_ref(correction['observation_ref'])):
                    raise ApplicationError('SUBMISSION_REPORT_OUTPUT_MISMATCH')
            value = content.value
            profile = value['profile_ref']
            task = decode_json(params['prompt'][0]['text'].encode('utf-8'))
            authorization = grant.intent.authorization
            if (value['package_digest'] != 'sha256:' + package.ref.digest.hex
                    or profile != task.get('profile_ref')
                    or any(not any(e.environment_id == profile['environmentNamespace']
                            and e.profile_id == profile['profileId']
                            and 'sha256:' + e.profile_digest.hex == profile['contentDigest']
                            for e in scope.environment_refs) for _, scope in authorization.scope_by_action)):
                raise ApplicationError('SUBMISSION_REPORT_BINDING_MISMATCH')
            yield VerifiedUnitReport(method, exact, submission.output_refs,
                Digest('sha256', hashlib.sha256(raw).hexdigest()), binding.execution_operation_ref,
                binding.prompt_input_digest, captured.query_digest, captured.blob_ref)
