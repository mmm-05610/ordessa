"""Explicit document allocation is independent of step/model budgets."""
from dataclasses import replace
import pytest
from decision_runtime import DecisionError
from decision_runtime.definitions.values import job_document_bound, MAX_JOB_DOCUMENT_BYTES
from decision_runtime.settings import DecisionsSettings
from test_capability import settings


def test_document_default_and_absolute_bound_are_unchanged_and_finite(tmp_path):
    original = settings(tmp_path)
    assert original.job_document_max_bytes is None
    assert job_document_bound() == 512 * 1024
    assert job_document_bound(MAX_JOB_DOCUMENT_BYTES) == 8 * 512 * 1024 + 65536
    for value in (True, 0, -1, 1.5, MAX_JOB_DOCUMENT_BYTES + 1):
        with pytest.raises(DecisionError, match='invalid_job_document_limit'):
            replace(original, job_document_max_bytes=value)
