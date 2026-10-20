"""Trusted product bindings to original method validators and Unit identities.

Methods own schemas/phase policy, Engineering owns submission/review/Work,
Execution owns authorized identity/result reads. No wire policy interpreter,
truth scanner, new business state or verified-test producer is installed here.
"""
import hashlib
import json
from contextlib import contextmanager
from types import SimpleNamespace
from urllib.parse import urljoin

from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.orchestration.method_content import document_type_for_payload
from ordessa_engineering.domain.artifacts.models import MethodContent, MethodPayload
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.methods.loading.parsing import parse_document
from ordessa_engineering.methods.definitions.models.compiled import thaw_value


def decode_method_report(snapshot, schema_ref, text):
    """Decode strict JSON using the exact original method document schema.

    Returns original MethodContent, never a Submission/Review or acceptance.
    A method schema saying ``asserted`` remains asserted, even for complete.
    """
    if type(text) is not str or len(text.encode('utf-8')) > 262144:
        raise ApplicationError('SUBMISSION_REPORT_OUTPUT_INVALID')
    definitions = tuple(d for d in snapshot.program.document_definitions
        if d.schema_resource.resource_id == schema_ref.resource_id
        and d.schema_resource.sha256 == schema_ref.resource_digest.hex)
    if len(definitions) != 1:
        raise ApplicationError('METHOD_DOCUMENT_TYPE_UNAVAILABLE')
    try:
        value = parse_document(text.encode('utf-8'), 'application/json', 'recorded-unit-output.json')
        content = MethodContent.from_value(schema_ref, value)
        schema = thaw_value(definitions[0].value_schema)
        location = 'https://ordessa.invalid/method/' + schema_ref.logical_path
        payload = MethodPayload('application/json', urljoin(location, schema.get('$id', location)), content)
        document_type_for_payload(snapshot, payload)
    except ApplicationError:
        raise
    except Exception as error:
        raise ApplicationError('SUBMISSION_REPORT_OUTPUT_INVALID') from error
    return content


class OriginalMethodReportSource:
    """Consume original SubmissionReportSourcePort; actual response only.

    Engineering already captures through original records before calling this
    port. Its dispatch/Grant/package binding and pending-review write remain
    entirely in SubmissionUseCases.record_report, not in this adapter.
    """
    def __init__(self, factory, methods, blobs, access, *, scope, phase_key):
        if methods.factory is not factory or blobs.authority_id != factory.authority_id:
            raise ApplicationError('METHOD_AUTHORITY_MISMATCH')
        self.factory, self.methods, self.blobs, self.access, self.scope = factory, methods, blobs, access, scope
        self.phase_key = phase_key

    @contextmanager
    def guard_report(self, context, package, submission, captured_observation):
        if (context.scope != submission.scope or submission.method_content is None
                or captured_observation.authority_id != self.factory.authority_id
                or captured_observation.state != 'completed'):
            raise ApplicationError('SUBMISSION_REPORT_SOURCE_INVALID')
        schema_ref = submission.method_content.schema_ref
        with self.access.guard_current_capability(context,self.scope,'engineering.submissions.record_report'):
            with self.methods.guard_selected(context) as snapshot:
                content = submission.method_content
                nodes = tuple(n for n in snapshot.program.workflow.steps if n.id == self.phase_key)
                if len(nodes) != 1 or getattr(nodes[0], 'config', None) is None:
                    raise ApplicationError('SUBMISSION_REPORT_METHOD_BINDING_UNAVAILABLE')
                strategy = thaw_value(nodes[0].config).get('unit_submission_review_strategy', {})
                selected_schema = strategy.get('fixed_delivery', {}).get('author_result_schema')
                if selected_schema != schema_ref.resource_id:
                    raise ApplicationError('SUBMISSION_REPORT_METHOD_BINDING_UNAVAILABLE')
                if schema_ref.method_ref != package.payload.method_ref:
                    raise ApplicationError('SUBMISSION_REPORT_BINDING_MISMATCH')
                receipt = json.loads(self.blobs.read_verified(captured_observation.blob_ref))
                execution = submission.execution_ref
                unit = {'environmentNamespace':execution.environment_namespace, 'unitId':execution.unit_id,
                    'ownerProviderRef':json.loads(execution.owner_provider_ref_bytes), 'sourceRevision':execution.source_revision}
                summary = receipt.get('summary') or {}
                if (captured_observation.unit_ref != unit
                        or captured_observation.operation_ref != execution.operation_ref
                        or captured_observation.expected_prompt_digest != 'sha256:'+execution.prompt_input_digest.hex
                        or captured_observation.blob_ref != execution.captured_observation_ref
                        or receipt.get('unitRef') != unit or receipt.get('operationRef') != execution.operation_ref
                        or receipt.get('inputDigest') != captured_observation.expected_prompt_digest
                        or receipt.get('state') != 'completed'
                        or summary.get('successfulRpcResponse') is not True
                        or summary.get('stopReason') != 'end_turn'):
                    raise ApplicationError('SUBMISSION_REPORT_SOURCE_INVALID')
                decoded = decode_method_report(snapshot, schema_ref, summary.get('text'))
                if decoded.value_bytes != content.value_bytes:
                    raise ApplicationError('SUBMISSION_REPORT_RESPONSE_MISMATCH')
                # Private implementation of the original port's admission view;
                # no new public DTO, state machine, grant or host descriptor.
                yield SimpleNamespace(method_ref=schema_ref.method_ref,report_schema_ref=schema_ref,
                    output_refs=submission.output_refs,
                    report_content_digest=Digest('sha256',hashlib.sha256(content.value_bytes).hexdigest()),
                    execution_operation_ref=execution.operation_ref,prompt_input_digest=execution.prompt_input_digest,
                    query_digest=captured_observation.query_digest,captured_observation_ref=captured_observation.blob_ref)


