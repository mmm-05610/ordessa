"""Finite method-authored answer projection; no model call or grant authority."""
from ..contracts.errors import ApplicationError
from ..contracts.reviewer_admission import CriterionAnswer, NominalCriterionResolution
from ...domain.reviews.models import ReviewPlan, CheckKey
from ...domain.artifacts.refs import ArtifactRevisionRef
from ...methods.definitions.models.compiled import (
    thaw_value, ChoiceVocabulary, ScoreVocabulary, NoulVocabulary,
)
from ...methods.validation.nominal import nominal_declaration_error


def _criterion(plan, standard, check_key):
    if (type(plan) is not ReviewPlan or type(check_key) is not CheckKey or check_key not in plan.check_keys
            or getattr(standard,'standard_id',None) != plan.requirement.criterion_set_ref.criterion_set_id
            or getattr(getattr(standard,'resource_ref',None),'sha256',None) != plan.requirement.criterion_set_ref.digest.hex):
        raise ApplicationError('METHOD_REQUIREMENTS_CHANGED')
    criteria = [c for c in standard.criteria if c.criterion_id == check_key.criterion_id]
    if len(criteria)!=1 or len(criteria[0].checks)!=1 or criteria[0].decision_policy is not None:
        raise ApplicationError('REVIEW_CHECK_EXECUTION_UNAVAILABLE')
    return criteria[0]


def _vocabulary(criterion):
    vocabulary = criterion.answer_vocabulary
    if type(vocabulary) is ChoiceVocabulary:
        return 'choice', tuple(option.option_id for option in vocabulary.options)
    if type(vocabulary) is ScoreVocabulary:
        return 'score', tuple(level.level_id for level in vocabulary.levels)
    if type(vocabulary) is NoulVocabulary:
        return 'noul', (False, True)
    return None, ()


def nominal_binding(criterion):
    bindings = thaw_value(criterion.checks[0].bindings)
    if 'nominal_answer_conversion' not in bindings and 'quality_admission' not in bindings:
        return None
    kind, values = _vocabulary(criterion)
    code = nominal_declaration_error(bindings, kind, values)
    if code:
        raise ApplicationError(code)
    return bindings['nominal_answer_conversion']


def nominal_requires_matching_evaluation(criterion):
    """Whether this exact method declaration opts into legacy evaluation gating."""
    bindings = thaw_value(criterion.checks[0].bindings)
    return 'quality_admission' in bindings


def _unknown(mapping, reason):
    return mapping, 'unknown', reason


