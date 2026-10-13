"""Explicit success/failure and stable error retention at the domain boundary."""
from dataclasses import FrozenInstanceError

import pytest

from ordessa_engineering.domain.changes.errors import (DomainError)
from ordessa_engineering.domain.changes.errors import (DomainErrorCode)
from ordessa_engineering.domain.artifacts.refs import (ArtifactRevisionRef)
from ordessa_engineering.domain.changes.result import (Result)
from ordessa_engineering.domain.common.models.values import (Digest)


@pytest.mark.parametrize("value", [None, False, 0, (), "value"])
def test_success_preserves_values_including_none(value):
    result = Result.success(value)
    assert result.ok
    assert result.value is value
    assert result.error is None


def test_failure_preserves_complete_original_error_and_is_frozen():
    ref = ArtifactRevisionRef("realm", "project", "artifact", "revision", Digest("sha256", "a" * 64))
    violation = DomainError(DomainErrorCode.PROPOSAL_UNAVAILABLE, (ref,))
    error = DomainError(DomainErrorCode.INVALID_CHANGE_SET, (ref,),
                        (("expected_count", 2), ("actual_count", 1)), (violation,))
    result = Result.failure(error)
    assert not result.ok
    assert result.value is None
    assert result.error is error
    assert result.error.subject_refs == (ref,)
    assert result.error.details == (("actual_count", 1), ("expected_count", 2))
    assert result.error.violations == (violation,)
    with pytest.raises(FrozenInstanceError):
        result.error = None


@pytest.mark.parametrize("error", [None, "INVALID_SCHEMA", ValueError("synthetic")])
def test_failure_refuses_unstructured_errors_including_missing_error(error):
    with pytest.raises(TypeError, match="requires DomainError"):
        Result.failure(error)


def test_result_refuses_ambiguous_construction_and_truthiness():
    error = DomainError(DomainErrorCode.INVALID_SCHEMA)
    with pytest.raises(ValueError, match="both value and error"):
        Result(value="value", error=error)
    with pytest.raises(TypeError, match="requires DomainError"):
        Result(error=ValueError("synthetic"))
    for result in (Result.success(None), Result.failure(error)):
        with pytest.raises(TypeError, match="explicitly"):
            bool(result)
