"""Current independent Profile owner; controlled external admission only.

No Unit, Decision flow, native process or human authorization is assembled.
The inherited native-flow tests retain their original assertions separately.
"""
from contextlib import contextmanager
from threading import RLock

import pytest

from ordessa_engineering.adapters.execution_profiles import NativeProfileSelectionSource
from ordessa_engineering.domain.common.outcomes.library_failures import EngineeringError
from ordessa_agents.profiles import (
    ProfileAccessRefused, ProfileNotFound, ProfileRevisionConflict,
    ProfileRevisionRef, ProfileService, SqliteProfileStore,
)
from ordessa_infrastructure.security.fingerprints import HmacKeyRing


class _Policy:
    def __init__(self):
        self.denied = set()

    def admit_object_access(self, principal, target, mode):
        return not any(target.endswith(':' + profile) for profile in self.denied)

    def admit_invoke(self, *_args):
        return True


class _Fingerprint:
    def __init__(self):
        self.ring = HmacKeyRing({'fixture': b'engineering-profile-fixture'}, active_key_id='fixture')

    def describe(self):
        return self.ring.describe(comparison_scope='engineering-profile:test')

    def fingerprint(self, request, surface, digest):
        import json
        raw = json.dumps([request.environment_namespace, request.principal_scope,
                          request.request_id, surface, digest], separators=(',', ':'))
        return self.ring.sign(raw.encode())


class _Admission:
    namespace = 'engineering-profile-current-owner'
    principal_scope = 'controlled-external-principal'

    def __init__(self, policy):
        self.policy = policy
        self.admission_lock = RLock()
        self.fingerprint_port = _Fingerprint()

    def check_open(self):
        pass

    def check_namespace(self, namespace):
        if namespace != self.namespace:
            raise ValueError('foreign namespace')


class _Validator:
    def validate_profile(self, content):
        # Controlled harness validation; no claim of actual provider support.
        return None


@contextmanager
def _owner(tmp_path):
    store = SqliteProfileStore(tmp_path / 'profiles.sqlite')
    policy = _Policy()
    try:
        yield ProfileService(store, _Admission(policy), _Validator()), policy
    finally:
        store.close()


def _content(label):
    return {'schemaVersion': '1', 'harnessDefinitionRef': {
        'environmentNamespace': _Admission.namespace, 'definitionId': 'controlled'},
        'declarations': [], 'metadata': {'fixture_label': label}}


def _create(profiles, name, label):
    return profiles.create(profile_id=name, name=name, content=_content(label),
                           request=profiles.request_key('create-' + name))


def test_source_preserves_exact_revision_complete_set_and_current_archive(tmp_path):
    with _owner(tmp_path) as (profiles, _):
        first = _create(profiles, 'profile-a', 'first')
        profiles.revise('profile-a', content=_content('second'), expected_version=1,
                        base_revision=first.current_revision, request=profiles.request_key('revise-a'))
        source = NativeProfileSelectionSource(profiles, allowed_revisions=(first.current_revision,))
        option_id, (selected, description) = next(iter(source.candidates(max_candidates=1).items()))
        assert selected is first.current_revision
        assert option_id.startswith('profile-a@1:')
        assert '"fixture_label":"first"' in description
        assert source.validate(selected) is selected
        with pytest.raises(EngineeringError, match='not_method_allowed'):
            source.validate(profiles.get('profile-a').current_revision)
        second = _create(profiles, 'profile-b', 'third')
        complete = NativeProfileSelectionSource(profiles,
            allowed_revisions=(first.current_revision, second.current_revision))
        with pytest.raises(EngineeringError, match='over_limit'):
            complete.candidates(max_candidates=1)
        profiles.archive('profile-b', expected_version=1, request=profiles.request_key('archive-b'))
        with pytest.raises(EngineeringError, match='candidate_set_unavailable'):
            complete.candidates(max_candidates=2)


def test_source_rechecks_current_acl_digest_and_management_identity(tmp_path):
    with _owner(tmp_path) as (profiles, policy):
        exact = _create(profiles, 'profile-acl', 'acl').current_revision
        source = NativeProfileSelectionSource(profiles, allowed_revisions=(exact,))
        policy.denied.add('profile-acl')
        with pytest.raises(ProfileAccessRefused):
            source.candidates(max_candidates=1)
        policy.denied.clear()
        bad = ProfileRevisionRef(exact.environment_namespace, exact.profile_id, exact.revision,
                                 'sha256:' + 'f' * 64)
        with pytest.raises(ProfileRevisionConflict):
            NativeProfileSelectionSource(profiles, allowed_revisions=(bad,)).candidates(max_candidates=1)
        foreign = ProfileRevisionRef('foreign', exact.profile_id, exact.revision, exact.digest)
        with pytest.raises(EngineeringError, match='environment_mismatch'):
            NativeProfileSelectionSource(profiles, allowed_revisions=(foreign,))
        snapshot = ProfileRevisionRef(exact.environment_namespace, 'snap-' + '1' * 48,
                                      1, 'sha256:' + '1' * 64)
        with pytest.raises(ProfileNotFound):
            NativeProfileSelectionSource(profiles, allowed_revisions=(snapshot,)).candidates(max_candidates=1)


def test_source_rejects_ambiguous_empty_oversized_and_foreign_refs(tmp_path):
    with _owner(tmp_path) as (profiles, _):
        exact = _create(profiles, 'profile-a', 'first').current_revision
        for refs, error in [((), 'unavailable'), ((exact, exact), 'ambiguous'),
                            ((object(),), 'unavailable'), ((exact,) * 65, 'over_limit')]:
            with pytest.raises(EngineeringError, match=error):
                NativeProfileSelectionSource(profiles, allowed_revisions=refs)
        source = NativeProfileSelectionSource(profiles, allowed_revisions=(exact,))
        for limit in (False, 0, 65):
            with pytest.raises(EngineeringError, match='limit_invalid'):
                source.candidates(max_candidates=limit)
        profiles.revise('profile-a', content=_content('x' * (16 * 1024)), expected_version=1,
                        base_revision=exact, request=profiles.request_key('oversized'))
        oversized = profiles.get('profile-a').current_revision
        with pytest.raises(EngineeringError, match='description_too_large'):
            NativeProfileSelectionSource(profiles, allowed_revisions=(oversized,)).candidates(max_candidates=1)
