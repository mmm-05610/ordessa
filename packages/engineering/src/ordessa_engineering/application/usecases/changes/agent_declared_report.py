"""Ordinary Agent Work reports on the original schema17 business authority.

The independent Agent owner supplies the capture and Profile provenance. Report
claims remain authored assertions; no checkout/test/effect verification occurs.
"""
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import hashlib

from jsonschema import Draft202012Validator
from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ordessa_infrastructure.encoding.canonical_json import LIBRARY_JSON_PROFILE
from ...contracts.errors import ApplicationError
from ...contracts.execution_observations import AgentExecutionObservationRef
from ...orchestration.owner_capabilities import agent_report_capability
from ..packages.authorization import resolve_work_package_authorization
from ....domain.approvals.implementation import WorkPackageAuthorizationIntent
from ....domain.changes.agent_dispatch import AgentWorkDispatchBinding
from ....domain.changes.agent_dispatch_codec import decode_agent_dispatch
from ....domain.changes.agent_submission_report import AgentSubmissionReport
from ....domain.changes.dispatch import package_ref_projection
from ....domain.changes.submission_binding import validate_submission_graph
from ....domain.common.models.values import Digest
from ....domain.common.outcomes.diagnostics import ReferenceError
from ....domain.packages.models import PreparedPackagePayload


def resolve_agent_declared_report_binding(uow, submission):
    """Resolve the actual scoped Agent attempt, keeping native operation separate."""
    if type(submission) is not AgentSubmissionReport or submission.scope != uow.scope:
        raise ApplicationError('SUBMISSION_DISPATCH_BINDING_MISMATCH')
    if submission.checkpoint_ref is not None:
        raise ApplicationError('AGENT_REPORT_CHECKPOINT_UNAVAILABLE')
    execution = submission.execution_ref
    try:
        row = uow.work_dispatch.by_operation(execution.engineering_attempt_ref, uow.scope)
    except ApplicationError as error:
        if error.code == 'NOT_FOUND':
            raise ApplicationError('SUBMISSION_DISPATCH_BINDING_UNAVAILABLE') from error
        raise
    binding = decode_agent_dispatch(row['binding_bytes'])
    if (type(binding) is not AgentWorkDispatchBinding
            or binding.subject != {'subject_kind': 'frozen_package',
                'subject_ref': package_ref_projection(submission.package_ref)}
            or binding.scope != uow.scope or binding.package_ref != submission.package_ref
            or binding.approval_ref is None or submission.authorization_refs != (binding.approval_ref,)
            or binding.engineering_attempt_ref != execution.engineering_attempt_ref
            or binding.agent_ref_bytes != execution.agent_ref_bytes or binding.turn_ref_bytes != execution.turn_ref_bytes
            or binding.prompt_input_digest != execution.prompt_input_digest
            or binding.expected_query_digest != execution.query_digest
            or binding.run_id != row['run_id'] or binding.step_id != row['step_id']
            or binding.attempt != row['attempt'] or binding.work['dispatch_key'] != row['run_id']
            or row['execution_operation_ref'] != binding.engineering_attempt_ref
            or row['dispatch_fence'] != binding.fence or row['dispatch_phase'] != 'completed'
            or row['result_blob_json'] != canonical_bytes(asdict(execution.captured_observation_ref)).decode('utf-8')
            or 'implementation_report' not in binding.required_results):
        raise ApplicationError('SUBMISSION_DISPATCH_BINDING_MISMATCH')
    # New continuation/checkpoint contracts are not inferred from Unit markers.
    if binding.attempt != 1 or row['continuation'] is not None:
        raise ApplicationError('AGENT_REPORT_CONTINUATION_UNAVAILABLE')
    grant = uow.authorization.get_grant(binding.approval_ref)
    if type(grant.intent) is not WorkPackageAuthorizationIntent or grant.intent.digest != binding.intent_digest:
        raise ApplicationError('SUBMISSION_DISPATCH_BINDING_MISMATCH')
    authorization, work = grant.intent.authorization, binding.work
    if (authorization.work_id != work['work_id'] or authorization.action_id != work['action_id']
            or authorization.step_id != work['step_id'] or binding.step_id != authorization.step_id
            or not set(action for action, _ in binding.action_instances) <= set(authorization.actions)):
        raise ApplicationError('SUBMISSION_DISPATCH_BINDING_MISMATCH')
    facts = resolve_work_package_authorization(uow, authorization)
    try:
        validate_submission_graph(submission, facts.package, grant, (), ())
    except ReferenceError as error:
        raise ApplicationError(error.code) from error
    return binding


