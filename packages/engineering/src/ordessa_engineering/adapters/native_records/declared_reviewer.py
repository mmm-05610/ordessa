"""Read a declared report review from original UnitRecords and assignment owners.

The envelope below is a native-source locator, not a method result schema or
reviewer attestation. The original captured ACP response supplies the human
judgement against the whole pinned criterion; assignments and current access
authenticate its source. No execution, permission or second run ledger is owned
here. Source-target reviews remain with their explicitly configured source.
"""
from contextlib import contextmanager, ExitStack
from dataclasses import asdict
from pathlib import Path

from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ...application.contracts.errors import ApplicationError
from ...application.contracts.reviewer_admission import CriterionAnswer, VerifiedReviewResponse
from ...application.usecases.changes.execution_capture import capture_execution_observation
from ...application.usecases.changes.declared_report import (
    declared_review_operation_ref, resolve_declared_report_binding)
from ...application.usecases.reviews.admission import review_observations
from ...domain.common.mechanisms.codec import decode_blob_ref
from ...domain.common.mechanisms.hashing import record_digest
from ...domain.common.models.identity import ActorRef
from ...domain.reviews.refs import SubmissionRef
from ...domain.reviews.models import CurrentReviewTrust, observations_digest


CONTRACT = 'ordessa.declared-unit-review-source/1'
_RECORD_TYPE = 'declared-unit-review-source'
CAPABILITY = 'engineering.reviewer.unit'


