"""Compile validated external policies into neutral immutable values."""
from ..definitions.models.compiled import DecisionPolicy, DispositionPolicy, ReductionPolicy


def compile_disposition(value: dict) -> DispositionPolicy:
    return DispositionPolicy(**value)


def compile_reduction(value: dict) -> ReductionPolicy:
    return ReductionPolicy(value["required_criteria"], value["empty_applicable_set"], tuple(value["priority"]))