@dataclass(frozen=True)
class VerifiedAgentReport:
    method_ref: object
    report_schema_ref: object
    output_refs: tuple
    report_content_digest: Digest
    execution_operation_ref: str
    prompt_input_digest: Digest
    query_digest: str
    captured_observation_ref: object
    agent_ref_bytes: bytes
    turn_ref_bytes: bytes
    engineering_attempt_ref: str


class DeclaredAgentWorkReportSource:
    declared_agent_work_reports = True

    def __init__(self, factory, method_control, blobs, records, query_factory):
        if (getattr(method_control, 'factory', None) is not factory
                or any(not callable(getattr(method_control, name, None)) for name in ('guard', 'resource_ref', 'read_resource'))
                or getattr(blobs, 'authority_id', None) != getattr(factory, 'authority_id', None)
                or getattr(records, 'blob_store', None) is not blobs or not callable(query_factory)
                or any(not callable(getattr(records, name, None)) for name in ('capture_reference', 'read_agent_binding'))):
            raise ApplicationError('SUBMISSION_REPORT_AUTHORITY_MISMATCH')
        self.factory, self.methods, self.blobs = factory, method_control, blobs
        self.records, self.query_factory = records, query_factory
        self.report_descriptor = agent_report_capability()

    @contextmanager
    def guard_report(self, context, package, submission, captured):
        if (type(submission) is not AgentSubmissionReport or type(package.payload) is not PreparedPackagePayload
                or context.scope != submission.scope or package.scope != context.scope):
            raise ApplicationError('SUBMISSION_REPORT_BINDING_MISMATCH')
        if submission.checkpoint_ref is not None:
            raise ApplicationError('AGENT_REPORT_CHECKPOINT_UNAVAILABLE')
        method = package.payload.method_ref
        with self.methods.guard(context, method) as declaration:
            with self.factory.begin(context.scope, 'read') as uow:
                binding = resolve_agent_declared_report_binding(uow, submission)
                if uow.implementation.resolve_package(binding.package_ref) != package:
                    raise ApplicationError('SUBMISSION_REPORT_BINDING_MISMATCH')
                grant = uow.authorization.get_grant(binding.approval_ref)
            actions = tuple(action for action in declaration.actions if action.action_id == binding.work['action_id'])
            steps = () if len(actions) != 1 else tuple(step for step in actions[0].steps if step.step_id == binding.step_id)
            if (len(steps) != 1 or steps[0].name != 'implement-approved-package' or steps[0].kind != 'invoke'
                    or 'implementation_report' not in steps[0].outputs
                    or not {'implementation-report-schema', 'agent-report-contract'} <= {r.resource_id for r in actions[0].resources}):
                raise ApplicationError('SUBMISSION_REPORT_METHOD_MISMATCH')
            contract_ref = self.methods.resource_ref(context, method, 'agent-report-contract')
            descriptor = self.report_descriptor
            expected = {'$schema': 'https://json-schema.org/draft/2020-12/schema',
                '$id': descriptor.contract['input_schema_id'], **descriptor.contract['input_schema'],
                'x-ordessa-capability-binding': {name: getattr(descriptor, name) for name in
                    ('capability_id', 'kind', 'interface_version', 'contract_digest')}}
            if decode_json(self.methods.read_resource(context, contract_ref)) != expected:
                raise ApplicationError('AGENT_REPORT_METHOD_CONTRACT_MISMATCH')
            exact = self.methods.resource_ref(context, method, 'implementation-report-schema')
            schema = decode_json(self.methods.read_resource(context, exact))
            content = submission.method_content
            if content.schema_ref != exact or not Draft202012Validator(schema).is_valid(content.value):
                raise ApplicationError('SUBMISSION_REPORT_SCHEMA_MISMATCH')
            invocation = self.query_factory(binding)
            if invocation is None:
                raise ApplicationError('EXECUTION_QUERY_AUTHORITY_REQUIRED')
            # Independent authorized source reads: neither report text, prompt,
            # Grant nor a caller-created capture can attest Profile identity.
            provenance = self.records.read_agent_binding(decode_json(binding.agent_ref_bytes), read_invocation=invocation)
            current = self.records.capture_reference(submission.execution_ref, read_invocation=invocation)
            if type(captured) is not AgentExecutionObservationRef or current != captured:
                raise ApplicationError('SUBMISSION_EXECUTION_OBSERVATION_CHANGED')
            execution = submission.execution_ref
            if (captured.state != 'completed' or captured.agent_ref_bytes != binding.agent_ref_bytes
                    or captured.turn_ref_bytes != binding.turn_ref_bytes
                    or captured.engineering_attempt_ref != binding.engineering_attempt_ref
                    or captured.query_digest != binding.expected_query_digest
                    or captured.operation_ref != execution.operation_ref
                    or captured.expected_prompt_digest != 'sha256:' + binding.prompt_input_digest.hex
                    or captured.blob_ref != execution.captured_observation_ref
                    or captured.authority_id != self.factory.authority_id
                    or provenance.source_revision != execution.source_revision
                    or not captured.report_text):
                raise ApplicationError('SUBMISSION_REPORT_OUTPUT_UNAVAILABLE')
            from ordessa_execution_agents.sdk.interactions import TurnReceipt
            receipt = TurnReceipt.decode(decode_json(self.blobs.read_verified(captured.blob_ref)))
            params = decode_json(self.blobs.read_verified(binding.prompt_ref))
            observation = decode_json(receipt.observation_bytes)
            protocol = observation.get('protocol', {})
            frames = protocol.get('frames')
            responses = [] if type(frames) is not list else [frame for frame in frames if type(frame) is dict and 'method' not in frame]
            if (receipt.state != 'completed' or receipt.agent_operation_ref != execution.operation_ref
                    or receipt.turn_ref.projection() != decode_json(binding.turn_ref_bytes)
                    or receipt.engineering_attempt_ref != binding.engineering_attempt_ref
                    or receipt.input_digest != 'sha256:' + binding.prompt_input_digest.hex
                    or receipt.session_id != params.get('sessionId')
                    or protocol.get('protocolId') != 'acp' or 'reason' in protocol
                    or len(responses) != 1 or responses[0].get('id') != execution.operation_ref
                    or responses[0].get('jsonrpc') != '2.0' or 'error' in responses[0]
                    or type(responses[0].get('result')) is not dict
                    or responses[0]['result'].get('stopReason') != 'end_turn'):
                raise ApplicationError('SUBMISSION_REPORT_OUTPUT_UNAVAILABLE')
            prompt_digest = 'sha256:' + hashlib.sha256(canonical_bytes({
                'schemaVersion': 'agent-prompt-input/1', 'instanceRef': decode_json(binding.agent_ref_bytes),
                'sessionId': receipt.session_id, 'params': params}, profile=LIBRARY_JSON_PROFILE)).hexdigest()
            if prompt_digest != receipt.input_digest:
                raise ApplicationError('SUBMISSION_REPORT_BINDING_MISMATCH')
            try:
                raw = canonical_bytes(decode_json(captured.report_text.encode('utf-8')))
            except (ValueError, TypeError, UnicodeError):
                raise ApplicationError('SUBMISSION_REPORT_OUTPUT_INVALID') from None
            if raw != content.value_bytes or self.blobs.read_verified(submission.output_refs[0]) != raw:
                raise ApplicationError('SUBMISSION_REPORT_OUTPUT_MISMATCH')
            task = decode_json(params['prompt'][0]['text'].encode('utf-8'))
            profile = provenance.profile_ref
            actual_profile = {'environmentNamespace': profile.environment_namespace, 'profileId': profile.profile_id,
                'manifestRevision': profile.revision, 'contentDigest': profile.digest}
            if (content.value['package_digest'] != 'sha256:' + package.ref.digest.hex
                    or content.value['profile_ref'] != actual_profile or task.get('profile_ref') != actual_profile
                    or any(not any(e.environment_id == profile.environment_namespace and e.profile_id == profile.profile_id
                            and 'sha256:' + e.profile_digest.hex == profile.digest for e in scope.environment_refs)
                        for _, scope in grant.intent.authorization.scope_by_action)):
                raise ApplicationError('SUBMISSION_REPORT_BINDING_MISMATCH')
            yield VerifiedAgentReport(method, exact, submission.output_refs,
                Digest('sha256', hashlib.sha256(raw).hexdigest()), execution.operation_ref,
                binding.prompt_input_digest, captured.query_digest, captured.blob_ref,
                binding.agent_ref_bytes, binding.turn_ref_bytes, binding.engineering_attempt_ref)