class DeclaredUnitReviewerSource:
    def __init__(self, factory, *, access, scope, methods, bindings, records, blobs,
                 query_factory, source_reviewer, review_paths, report_source=None):
        if (getattr(methods, 'factory', None) is not factory
                or getattr(bindings, 'factory', None) is not factory
                or getattr(blobs, 'authority_id', None) != factory.authority_id
                or not callable(query_factory)
                or not callable(getattr(access, 'guard_current_capability', None))
                or not callable(getattr(records, 'query_acp_turn', None))):
            raise ApplicationError('REVIEW_SOURCE_AUTHORITY_MISMATCH')
        if report_source is not None and (
                getattr(report_source, 'factory', None) is not factory
                or getattr(report_source, 'methods', None) is not methods
                or getattr(report_source, 'blobs', None) is not blobs
                or not callable(getattr(report_source, 'correction_review_evidence', None))):
            raise ApplicationError('REVIEW_SOURCE_AUTHORITY_MISMATCH')
        self.factory, self.access, self.scope = factory, access, scope
        self.methods, self.bindings = methods, bindings
        self.records, self.blobs, self.query = records, blobs, query_factory
        self.source_reviewer = source_reviewer
        self.report_source = report_source
        self.review_paths = frozenset(Path(path) for path in review_paths)
        if (not self.review_paths or any(not path.is_absolute() or path.resolve() != path
                or any(part.is_symlink() for part in (path, *path.parents)) for path in self.review_paths)):
            raise ApplicationError('REVIEW_SOURCE_AUTHORITY_MISMATCH')
        self.verifier_id, self.verifier_version = 'ordessa.declared-unit-records', '1'

    def _read_only_events(self, unit, receipt):
        cwd = Path(self.records.owner_read_unit(unit['unitId']).facts['privateRootFacts']['cwd'])
        def allowed(value):
            if type(value) is not str or not value or '..' in Path(value).parts:
                return False
            path = Path(value) if Path(value).is_absolute() else cwd / value
            return (path.resolve() in self.review_paths
                and not any(part.is_symlink() for part in (path, *path.parents)))

        def refuse():
            raise ApplicationError('REVIEW_READ_ONLY_SCOPE_VIOLATION')

        events = receipt.get('events')
        if type(events) is not list:
            refuse()
        permissions = {}
        tool_updates = {}
        for event in events:
            raw = event.get('raw') if isinstance(event, dict) else None
            if not isinstance(raw, dict):
                refuse()
            method, params = raw.get('method'), raw.get('params', {})
            if method is None:  # Incoming JSON-RPC response to a prior callback.
                continue
            if not isinstance(params, dict):
                refuse()
            if method == 'session/request_permission':
                tool = params.get('toolCall', {})
                locations = tool.get('locations', [])
                files = params.get('files', [])
                tool_id = params.get('toolCallId')
                if (raw.get('id') is None or type(tool_id) is not str or not tool_id
                        or params.get('approval') != 'file' or not isinstance(tool, dict)
                        or tool.get('toolCallId') != tool_id or tool.get('kind') != 'read'
                        or not isinstance(files, list) or not files
                        or not isinstance(locations, list) or not locations
                        or not all(allowed(path) for path in files)
                        or not all(isinstance(location, dict) and allowed(location.get('path'))
                                   for location in locations)
                        or tool_id in permissions):
                    refuse()
                options = params.get('options')
                if (not isinstance(options, list)
                        or sum(1 for option in options if isinstance(option, dict)
                               and option.get('kind') == 'allow_once') != 1):
                    refuse()
                permissions[tool_id] = {'paths': frozenset(files), 'complete': False}
            elif method == 'fs/read_text_file':
                if not allowed(params.get('path')):
                    refuse()
            elif method == 'fs/write_text_file' or type(method) is str and method.startswith('terminal/'):
                refuse()
            elif method == 'session/update':
                update = params.get('update', {})
                if not isinstance(update, dict):
                    refuse()
                if update.get('sessionUpdate') in {'tool_call', 'tool_call_update'}:
                    tool_id = params.get('toolCallId')
                    if (params.get('type') != update['sessionUpdate'] or type(tool_id) is not str
                            or not tool_id or update.get('toolCallId') != tool_id
                            or params.get('approval') not in (None, 'file')):
                        refuse()
                    item = tool_updates.setdefault(tool_id, {'final': False})
                    if item['final']:
                        refuse()
                    status = params.get('status')
                    decision = params.get('permissionDecision')
                    if status == 'in_progress' and decision is None:
                        continue
                    if (status == 'completed' and decision == 'approved'
                            and params.get('approval') == 'file'):
                        item['final'] = True
                        continue
                    refuse()
            else:
                # Only the original Unit's read callback and ACP status/update
                # channel are within this evidence policy.
                refuse()

        if set(tool_updates) != set(permissions):
            refuse()
        for tool_id, item in tool_updates.items():
            permission = permissions[tool_id]
            if not item['final'] or permission['complete']:
                refuse()
            permission['complete'] = True

    @staticmethod
    def is_report(plan):
        return any(type(target.ref) is SubmissionRef
                   for target in plan.requirement.expected_targets.targets)

    @staticmethod
    def operation_ref(plan, assignment):
        return declared_review_operation_ref(plan, assignment)

    def prompt_parameters(self, context, plan, request, assignment, session_id):
        """Reconstruct the complete request from frozen original owner inputs."""
        with self.methods.guard(context, plan.requirement.method_ref) as definition:
            selected = self.bindings.resolve_declared_submission_plan(context, plan, definition)
            with self.factory.begin(context.scope, 'read') as uow:
                submission = uow.submissions.resolve(plan.requirement.expected_targets.targets[0].ref)
                dispatch = resolve_declared_report_binding(uow, submission)
                package = uow.implementation.resolve_package(submission.package_ref)
                documents = [{'role': doc.role, 'source_ref': asdict(doc.source_ref),
                    'text': uow.implementation.read_prepared_document(package.ref, doc.role).decode('utf-8')}
                    for doc in package.payload.documents]
            resources = {}
            for name in ('independent-review-prompt', 'implementation-review-criteria', 'profile-selection-prompt'):
                exact = self.methods.resource_ref(context, plan.requirement.method_ref, name)
                resources[name] = {'ref': asdict(exact),
                    'text': self.methods.read_resource(context, exact).decode('utf-8')}
            binding = {'ordessa.declared-unit-review': {
                'plan': asdict(plan), 'request_version': assignment.request_version,
                'fence': assignment.fence, 'assignment_ref': asdict(assignment.ref),
                'reviewer_unit_ref': assignment.reviewer_unit_ref,
                'author_unit_ref': decode_json(dispatch.unit_ref_bytes)}}
            original_check_observation = None
            rework = None
            if submission.checkpoint_ref is not None:
                if self.report_source is None:
                    raise ApplicationError('REVIEW_SOURCE_AUTHORITY_MISMATCH')
                materials = getattr(self.report_source, 'report_content_rework_materials', None)
                if callable(materials):
                    rework = materials(context, submission, method_guarded=True)
                if rework is not None:
                    if (type(rework) is not dict
                            or rework.get('contract') != 'ordessa.report-content-rework-materials/1'):
                        raise ApplicationError('REVIEW_SOURCE_AUTHORITY_MISMATCH')
                    original_check_observation = rework.get('original_check_observation')
                else:
                    original_check_observation = self.report_source.correction_review_evidence(
                        context, submission)
                required = {'contract', 'checkpoint_ref', 'plan_ref', 'origin_operation_ref',
                    'journal_ref', 'excerpt_ref', 'tool_call_id', 'command_digest',
                    'command_utf8', 'excerpt_utf8', 'files', 'limitation'}
                if (type(original_check_observation) is not dict
                        or set(original_check_observation) != required
                        or original_check_observation.get('contract') !=
                           'ordessa.original-check-observation/1'
                        or original_check_observation.get('origin_operation_ref') !=
                           dispatch.execution_operation_ref
                        or type(original_check_observation.get('command_utf8')) is not str
                        or not original_check_observation['command_utf8']
                        or type(original_check_observation.get('excerpt_utf8')) is not str
                        or type(original_check_observation.get('files')) is not list):
                    raise ApplicationError('REVIEW_SOURCE_AUTHORITY_MISMATCH')
            body = {'package_ref': asdict(package.ref), 'method_ref': asdict(plan.requirement.method_ref),
                'documents': documents, 'report': submission.method_content.value,
                'original_check_observation': original_check_observation,
                'released_resources': resources, 'criterion': selected.standard.criteria[0].statement,
                'transport_response': {
                    'instruction': 'Return exactly one JSON object with verdict, rationale and findings. '
                        'Judge the complete pinned human criterion independently. Read only the four '
                        'authorized repository files. Do not edit files or run commands. '
                        'The original_check_observation is historical selected evidence only; it is '
                        'not a rerun for this review and not authenticated execution proof. Do not '
                        'run its command or claim that it passed. '
                        'Missing verification evidence must be identified; never invent a passed test. '
                        'This JSON object carries the human judgement, not a method ReviewRecord schema.',
                    'verdict': ['passed', 'rejected', 'cancelled', 'unknown'],
                    'rationale': 'nonempty string explaining the complete assessment',
                    'findings': ['specific evidence, unresolved checks, or requested rework']}}
            if rework is not None:
                body['report_content_rework'] = rework
            return {'sessionId': session_id, 'prompt': [
                {'type': 'text', 'text': canonical_bytes(binding).decode('utf-8')},
                {'type': 'text', 'text': canonical_bytes(body).decode('utf-8')}]}

    def _read(self, context, plan, raw_ref, standard, *, recording):
        try:
            value = decode_json(self.blobs.read_verified(raw_ref))
            required = {'contract', 'review_id', 'plan_digest', 'request_version', 'fence',
                'assignment_ref', 'unit_ref', 'operation_ref', 'params_ref', 'observation_ref'}
            if (type(value) is not dict or set(value) != required
                    or value['contract'] != CONTRACT or value['review_id'] != plan.review_id
                    or value['plan_digest'] != asdict(plan.plan_digest)):
                raise ValueError('exact native review locator required')
            with self.factory.begin(context.scope, 'read') as uow:
                request = uow.reviews.get_request(plan.review_id)
                persisted_plan = uow.reviews.get_plan(plan.review_id)
                assignment, control = uow.reviewer_assignments.active_for_review(plan.review_id)
                submission = uow.submissions.resolve(plan.requirement.expected_targets.targets[0].ref)
                dispatch = resolve_declared_report_binding(uow, submission)
            version = value['request_version']
            if (type(version) is not int or type(value['fence']) is not int
                    or persisted_plan != plan or assignment.plan_digest != plan.plan_digest
                    or assignment.method_ref != plan.requirement.method_ref
                    or assignment.request_version != version or assignment.fence != value['fence']
                    or request.fence != value['fence']
                    or (request.state, request.version) != (
                        ('requested', version) if recording else ('recorded', version + 1))
                    or control.state != 'active' or control.ref != assignment.ref
                    or assignment.roles != tuple(sorted(plan.reviewer_requirements))
                    or value['assignment_ref'] != asdict(assignment.ref)
                    or value['unit_ref'] != assignment.reviewer_unit_ref
                    or assignment.author_unit_ref_bytes != dispatch.unit_ref_bytes):
                raise ApplicationError('SUBMISSION_REVIEW_ASSIGNMENT_MISMATCH')
            author, unit = decode_json(dispatch.unit_ref_bytes), value['unit_ref']
            if (author['environmentNamespace'], author['unitId']) == (
                    unit['environmentNamespace'], unit['unitId']):
                raise ApplicationError('UNTRUSTED_REVIEWER')
            params_ref = decode_blob_ref(value['params_ref'])
            params = decode_json(self.blobs.read_verified(params_ref))
            session = self.records.owner_read_session(unit['unitId']).native_facts['sessionId']
            expected = self.prompt_parameters(context, plan, request, assignment, session)
            if (value['operation_ref'] != self.operation_ref(plan, assignment)
                    or canonical_bytes(params) != canonical_bytes(expected)):
                raise ApplicationError('REVIEW_REQUEST_CHANGED')
            digest = self.records.acp_prompt_input_digest(unit, params)
            observation = capture_execution_observation(self.records, self.blobs,
                authority_id=self.factory.authority_id, unit_ref=unit,
                operation_ref=value['operation_ref'], expected_prompt_digest=digest,
                query_invocation=self.query(context, unit, value['operation_ref'], digest),
                max_receipt_bytes=self.records.acp_turn_evidence_max_bytes)
            if canonical_bytes(asdict(observation)) != canonical_bytes(value['observation_ref']):
                raise ApplicationError('REVIEW_SOURCE_INCOMPLETE')
            receipt = decode_json(self.blobs.read_verified(observation.blob_ref))
            self._read_only_events(unit, receipt)
            summary, response = receipt.get('summary', {}), receipt.get('response', {})
            if (observation.state != 'completed'
                    or receipt.get('input') != {'unitRef': unit, 'params': params}
                    or summary.get('successfulRpcResponse') is not True
                    or summary.get('stopReason') != 'end_turn'
                    or type(summary.get('text')) is not str
                    or receipt.get('request', {}).get('raw', {}).get('jsonrpc') != '2.0'
                    or receipt.get('request', {}).get('raw', {}).get('method') != 'session/prompt'
                    or receipt.get('request', {}).get('raw', {}).get('params') != params
                    or type(response.get('id')) is not type(receipt.get('request', {}).get('raw', {}).get('id'))
                    or response.get('id') != receipt.get('request', {}).get('raw', {}).get('id')
                    or response.get('jsonrpc') != '2.0'
                    or 'result' not in response or 'error' in response
                    or response not in [event.get('raw') for event in receipt.get('events', [])]):
                raise ApplicationError('REVIEW_SOURCE_INCOMPLETE')
            judgement = decode_json(summary['text'].encode('utf-8'))
            if (type(judgement) is not dict or set(judgement) != {'verdict', 'rationale', 'findings'}
                    or judgement['verdict'] not in {'passed', 'rejected', 'cancelled', 'unknown'}
                    or type(judgement['rationale']) is not str or not judgement['rationale'].strip()
                    or type(judgement['findings']) is not list
                    or any(type(item) is not str for item in judgement['findings'])
                    or len(plan.check_keys) != 1):
                raise ApplicationError('REVIEW_RAW_RESPONSE_INVALID')
            status = {'passed': 'satisfied', 'rejected': 'violated',
                      'cancelled': 'unknown', 'unknown': 'unknown'}[judgement['verdict']]
            rationale = judgement['rationale'] + '\n' + '\n'.join(judgement['findings'])
            answers = (CriterionAnswer(plan.check_keys[0], status, (), rationale),)
            observations = review_observations(plan, standard, answers)
            actor = ActorRef(record_digest('unit-reviewer-actor', {
                'unit_ref': assignment.reviewer_unit_ref,
                'assignment': asdict(assignment.ref)}).hex, 'agent', 'ordessa-unit-records')
            evidence = record_digest(_RECORD_TYPE, {'assignment': asdict(assignment.ref),
                'operation_ref': value['operation_ref'], 'unit_ref': unit,
                'principal_id': context.principal_id, 'roles': assignment.roles,
                'plan_digest': asdict(plan.plan_digest), 'input_digest': digest})
            return assignment, control, actor, evidence, answers, observations
        except ApplicationError:
            raise
        except (ValueError, TypeError, KeyError, AttributeError, UnicodeError) as error:
            raise ApplicationError('REVIEW_SOURCE_INVALID') from error

    def _evidence(self, plan, raw_ref, facts):
        from ...domain.reviews.evidence import VerifiedReviewerEvidence
        assignment, control, actor, capability, answers, observations = facts
        evidence = VerifiedReviewerEvidence(plan.scope, actor, assignment.roles,
            self.verifier_id, self.verifier_version, control.version, plan.request_digest,
            raw_ref.digest, observations_digest(observations), capability)
        return VerifiedReviewResponse(evidence, answers)

    def verify_response(self, context, plan, request, raw_response_ref, *, standard):
        if not self.is_report(plan):
            return self.source_reviewer.verify_response(
                context, plan, request, raw_response_ref, standard=standard)
        with self.access.guard_current_capability(context, self.scope, CAPABILITY), \
                self.methods.guard(context, plan.requirement.method_ref) as definition:
            resolved = self.bindings.resolve_declared_submission_plan(context, plan, definition)
            if resolved.standard != standard:
                raise ApplicationError('METHOD_REQUIREMENTS_CHANGED')
            facts = self._read(context, plan, raw_response_ref, standard, recording=True)
            response = self._evidence(plan, raw_response_ref, facts)
            if request.review_id != plan.review_id or request.version != facts[0].request_version:
                raise ApplicationError('REVIEW_REQUEST_CHANGED')
            return response

    @contextmanager
    def guard_trust(self, context, records):
        report = tuple(record for record in records if self.is_report(record.plan))
        source = tuple(record for record in records if not self.is_report(record.plan))
        with ExitStack() as guards:
            current = list(guards.enter_context(self.source_reviewer.guard_trust(context, source)))
            if report:
                guards.enter_context(self.access.guard_current_capability(context, self.scope, CAPABILITY))
            for record in report:
                definition = guards.enter_context(self.methods.guard(context, record.plan.requirement.method_ref))
                standard = self.bindings.resolve_declared_submission_plan(context, record.plan, definition).standard
                with self.factory.begin(context.scope, 'read') as uow:
                    request = uow.reviews.get_request(record.plan.review_id)
                recording = request.state == 'requested'
                if recording:
                    # The original record command checks trust before its
                    # insert. Only that issued command may admit this pending
                    # response; ordinary readers still need a recorded request.
                    self.access.require(context, 'engineering.reviews.record')
                facts = self._read(context, record.plan, record.raw_response_ref, standard, recording=recording)
                expected = self._evidence(record.plan, record.raw_response_ref, facts).reviewer_evidence
                if expected != record.reviewer_evidence:
                    raise ApplicationError('UNTRUSTED_REVIEWER')
                current.append(CurrentReviewTrust(record.ref, self.verifier_id, facts[1].version))
            yield tuple(current)
