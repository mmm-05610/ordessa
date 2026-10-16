"""Finite method-authored answer mappings, independent of evaluation policy."""

_CHOICE_V1_FIELDS = frozenset({'contract_version','answer_kind','option_statuses',
    'tie','missing_answer','incomplete_answer','truncated_input','unmapped_option'})
_V2_COMMON_FIELDS = frozenset({'contract_version','answer_kind','tie','missing_answer',
    'incomplete_answer','truncated_input','unmapped_answer'})
_QUALITY = {'contract_version':'ordessa.review-quality-admission/1',
    'activation':'matching_validated_evaluation_required',
    'missing_evaluation':'manual','unresolved_model':'manual'}
_STATUSES = frozenset({'satisfied','violated','insufficient','unknown'})


def _valid_status_map(value, expected):
    return (type(expected) is tuple and all(type(item) is str for item in expected)
            and len(set(expected)) == len(expected)
            and type(value) is dict and set(value) == set(expected)
            and all(type(status) is str and status in _STATUSES for status in value.values()))


def nominal_declaration_error(bindings, vocabulary_kind=None, vocabulary_values=()):
    """Return a structural refusal for a method's finite answer mapping.

    The v1 choice declaration remains byte-compatible. Version 2 has strict
    kind-specific maps: option IDs, level IDs, or typed Boolean entries. This
    validates only declaration shape and vocabulary coverage; it never
    authenticates an answer, performs scoring, or attests model quality.
    """
    if type(bindings) is not dict:
        return 'NOMINAL_CONVERSION_INVALID'
    has_v1_or_v2 = 'nominal_answer_conversion' in bindings
    has_quality = 'quality_admission' in bindings
    if not has_v1_or_v2 and not has_quality:
        return None
    nominal = bindings.get('nominal_answer_conversion')
    if type(nominal) is not dict:
        return 'NOMINAL_CONVERSION_INVALID'

    version = nominal.get('contract_version')
    kind = nominal.get('answer_kind')
    if type(kind) is not str or kind != vocabulary_kind:
        return 'NOMINAL_ANSWER_KIND_MISMATCH'

    if version == 'ordessa.nominal-choice-status/1':
        if kind != 'choice' or set(nominal) != _CHOICE_V1_FIELDS:
            return 'NOMINAL_CONVERSION_INVALID'
        if any(nominal[k] != 'unknown' for k in _CHOICE_V1_FIELDS
                - {'contract_version','answer_kind','option_statuses'}):
            return 'NOMINAL_CONVERSION_INVALID'
        if not _valid_status_map(nominal['option_statuses'], vocabulary_values):
            return 'NOMINAL_OPTION_MAP_INVALID'
    elif version == 'ordessa.nominal-answer-status/2':
        if any(nominal.get(field) != 'unknown' for field in
                ('tie','missing_answer','incomplete_answer','truncated_input','unmapped_answer')):
            return 'NOMINAL_CONVERSION_INVALID'
        expected_fields = {
            'choice': _V2_COMMON_FIELDS | {'option_statuses'},
            'score': _V2_COMMON_FIELDS | {'level_statuses'},
            'noul': _V2_COMMON_FIELDS | {'boolean_statuses'},
        }.get(kind)
        if expected_fields is None or set(nominal) != expected_fields:
            return 'NOMINAL_CONVERSION_INVALID'
        if kind in ('choice','score'):
            field = 'option_statuses' if kind == 'choice' else 'level_statuses'
            if not _valid_status_map(nominal[field], vocabulary_values):
                return 'NOMINAL_OPTION_MAP_INVALID' if kind == 'choice' else 'NOMINAL_LEVEL_MAP_INVALID'
        else:
            rows = nominal['boolean_statuses']
            if (type(rows) is not list or len(rows) != 2
                    or any(type(row) is not dict or set(row) != {'value','status'} for row in rows)
                    or {row.get('value') for row in rows if type(row.get('value')) is bool} != {True, False}
                    or any(type(row.get('value')) is not bool for row in rows)
                    or any(type(row.get('status')) is not str or row['status'] not in _STATUSES for row in rows)):
                return 'NOMINAL_BOOLEAN_MAP_INVALID'
    else:
        return 'NOMINAL_CONVERSION_INVALID'

    # An explicitly declared legacy requirement remains method-specific and
    # must be complete. Omission is allowed; explicit null is malformed.
    if has_quality and bindings['quality_admission'] != _QUALITY:
        return 'NOMINAL_QUALITY_ADMISSION_REQUIRED'
    return None
