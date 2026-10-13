"""Safety semantics of finite standards; declaration shapes live in definitions."""
from __future__ import annotations

from decimal import Decimal

from ..definitions.errors import Diagnostic
from ..definitions.models import LoadedMethod
from .nominal import nominal_declaration_error


def validate_policies(loaded: LoadedMethod) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for resource_id, resource in loaded.resources.items():
        if resource.declaration.get("kind") != "standard":
            continue
        path = resource.captured.logical_path

        def error(code: str, message: str, pointer: str) -> None:
            diagnostics.append(Diagnostic(code, "error", message, resource_id, path, pointer))

        for index, criterion in enumerate(resource.value["criteria"]):
            pointer = f"/criteria/{index}"
            if criterion["policy"]["unknown"] == "pass":
                error("UNKNOWN_CANNOT_PASS", "unknown check results cannot pass", f"{pointer}/policy/unknown")
            vocabulary = criterion.get("answer_vocabulary")
            nominal = False
            for check_index, check in enumerate(criterion['checks']):
                bindings = check['bindings']
                if 'nominal_answer_conversion' in bindings or 'quality_admission' in bindings:
                    nominal = True
                    kind = vocabulary.get('kind') if type(vocabulary) is dict else None
                    if kind == 'choice' and type(vocabulary.get('options')) is list:
                        values = tuple(item.get('option_id') for item in vocabulary['options']
                                       if type(item) is dict)
                    elif kind == 'score' and type(vocabulary.get('levels')) is list:
                        values = tuple(item.get('level_id') for item in vocabulary['levels']
                                       if type(item) is dict)
                    elif kind == 'noul':
                        values = (False, True)
                    else:
                        values = ()
                    code = nominal_declaration_error(bindings, kind, values)
                    if code:
                        error(code, 'nominal conversion requires a complete finite vocabulary map and explicit unknown handling',
                            f'{pointer}/checks/{check_index}/bindings')
            if nominal and (len(criterion['checks']) != 1 or criterion.get('decision_policy') is not None):
                error('NOMINAL_PROBABILITY_POLICY_CONFLICT', 'nominal conversion cannot replace or mix with probability policy', pointer)
            if vocabulary:
                kind = vocabulary["kind"]
                if kind == "choice":
                    ids = [item["option_id"] for item in vocabulary["options"]]
                    if len(ids) != len(set(ids)):
                        error("ANSWER_VOCABULARY_INVALID", "choice options require unique IDs", f"{pointer}/answer_vocabulary/options")
                elif kind == "score":
                    indexes = [item["index"] for item in vocabulary["levels"]]
                    ids = [item["level_id"] for item in vocabulary["levels"]]
                    if sorted(indexes) != list(range(len(indexes))) or len(ids) != len(set(ids)):
                        error("ANSWER_VOCABULARY_INVALID", "score levels require unique IDs and contiguous indices", f"{pointer}/answer_vocabulary/levels")
            policy = criterion.get("decision_policy")
            if policy is None:
                continue
            pp = f"{pointer}/decision_policy"
            if not vocabulary:
                error("DECISION_VOCABULARY_REQUIRED", "decision policy requires a finite answer vocabulary", pp)
                continue
            kind = vocabulary["kind"]
            thresholds = {key for key in policy if key.startswith("minimum_") or key == "maximum_p_true"}
            allowed = {"choice": {"minimum_selected_probability"}, "score": {"minimum_expected_index", "minimum_top_level_probability"}, "noul": {"maximum_p_true"}}[kind]
            if not thresholds or not thresholds.issubset(allowed):
                error("DECISION_POLICY_THRESHOLD_INVALID", "thresholds must match the answer vocabulary", pp)
            irrelevant = {"choice": {"above_threshold"}, "score": {"selected_option", "option_statuses", "above_threshold"}, "noul": {"selected_option", "option_statuses", "below_threshold"}}[kind]
            if irrelevant.intersection(policy):
                error("DECISION_POLICY_KIND_MISMATCH", "decision policy contains fields for another answer kind", pp)
            for key in thresholds:
                number = Decimal(policy[key])
                maximum = Decimal(len(vocabulary["levels"]) - 1) if key == "minimum_expected_index" and kind == "score" else Decimal(1)
                if number < 0 or number > maximum:
                    error("THRESHOLD_OUT_OF_RANGE", "threshold exceeds its finite answer range", f"{pp}/{key}")
            if policy["missing_evaluation"] == "pass":
                error("MISSING_EVALUATION_CANNOT_PASS", "missing evaluation cannot pass", f"{pp}/missing_evaluation")
            for key in ("above_threshold", "below_threshold"):
                if policy.get(key) == "pass":
                    error("UNSATISFIED_THRESHOLD_CANNOT_PASS", "failed threshold cannot pass", f"{pp}/{key}")
            if kind == "choice":
                option_ids = {item["option_id"] for item in vocabulary["options"]}
                statuses = policy.get("option_statuses", {})
                selected = policy.get("selected_option")
                if (selected not in option_ids or set(statuses) != option_ids
                        or statuses.get(selected) != "threshold_dependent"
                        or any(status == "threshold_dependent" for option, status in statuses.items() if option != selected)):
                    error("DECISION_OPTION_POLICY_INVALID", "choice policy must cover every option and bind the threshold to the selected option", pp)
                if "below_threshold" not in policy:
                    error("DECISION_THRESHOLD_DISPOSITION_MISSING", "choice policy must declare below-threshold disposition", pp)
            elif kind == "score":
                if "below_threshold" not in policy:
                    error("DECISION_THRESHOLD_DISPOSITION_MISSING", "score policy must declare below-threshold disposition", pp)
            elif "above_threshold" not in policy:
                error("DECISION_THRESHOLD_DISPOSITION_MISSING", "noul policy must declare above-threshold disposition", pp)
    return diagnostics
