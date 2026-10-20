"""Original execution/material provenance admission, never a client verdict."""
from typing import Protocol


class SubmissionSourcePort(Protocol):
    def guard_submission(self, context, submission, package):
        """Verify exact original dispatch/package/grant/record correlation.

        Admit only the selected method's explicitly submitted documents and
        reports, their immutable output revisions and original execution
        identities. Retain current method/source guards through COMMIT.
        Execution-code, Git, tree, test and effect inspection belongs to the
        method's workers/checkers; this port must not scan or verify those
        claims. Their reports remain assertions until required reviews pass.
        An ACP result or a caller-created DTO alone cannot implement this port.
        """
        ...


class SubmissionReportAdmission(Protocol):
    """Typed admission produced by the selected Method/report source owner.

    This is not caller input or an authorization.  It binds the report body and
    fixed output revisions to one captured native execution observation.
    """
    method_ref: object
    report_schema_ref: object
    output_refs: tuple
    report_content_digest: object
    execution_operation_ref: str
    prompt_input_digest: object
    query_digest: str
    captured_observation_ref: object


class SubmissionReportSourcePort(Protocol):
    def guard_report(self, context, package, submission, captured_observation):
        """Yield an admission from current selected Method and actual response.

        Implementations must resolve the active Method and its declared report
        schema/roles/standards, verify the actual Unit response and output
        revisions, and retain those source/control guards through COMMIT.  A
        reconstructed DTO, ACP state, or self-hash is not sufficient evidence.
        """
        ...


class SubmissionRepository(Protocol):
    def create(self, record): ...
    def resolve(self, ref): ...


def report_input_schema(schema_version=None):
    """Closed original Submission transport; report mode has a distinct operation."""
    from ..orchestration.owner_capabilities import owner_capabilities
    descriptor = next(d for d in owner_capabilities()
                      if d.capability_id == 'engineering.submissions.record_report')
    schema = {'$schema':'https://json-schema.org/draft/2020-12/schema',
              '$id':descriptor.contract['input_schema_id'], **descriptor.contract['input_schema']}
    if schema_version in (1, 2):
        from copy import deepcopy
        schema = deepcopy(schema)
        schema['properties']['record'] = schema['properties']['record']['oneOf'][schema_version - 1]
    return schema


def agent_report_input_schema():
    """Current Agent report contract; never infer it from untrusted version text."""
    from ..orchestration.owner_capabilities import agent_report_capability
    descriptor = agent_report_capability()
    return {'$schema':'https://json-schema.org/draft/2020-12/schema',
            '$id':descriptor.contract['input_schema_id'], **descriptor.contract['input_schema']}
