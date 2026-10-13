"""Exact acceptance expansion over persisted Submission result identities.

The SubmissionRef and output revisions below are synthetic pure values. They
exercise closed projection only and do not authenticate a Submission or review.
"""
from pathlib import Path
import tempfile
import json
from dataclasses import replace

import yaml

import pytest

from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError
from ordessa_engineering.domain.reviews.models import CriterionSetRef
from ordessa_engineering.domain.reviews.requirements import (
    ReviewRequirementTemplate, SubjectSelector, TemplateCheck, TemplateTarget,
    expand_submission_requirement,
)
from ordessa_engineering.domain.reviews.refs import SubmissionRef

from test_method_per_claim import ROOT, SCOPE, published, revision, binding
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.snapshots import EngineeringTargetBindings
from ordessa_engineering.application.orchestration.method_bridge import MethodBridge


INTENT = 'implementation-intent-test'


def _template(*, phase='quality-phase'):
    slot = TemplateTarget('output', SubjectSelector('result_of_intent', implementation_intent_id=INTENT))
    return ReviewRequirementTemplate(SCOPE, 'acceptance-template', 1, 'acceptance', (slot,),
        _method_ref(), CriterionSetRef('acceptance-standard', 1, Digest('sha256', 'a' * 64)),
        (TemplateCheck(slot, 'acceptance-check'),), ('reviewer',), phase)


def _method_ref():
    from ordessa_engineering.domain.artifacts.method_binding import MethodRef
    return MethodRef('acceptance-method', '1.0.0', 1, Digest('sha256', 'b' * 64))


def _submission(submission_id='submission-one'):
    return SubmissionRef(SCOPE.realm_id, SCOPE.project_id, submission_id, Digest('sha256', 'c' * 64))


def _output(refs):
    return {r.ref: r for r in refs}


def test_deferred_template_expands_every_exact_output_and_binds_submission_identity():
    template = _template()
    first, second = revision('accept-one'), revision('accept-two')
    outputs = (first.ref, second.ref)
    revisions = _output((first, second))
    expanded = expand_submission_requirement(template, _submission(), INTENT, outputs, revisions)

    assert {target.ref for target in expanded.expected_targets.targets} == set(outputs)
    assert {check.target.ref for check in expanded.required_check_keys} == set(outputs)
    assert expanded.purpose == 'acceptance'
    assert expanded.requirement_id != expand_submission_requirement(
        template, _submission('submission-two'), INTENT, outputs, revisions).requirement_id


def test_submission_expansion_rejects_empty_blob_missing_and_wrong_intent_results():
    template = _template()
    output = revision('accept-valid')
    blob = BlobRef(Digest('sha256', 'd' * 64), 3, 'application/json', 'blob-test')
    revisions = _output((output,))
    with pytest.raises(ReferenceError, match='SUBMISSION_OUTPUT_UNSUPPORTED'):
        expand_submission_requirement(template, _submission(), INTENT, (), revisions)
    with pytest.raises(ReferenceError, match='SUBMISSION_OUTPUT_UNSUPPORTED'):
        expand_submission_requirement(template, _submission(), INTENT, (blob,), {})
    with pytest.raises(ReferenceError, match='UNRESOLVED_REVIEW_TARGET'):
        expand_submission_requirement(template, _submission(), INTENT, (output.ref,), {})
    with pytest.raises(ReferenceError, match='IMPLEMENTATION_INTENT_MISMATCH'):
        expand_submission_requirement(template, _submission(), 'other-intent', (output.ref,), revisions)


def test_acceptance_bindings_cannot_relabel_quality_standard_from_actual_2_5():
    candidate = ROOT / 'candidates/2.4.0'
    with tempfile.TemporaryDirectory() as directory:
        lib = EngineeringLibrary.create((Path(directory) / 'acceptance.sqlite').resolve(),
            library_id='acceptance-test', schema_version=10)
        try:
            snapshot = published(lib, candidate)
            standards = [standard for standard in snapshot.program.standard_definitions
                         if standard.purpose == 'acceptance']
            assert len(standards) == 1
            document = revision('acceptance-target')
            original = binding((document,))
            target = original.targets.targets[0]
            required_inputs = tuple(sorted({name for criterion in standards[0].criteria
                                            for name in (criterion.required_inputs or ())}))
            selected = EngineeringTargetBindings(original.scope, original.targets, ((target, 'submission'),),
                required_inputs, original.eligible_reviewer_roles, 'acceptance',
                original.requirement_version, original.criterion_set_version, 'acceptance', 'acceptance')
            requirements = MethodBridge().review_requirements(snapshot, selected, revisions=(document,))
            assert len(requirements) == 1 and requirements[0].purpose == 'acceptance'

            quality_standards = [standard for standard in snapshot.program.standard_definitions
                                 if standard.purpose == 'quality']
            quality_inputs = tuple(sorted({name for standard in quality_standards
                                           for criterion in standard.criteria
                                           for name in (criterion.required_inputs or ())}))
            quality = replace(selected, document_types=((target, 'spec-kit-package'),),
                input_slots=quality_inputs, phase_key='quality_review',
                workflow_node_id='quality_review')
            with pytest.raises(ApplicationError, match='METHOD_REVIEW_PURPOSE_UNAVAILABLE'):
                MethodBridge().review_requirements(snapshot, quality, revisions=(document,))
        finally:
            lib.close()

    # 2.5 has an acceptance standard declaration in raw candidate bytes, but
    # the registered validation evidence marks the candidate compiler-unknown;
    # this is not treated as a published MethodSnapshot or green implementation.
    candidate_25 = ROOT / 'candidates/2.5.0'
    raw_standard = yaml.safe_load((candidate_25 / 'standards/acceptance.yaml').read_bytes())
    from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader
    from ordessa_engineering.methods.loading.loader import load_method
    from ordessa_engineering.methods.definitions.models import MethodSource
    from ordessa_engineering.methods import compile_method
    from ordessa_engineering.application.orchestration.method_bridge import command_capabilities
    assert raw_standard['purpose'] == 'acceptance'
    # Historical validation JSON layout is not a runtime capability authority.
    # Keep the original unsupported assertion, using actual current loader/compiler.
    loaded = load_method(MethodSource(candidate_25), FileResourceReader())
    assert loaded.ok, loaded.error
    compiled = compile_method(loaded.value, command_capabilities(), 'engineering-test/current-host')
    assert not compiled.ok
    assert compiled.error.code == 'UNKNOWN_CAPABILITY'
