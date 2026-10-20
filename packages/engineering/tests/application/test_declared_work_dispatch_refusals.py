"""Declared-Work dispatch refuses by the real missing item, in a fixed order."""
import pytest

from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.orchestration.steps.implementation_dispatch import (
    ImplementationDispatch)
from test_real_source_chain import context


class _Access:
    def __init__(self):
        self.calls = []

    def require(self, context, operation):
        self.calls.append(operation)


class _Selection:
    """Mirrors the run line's requirement: a callable selection guard."""

    def guard_selection(self, *args, **kwargs):
        return None


def dispatch(**overrides):
    value = ImplementationDispatch.__new__(ImplementationDispatch)
    value.access = _Access()
    value.execution = None
    value.blobs = None
    value.selection = _Selection()
    value.factory = None
    for name, item in overrides.items():
        setattr(value, name, item)
    return value


def call(value, actions=('edit_repository',), attempt=1):
    return value.dispatch_declared_work(
        'w1:work-1:incremental.prepare-packages:draft', 'work-1',
        'incremental.prepare-packages', 'draft', attempt,
        {'environmentNamespace': 'env', 'unitId': 'unit', 'ownerProviderRef': {},
         'sourceRevision': 'rev'}, {}, tuple(actions),
        context('declared-work-dispatch-probe'))


def test_missing_execution_authority_is_reported_first():
    with pytest.raises(ApplicationError) as exc:
        call(dispatch())
    assert exc.value.code == 'DISPATCH_EXECUTION_AUTHORITY_UNAVAILABLE'


def test_missing_selection_authority_is_reported_next():
    value = dispatch(execution=object(), blobs=object())
    value.selection = None
    with pytest.raises(ApplicationError) as exc:
        call(value)
    assert exc.value.code == 'DISPATCH_SELECTION_AUTHORITY_UNAVAILABLE'


def test_invalid_argument_before_any_subject_lookup():
    value = dispatch(execution=object(), blobs=object())
    with pytest.raises(ApplicationError) as exc:
        call(value, actions=('edit_repository', 'edit_repository'))
    assert exc.value.code == 'INVALID_ARGUMENT'
    with pytest.raises(ApplicationError) as exc:
        call(value, attempt=0)
    assert exc.value.code == 'INVALID_ARGUMENT'


def test_generation_is_refused_by_the_platform_rule():
    # The same rule the implementation line enforces: generate_package,
    # apply_change and accept_artifact are not dispatched as implementation work.
    value = dispatch(execution=object(), blobs=object())
    for action in ('generate_package', 'apply_change', 'accept_artifact'):
        with pytest.raises(ApplicationError) as exc:
            call(value, actions=(action,))
        assert exc.value.code == 'ACTION_NOT_AUTHORIZED'
