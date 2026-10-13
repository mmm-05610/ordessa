"""Real owner imports/type references, retired paths, and diagnostic separation."""
import importlib
import subprocess
import sys

import pytest

from ordessa_engineering.domain.changes.errors import (DomainErrorCode)
from ordessa_engineering.domain.common.outcomes.diagnostics import (ReferenceError)
from ordessa_engineering.domain.changes.errors import (from_reference_error)


OWNERS = (
    'common.models.values', 'common.models.identity', 'common.models.refs',
    'common.models.selection', 'common.outcomes.diagnostics',
    'common.mechanisms.codec', 'common.mechanisms.hashing', 'common.mechanisms.selection',
    'artifacts.refs', 'artifacts.method_binding', 'artifacts.provenance',
    'artifacts.ref_codec', 'artifacts.method_codec', 'artifacts.provenance_codec',
    'changes.refs', 'changes.baselines', 'changes.errors', 'changes.result',
    'changes.ref_codec', 'changes.baseline_codec',
    'reviews.refs', 'reviews.targets', 'reviews.identity', 'reviews.evidence',
    'reviews.ref_codec', 'reviews.target_codec', 'approvals.refs', 'approvals.ref_codec',
)
PREFIX = 'ordessa_engineering.domain.common.'


@pytest.mark.parametrize('first', ('common.models.refs', 'changes.errors', 'reviews.targets', 'artifacts.provenance_codec'))
def test_real_fresh_import_orders_and_runtime_type_annotations(first):
    code = '''import importlib, inspect, typing
owners = %r
prefix = %r
importlib.import_module(prefix + %r)
for owner in owners:
    module = importlib.import_module(prefix + owner)
    for value in vars(module).values():
        if (inspect.isclass(value) or inspect.isfunction(value)) and value.__module__ == module.__name__:
            typing.get_type_hints(value)
print("ALL_OWNER_IMPORTS_AND_TYPE_HINTS_RESOLVED")
''' % (OWNERS, 'ordessa_engineering.domain.', first)
    result = subprocess.run([sys.executable, '-B', '-c', code], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'ALL_OWNER_IMPORTS_AND_TYPE_HINTS_RESOLVED'


@pytest.mark.parametrize('leaf', ('values', 'refs', 'provenance', 'trust', 'mutation', 'errors', 'result', 'codec', 'hashing'))
def test_flat_runtime_module_is_retired_without_alias(leaf):
    with pytest.raises(ModuleNotFoundError) as caught:
        importlib.import_module(PREFIX + leaf)
    assert caught.value.name == PREFIX + leaf


@pytest.mark.parametrize('leaf', ('models.provenance', 'models.trust', 'models.mutation',
                                 'outcomes.errors', 'outcomes.result'))
def test_business_common_module_is_retired_without_forwarder(leaf):
    with pytest.raises(ModuleNotFoundError) as caught:
        importlib.import_module(PREFIX + leaf)
    assert caught.value.name == PREFIX + leaf


def test_common_owners_have_no_business_reexports_or_error_catalog():
    values = importlib.import_module(PREFIX + 'models.values')
    refs = importlib.import_module(PREFIX + 'models.refs')
    identity = importlib.import_module(PREFIX + 'models.identity')
    diagnostics = importlib.import_module(PREFIX + 'outcomes.diagnostics')
    for name in ('ArtifactId', 'RevisionId', 'ChangeId', 'ProposalId', 'ReviewId',
                 'ApprovalId', 'SubmissionId', 'RepositoryId', 'MethodId'):
        assert not hasattr(values, name)
    for name in ('ArtifactRevisionRef', 'ProposalRef', 'ReviewRef', 'ApprovalRef',
                 'SubmissionRef', 'RepositorySnapshotRef', 'MethodRef', 'Target', 'TargetSet', 'SubjectRef'):
        assert not hasattr(refs, name)
    assert not hasattr(identity, 'RecordIdentity')
    assert not hasattr(diagnostics, 'DomainErrorCode')
    assert not hasattr(diagnostics, 'DomainError')


def test_minimal_diagnostic_preserves_exception_surface_and_never_constructs_full_error():
    failure = ReferenceError('PROPOSAL_UNAVAILABLE')
    assert failure.code == 'PROPOSAL_UNAVAILABLE'
    assert str(failure) == 'PROPOSAL_UNAVAILABLE'
    assert failure.args == ('PROPOSAL_UNAVAILABLE',)
    assert not hasattr(failure, 'error')
    assert 'DomainError' not in ReferenceError.__init__.__globals__
    converted = from_reference_error(failure)
    assert converted.code is DomainErrorCode.PROPOSAL_UNAVAILABLE
    assert converted.subject_refs == converted.details == converted.violations == ()