class OriginalMethodUnitReviewPolicy:
    """Apply a selected phase's declaration to authorized original identities.

    unit_query_factory selects original query invocation/digest from trusted
    composition. resolve_unit_reference authenticates all UnitRef fields,
    including released historical Units. No live Manager or ActorRef surrogate.
    Method/source guards are held by OriginalUnitReviewerSource around this.
    """
    def __init__(self, records, *, unit_query_factory):
        self.records, self.queries = records, unit_query_factory

    @contextmanager
    def __call__(self, context, snapshot, plan, run):
        if not callable(self.queries):
            raise ApplicationError('UNIT_IDENTITY_QUERY_AUTHORITY_UNAVAILABLE')
        nodes = tuple(n for n in snapshot.program.workflow.steps if n.id == plan.requirement.phase_key)
        if len(nodes) != 1 or getattr(nodes[0], 'config', None) is None:
            raise ApplicationError('METHOD_REVIEWER_POLICY_UNAVAILABLE')
        strategy = thaw_value(nodes[0].config).get('unit_submission_review_strategy')
        if (type(strategy) is not dict or strategy.get('schema_version') != 1
                or strategy.get('declaration_kind') != 'method_strategy_not_host_capability_or_authorization'):
            raise ApplicationError('METHOD_REVIEWER_POLICY_UNAVAILABLE')
        constraint = strategy.get('roles', {}).get('identity_constraint')
        if constraint != 'original_author_unit_identity_must_differ_from_original_reviewer_unit_identity':
            raise ApplicationError('METHOD_IDENTITY_CONSTRAINT_UNSUPPORTED')
        identities=[]
        for encoded in (run.author_unit_utf8,run.reviewer_unit_utf8):
            reference=json.loads(encoded)
            invocation,digest=self.queries(context,reference,run)
            original=self.records.resolve_unit_reference(reference,invocation,input_digest=digest)
            if canonical_bytes(original.public_ref) != canonical_bytes(reference):
                raise ApplicationError('UNIT_REVIEW_IDENTITY_MISMATCH')
            identities.append((original.public_ref['environmentNamespace'],original.public_ref['unitId']))
        if identities[0] == identities[1]:
            raise ApplicationError('METHOD_REVIEWER_CONSTRAINT_FAILED')
        # Reads verify immutable identities, not lifecycle/current effect grants.
        # Original method/source capability guards remain held by the caller.
        yield