def _mapped_status(criterion, mapping, *, answer_kind, answer_value,
                   selection_status, answer_complete, input_truncated):
    if mapping is None:
        return _unknown(mapping, 'NOMINAL_MAPPING_UNAVAILABLE')
    if type(answer_complete) is not bool or type(input_truncated) is not bool:
        return _unknown(mapping, 'NOMINAL_ANSWER_FORMAT_INVALID')
    if input_truncated:
        return _unknown(mapping, 'DECISION_INPUT_TRUNCATED')
    if not answer_complete:
        return _unknown(mapping, 'DECISION_ANSWER_INCOMPLETE')

    declared_kind = mapping.get('answer_kind')
    vocabulary_kind, _ = _vocabulary(criterion)
    if type(answer_kind) is not str or answer_kind != declared_kind or answer_kind != vocabulary_kind:
        return _unknown(mapping, 'NOMINAL_ANSWER_KIND_MISMATCH')

    version = mapping.get('contract_version')
    if answer_kind == 'choice':
        if selection_status == 'tie':
            return _unknown(mapping, 'DECISION_CHOICE_TIED')
        if selection_status == 'missing' or answer_value is None:
            return _unknown(mapping, 'DECISION_ANSWER_MISSING')
        if selection_status != 'unique' or type(answer_value) is not str:
            return _unknown(mapping, 'NOMINAL_ANSWER_FORMAT_INVALID')
        status_map = mapping.get('option_statuses')
        if type(status_map) is not dict or answer_value not in status_map:
            return _unknown(mapping, 'DECISION_ANSWER_UNMAPPED')
        return mapping, status_map[answer_value], 'NOMINAL_OPTION_MAPPED'

    if answer_kind == 'score':
        if selection_status is not None:
            return _unknown(mapping, 'NOMINAL_ANSWER_FORMAT_INVALID')
        # Accept only a source-proven discrete level index. An arbitrary native
        # numeric score/expected value is not a level selection; its producer
        # semantics must be established upstream. bool is not an integer index.
        if type(answer_value) is not int:
            return _unknown(mapping, 'NOMINAL_ANSWER_FORMAT_INVALID')
        vocabulary = criterion.answer_vocabulary
        levels = tuple(vocabulary.levels)
        selected = tuple(level for level in levels if type(level.index) is int and level.index == answer_value)
        if len(selected) != 1:
            return _unknown(mapping, 'DECISION_ANSWER_UNMAPPED')
        if version != 'ordessa.nominal-answer-status/2':
            return _unknown(mapping, 'NOMINAL_ANSWER_KIND_MISMATCH')
        status_map = mapping.get('level_statuses')
        if type(status_map) is not dict or selected[0].level_id not in status_map:
            return _unknown(mapping, 'DECISION_ANSWER_UNMAPPED')
        return mapping, status_map[selected[0].level_id], 'NOMINAL_LEVEL_MAPPED'

    if answer_kind == 'noul':
        if selection_status is not None:
            return _unknown(mapping, 'NOMINAL_ANSWER_FORMAT_INVALID')
        if type(answer_value) is not bool:
            return _unknown(mapping, 'NOMINAL_ANSWER_FORMAT_INVALID')
        if version != 'ordessa.nominal-answer-status/2':
            return _unknown(mapping, 'NOMINAL_ANSWER_KIND_MISMATCH')
        rows = mapping.get('boolean_statuses')
        if type(rows) is not list:
            return _unknown(mapping, 'DECISION_ANSWER_UNMAPPED')
        matches = tuple(row for row in rows if type(row) is dict
                        and type(row.get('value')) is bool and row['value'] is answer_value)
        if len(matches) != 1:
            return _unknown(mapping, 'DECISION_ANSWER_UNMAPPED')
        return mapping, matches[0]['status'], 'NOMINAL_BOOLEAN_MAPPED'

    return _unknown(mapping, 'NOMINAL_ANSWER_KIND_MISMATCH')


def nominal_decision_answer(plan, standard, check_key, *, answer_kind, answer_value,
        answer_complete, input_truncated, selection_status=None,
        evidence_refs=(), rationale=''):
    """Map a typed native answer only through the exact frozen method vocabulary.

    The source owner still verifies exact request/question/input/durable receipt,
    capability and current trust. Format/choice mismatches become method
    ``unknown``; wrong method version, source proof and evidence types refuse.
    This function neither invokes Decision nor selects a winner or threshold.
    """
    criterion = _criterion(plan, standard, check_key)
    if (type(evidence_refs) is not tuple
            or any(type(ref) is not ArtifactRevisionRef for ref in evidence_refs)
            or type(rationale) is not str):
        raise ApplicationError('REVIEW_SOURCE_INVALID')
    mapping = nominal_binding(criterion)
    _, status, reason = _mapped_status(criterion, mapping, answer_kind=answer_kind,
        answer_value=answer_value, selection_status=selection_status,
        answer_complete=answer_complete, input_truncated=input_truncated)
    disposition = getattr(criterion.policy, status)
    if nominal_requires_matching_evaluation(criterion):
        compatibility_disposition, compatibility_reason = 'manual', 'MODEL_EVALUATION_UNAVAILABLE'
    else:
        compatibility_disposition, compatibility_reason = disposition, reason
    answer = CriterionAnswer(check_key, status, evidence_refs, rationale or reason)
    return NominalCriterionResolution(answer, reason, compatibility_disposition, compatibility_reason)


def nominal_criterion_answer(plan, standard, check_key, *, selected_option,
        selection_status, answer_complete, input_truncated, evidence_refs=(), rationale=''):
    """Compatibility adapter for the original finite choice-answer API."""
    if (type(answer_complete) is not bool or type(input_truncated) is not bool
            or selection_status not in ('unique', 'tie', 'missing')
            or (selected_option is not None and type(selected_option) is not str)
            or (selection_status == 'unique' and type(selected_option) is not str)
            or (selection_status in ('tie', 'missing') and selected_option is not None)):
        raise ApplicationError('REVIEW_SOURCE_INVALID')
    return nominal_decision_answer(plan, standard, check_key, answer_kind='choice',
        answer_value=selected_option, selection_status=selection_status,
        answer_complete=answer_complete, input_truncated=input_truncated,
        evidence_refs=evidence_refs, rationale=rationale)
