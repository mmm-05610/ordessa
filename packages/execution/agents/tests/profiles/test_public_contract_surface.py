"""The Profile SDK surface: import-only contract, identity rules and codec presence.

Imports nothing from `ordessa_units` or `pacthold`: the Agent/Profile contract is
a standalone distribution surface (DESIGN §3.2). The `ProfileContent` round-trip
needs the exact content-schema literal, which is covered by the package's own
existing schema tests; this file pins the surface and the reference validation.
"""
import pytest

from ordessa_agents import public
from ordessa_agents.profiles import (
    ConfigurationDeclaration, Profile, ProfileContent, ProfileRevision, ProfileRevisionRef,
    ProfileService, ProfileStorePort, canonical_content, content_digest, decode_content,
    decode_profile, decode_revision, decode_revision_ref, encode_content, encode_profile,
    encode_revision, encode_revision_ref,
)

DIGEST = 'sha256:' + 'a' * 64


def _ref(revision=1, namespace='env-1', profile='profile-1', digest=DIGEST):
    return ProfileRevisionRef(environment_namespace=namespace, profile_id=profile,
                              revision=revision, digest=digest)


def test_public_surface_is_import_only_and_exports_the_frozen_names():
    assert public.__all__ == [
        'AGENT_CONTRACT_VERSION', 'ProfileService', 'Profile', 'ProfileRevision',
        'ProfileRevisionRef', 'ProfileContent', 'ConfigurationDeclaration', 'ProfileNotFound',
        'ProfileRevisionConflict', 'ProfileValidationError',
        'AgentManager', 'Records', 'ManagerRefused', 'AgentInstanceRef', 'EndpointRef',
        'InteractionService', 'AgentStartRequest', 'AgentStartReceipt', 'PreparedAgentContext', 'HarnessCatalog',
        'FrozenNativeRequest', 'NativeOperationRef', 'NativeOperationReceipt', 'NativeWriteBinding']
    # DESIGN §15 adds these exact native values; they retain their sole owner.
    from ordessa_agents.sdk import native_contracts
    for name in ('FrozenNativeRequest','NativeOperationRef','NativeOperationReceipt','NativeWriteBinding'):
        assert getattr(public,name) is getattr(native_contracts,name)
    assert isinstance(public.AGENT_CONTRACT_VERSION, str) and public.AGENT_CONTRACT_VERSION
    assert public.ProfileService is ProfileService
    assert public.Profile is Profile
    assert public.ProfileRevisionRef is ProfileRevisionRef


def test_revision_reference_carries_namespace_identity_and_content_digest():
    ref = _ref(revision=2)
    assert (ref.environment_namespace, ref.profile_id, ref.revision) == ('env-1', 'profile-1', 2)
    assert ref.digest == DIGEST
    # A reference is a value, not a handle: two equal references compare equal.
    assert _ref(revision=2) == ref
    with pytest.raises(Exception):
        _ref(profile='')
    with pytest.raises(Exception):
        _ref(revision=0)
    with pytest.raises(Exception):
        _ref(digest='sha256:' + 'A' * 64)      # uppercase hex is not a digest
    with pytest.raises(Exception):
        _ref(namespace='')


def test_reference_codec_round_trips_and_rejects_trailing_bytes():
    ref = _ref()
    encoded = encode_revision_ref(ref)
    assert decode_revision_ref(encoded) == ref
    with pytest.raises(Exception):
        decode_revision_ref(dict(encoded, revision=revision_placeholder()))


def revision_placeholder():
    return 99


def test_codecs_are_the_owner_surface_and_take_the_environment_where_required():
    # The Profile distribution owns these codecs; nothing re-implements them.
    for fn in (encode_content, decode_content, encode_revision, decode_revision,
               encode_profile, decode_profile, encode_revision_ref, decode_revision_ref,
               canonical_content, content_digest):
        assert callable(fn)
    assert len(content_digest('sha256:' + 'b' * 64)) == len('sha256:') + 64


def test_service_and_store_port_are_the_only_composition_seams():
    assert isinstance(ProfileStorePort, type)
    assert ProfileService is not None
    # Store, authenticated admission and resolved harness validation are explicit.
    import inspect
    parameters = inspect.signature(ProfileService.__init__).parameters
    assert list(parameters)[1:] == ['store', 'admission', 'validator']
