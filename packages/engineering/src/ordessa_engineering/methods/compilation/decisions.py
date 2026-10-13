"""Neutral selection and finite question expansion, with no host execution."""
from ..definitions.models.compiled import DecisionSpec, TargetSelector
from ..definitions.errors import MethodError, MethodFailure


def compile_selector(document_types: list[str]) -> TargetSelector:
    return TargetSelector(tuple(document_types))


def select_targets(selector: TargetSelector, candidates: tuple[tuple[str, str], ...], *, limit: int = 512) -> tuple[str, ...]:
    """Candidates are (target ID, document type) already supplied by application."""
    if type(limit) is not int or not 1 <= limit <= 512:
        raise MethodFailure(MethodError("SELECTOR_LIMIT_INVALID", "selector limit must be between 1 and 512"))
    if (type(candidates) is not tuple or len(candidates) > limit
            or any(type(item) is not tuple or len(item) != 2
                   or any(type(part) is not str or not part for part in item) for item in candidates)
            or len({identity for identity, _ in candidates}) != len(candidates)):
        raise MethodFailure(MethodError("SELECTOR_TARGET_SET_INVALID", "target set exceeds its limit or contains duplicate identities"))
    return tuple(identity for identity, kind in candidates
                 if not selector.document_types or kind in selector.document_types)


def expand_questions(spec: DecisionSpec, instance_ids: tuple[str, ...], *, limit: int = 512) -> tuple[tuple[str, str], ...]:
    """Return (instance ID, question ID); caller owns evidence/host bindings."""
    if type(limit) is not int or not 1 <= limit <= 512:
        raise MethodFailure(MethodError("QUESTION_EXPANSION_LIMIT_INVALID", "question expansion limit must be between 1 and 512"))
    if spec.iteration == "once":
        if instance_ids != ("once",):
            raise MethodFailure(MethodError("QUESTION_INSTANCE_INVALID", "single evaluation requires one explicit instance"))
    elif spec.iteration != "each_evidence_required_claim":
        raise MethodFailure(MethodError("QUESTION_ITERATION_UNSUPPORTED", "question iteration is unsupported"))
    if (not instance_ids or any(not isinstance(item, str) or not item for item in instance_ids)
            or len(set(instance_ids)) != len(instance_ids)):
        raise MethodFailure(MethodError("QUESTION_INSTANCE_INVALID", "question instances must be nonempty unique identities"))
    if len(instance_ids) * len(spec.questions) > limit:
        raise MethodFailure(MethodError("QUESTION_EXPANSION_LIMIT", "question expansion exceeds its limit"))
    return tuple((instance, question.question_id) for instance in instance_ids for question in spec.questions)


from ..definitions.models.compiled import DecisionPolicy

def compile_decision_policy(value: dict, kind: str) -> DecisionPolicy:
    keys = ("minimum_selected_probability", "minimum_top_level_probability", "maximum_p_true", "minimum_expected_index")
    return DecisionPolicy(kind, value["calibration_profile_id"], value["activation"],
        tuple((key, value[key]) for key in keys if key in value), value.get("selected_option"),
        tuple(sorted(value.get("option_statuses", {}).items())), value.get("below_threshold"),
        value.get("above_threshold"), value["missing_evaluation"], value["truncation"])


from ..definitions.models import LoadedMethod

def _decision_order(loaded: LoadedMethod) -> list[str]:
    ids = [key for key, item in loaded.resources.items() if item.declaration.get("kind") == "question_set"]
    # Question-set ordering is semantic and stable: the input contract defines
    # the consumer-facing grouping; ID breaks ties. It does not depend on a host
    # registry's unrelated catalog ordering.
    return sorted(ids, key=lambda key: (
        str((loaded.resources[key].value or {}).get("input_contract", "")), key
    ))