def unit_reviewer_source_factory(*, records, runs, query_factory, unit_query_factory,
                                 decode_answers, roles):
    """Ready trusted root entry; missing versioned review decoder still refuses."""
    from .engineering_unit_reviewer_source import OriginalUnitReviewerSource
    def build(factory,methods,blobs,access,scope):
        return OriginalUnitReviewerSource(records=records,blobs=blobs,access=access,scope=scope,
            method_control=methods,runs=runs,query_factory=query_factory,decode_answers=decode_answers,
            policy_guard=OriginalMethodUnitReviewPolicy(records,unit_query_factory=unit_query_factory),roles=roles)
    return build


class OriginalRecordedUnitReviewQueries:
    """Use existing UnitServices query issuance for original author/reviewer.

    author_submission_resolver is trusted Work binding resolving an exact original
    SubmissionRef, never latest or client actor/ref. request_factory produces the
    existing RequestKey through the configured original caller mapping.
    """
    def __init__(self, services, *, request_factory, author_submission_resolver):
        from ordessa_units.public import UnitServices
        from ordessa_units.management import UnitManager
        if (type(services) is not UnitServices or type(services.unit_manager) is not UnitManager
                or not callable(request_factory) or not callable(author_submission_resolver)):
            raise ApplicationError('UNIT_IDENTITY_QUERY_AUTHORITY_UNAVAILABLE')
        self.services,self.requests,self.authors=services,request_factory,author_submission_resolver

    def _issue(self, context, run, unit_ref, operation_ref, prompt_digest):
        from ordessa_infrastructure.identifiers import RequestKey
        request=self.requests(context,run,unit_ref,operation_ref,prompt_digest)
        if type(request) is not RequestKey:
            raise ApplicationError('UNIT_IDENTITY_QUERY_AUTHORITY_UNAVAILABLE')
        query=self.services.authorize_acp_turn_query(request,unit_ref,operation_ref,
            expected_prompt_input_digest=prompt_digest)
        return query,self.services.unit_manager.records.acp_turn_query_digest(unit_ref,operation_ref,prompt_digest)

    def __call__(self, context, run):
        return self._issue(context,run,json.loads(run.reviewer_unit_utf8),
            run.observation.operation_ref,run.observation.expected_prompt_digest)[0]

    def identity_query(self, context, reference, run):
        from ordessa_engineering.domain.changes.submission import Submission
        if canonical_bytes(reference)==run.reviewer_unit_utf8:
            return self._issue(context,run,reference,run.observation.operation_ref,run.observation.expected_prompt_digest)
        if canonical_bytes(reference)!=run.author_unit_utf8:
            raise ApplicationError('UNIT_REVIEW_IDENTITY_MISMATCH')
        submission=self.authors(context,run)
        if type(submission) is not Submission or submission.scope!=context.scope:
            raise ApplicationError('SUBMISSION_AUTHOR_SOURCE_UNAVAILABLE')
        execution=submission.execution_ref
        original={'environmentNamespace':execution.environment_namespace,'unitId':execution.unit_id,
                  'ownerProviderRef':json.loads(execution.owner_provider_ref_bytes),'sourceRevision':execution.source_revision}
        if canonical_bytes(original)!=canonical_bytes(reference):
            raise ApplicationError('UNIT_REVIEW_IDENTITY_MISMATCH')
        return self._issue(context,run,reference,execution.operation_ref,'sha256:'+execution.prompt_input_digest.hex)


def attach_method_report_ports(base_ports, *, factory, methods, blobs, access, scope,
                               phase_key, execution_records, execution_query_factory):
    """Attach new original Facade ports; preserve caller-selected review/consent.

    Use from build_product_runtime(application_ports_factory=...). Phase
    comes from the original Work selection. This does not choose a method,
    publish it, create a Unit, grant capability, or replace the JEV reviewer.
    """
    from dataclasses import replace
    from ordessa_system_access_bindings.engineering_wire import EngineeringApplicationPorts
    if type(base_ports) is not EngineeringApplicationPorts or execution_records is None or not callable(execution_query_factory):
        raise ApplicationError('SUBMISSION_REPORT_SOURCE_UNAVAILABLE')
    return replace(base_ports,submission_report_source=OriginalMethodReportSource(
        factory,methods,blobs,access,scope=scope,phase_key=phase_key),
        execution_records=execution_records,execution_query_factory=execution_query_factory)
