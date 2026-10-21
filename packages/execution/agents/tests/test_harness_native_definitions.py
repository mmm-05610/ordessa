"""Pure Harness contracts preserve bounds without retired Work Core imports."""
from dataclasses import FrozenInstanceError
import pytest
from ordessa_agents.harness.definitions import (
    NativeProfileRef, NativeContinuationRef, NativeCredentialRef,
    NativeRefInvalid, ProviderDescriptor,
)

KINDS = (NativeProfileRef, NativeContinuationRef, NativeCredentialRef)


@pytest.mark.parametrize("kind", KINDS)
def test_native_locator_preserves_identity_and_copies_bounded_metadata(kind):
    metadata = {"k" * 64: "v" * 256, **{str(i): "value" for i in range(15)}}
    locator = kind("provider", "native-id", "native://unchanged", metadata)
    assert locator.provider == "provider" and locator.native_id == "native-id"
    assert locator.uri == "native://unchanged" and locator.metadata == metadata
    metadata.clear()
    assert len(locator.metadata) == 16
    assert not hasattr(locator, "type")
    with pytest.raises(FrozenInstanceError):
        locator.provider = "changed"


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("metadata", [
    {str(i): "v" for i in range(17)}, {"k" * 65: "v"}, {"k": "v" * 257},
    {1: "v"}, {"k": 1}, {"k": {"nested": "v"}}, None,
])
def test_native_locator_rejects_out_of_bounds_or_nonstring_metadata(kind, metadata):
    with pytest.raises(NativeRefInvalid):
        kind("provider", "native-id", metadata=metadata)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("provider,native_id", [("", "id"), ("p", ""), (None, "id"), ("p", 1)])
def test_native_locator_requires_string_identity(kind, provider, native_id):
    with pytest.raises(NativeRefInvalid):
        kind(provider, native_id)


@pytest.mark.parametrize("kind", KINDS)
def test_native_locator_accepts_absent_uri_but_rejects_nonstring_uri(kind):
    assert kind("p", "id").uri is None
    with pytest.raises(NativeRefInvalid):
        kind("p", "id", uri=42)


def test_native_locator_kinds_are_distinct_even_with_identical_fields():
    profile, continuation, credential = [kind("p", "id") for kind in KINDS]
    assert profile != continuation and profile != credential and continuation != credential
    assert not isinstance(continuation, NativeProfileRef)
    assert not isinstance(credential, NativeContinuationRef)


@pytest.mark.parametrize("provider_id", ["a", "provider.name-1_test", "0"])
def test_provider_descriptor_preserves_exact_values(provider_id):
    descriptor = ProviderDescriptor(provider_id, " Display ", " version ")
    assert descriptor.id == provider_id
    assert descriptor.display_name == " Display " and descriptor.version == " version "


@pytest.mark.parametrize("provider_id", ["", "Upper", "_prefix", "a/b", "a b", None, 1])
def test_provider_descriptor_rejects_invalid_ids(provider_id):
    with pytest.raises(ValueError):
        ProviderDescriptor(provider_id, "display", "version")


@pytest.mark.parametrize("display,version", [("", "1"), (" ", "1"), (None, "1"), (1, "1"), ("d", ""), ("d", " "), ("d", None), ("d", 1)])
def test_provider_descriptor_requires_nonempty_string_display_and_version(display, version):
    with pytest.raises(ValueError):
        ProviderDescriptor("provider", display, version)
