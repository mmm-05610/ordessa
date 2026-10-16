"""The declared-Work dispatch identity contract."""
import pytest

from ordessa_engineering.application.contracts.dispatch_identity import (
    SUBJECT_KINDS, identity_agrees, is_folded_work_key, is_work_key,
    split_work_dispatch_key, subject_of, work_dispatch_key)
from ordessa_engineering.application.contracts.errors import ApplicationError


def test_key_is_namespaced_versioned_and_keeps_attempt_separate():
    key = work_dispatch_key('work-1', 'incremental.review-change', 'compare')
    assert key == 'w1:work-1:incremental.review-change:compare'
    assert is_work_key(key)
    assert split_work_dispatch_key(key) == (
        'work-1', 'incremental.review-change', 'compare')
    # attempt is not part of the key: it stays its own column, as before.
    assert 'w1:work-1:incremental.review-change:compare' == work_dispatch_key(
        'work-1', 'incremental.review-change', 'compare')


def test_same_step_name_in_a_different_action_never_collides():
    review = work_dispatch_key('work-1', 'incremental.review-change', 'record')
    packages = work_dispatch_key('work-1', 'incremental.prepare-packages', 'record')
    assert review != packages
    # and neither can be mistaken for a historical run id
    assert not is_work_key('run-1')


def test_two_works_with_the_same_action_and_step_never_collide():
    assert work_dispatch_key('work-1', 'a', 's') != work_dispatch_key('work-2', 'a', 's')


@pytest.mark.parametrize('args', [('', 'a', 's'), ('w', '', 's'), ('w', 'a', '')])
def test_empty_identity_parts_are_refused(args):
    with pytest.raises(ApplicationError) as exc:
        work_dispatch_key(*args)
    assert exc.value.code == 'WORK_DISPATCH_IDENTITY_INVALID'


def test_legal_ids_containing_the_separator_still_round_trip():
    key = work_dispatch_key('work:1', 'a:b', 's:1')
    assert split_work_dispatch_key(key) == ('work:1', 'a:b', 's:1')
    assert is_work_key(key) and not is_folded_work_key(key)
    # Escaping is reversible, so distinct ids never share a key.
    assert key != work_dispatch_key('work', '1:a:b', 's:1')


def test_very_long_legal_ids_get_a_namespaced_folded_key():
    key = work_dispatch_key('w' * 400, 'a' * 100, 's' * 100)
    assert is_work_key(key) and is_folded_work_key(key)
    assert len(key) <= 512
    with pytest.raises(ApplicationError):
        split_work_dispatch_key(key)


def test_split_refuses_non_work_keys():
    with pytest.raises(ApplicationError):
        split_work_dispatch_key('run-1')
    with pytest.raises(ApplicationError):
        split_work_dispatch_key('w2:work-1:a:s')


def test_stored_fields_must_agree_with_their_key():
    key = work_dispatch_key('work-1', 'a', 's')
    assert identity_agrees(key, 'work-1', 'a', 's')
    assert not identity_agrees(key, 'work-2', 'a', 's')
    assert not identity_agrees('run-1', 'work-1', 'a', 's')


def test_generation_subject_is_a_reviewed_change_never_a_package_name():
    subject = subject_of('reviewed_change', {'review_id': 'r-1'})
    assert subject == {'subject_kind': 'reviewed_change',
                       'subject_ref': {'review_id': 'r-1'}}
    assert SUBJECT_KINDS == ('reviewed_change', 'frozen_package')
    with pytest.raises(ApplicationError):
        subject_of('package', {'package_id': 'p-1'})
    with pytest.raises(ApplicationError):
        subject_of('frozen_package', {})
