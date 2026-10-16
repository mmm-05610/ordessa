"""Typed immutable intent retains all existing JSON schema and historical bytes."""
import copy
from dataclasses import FrozenInstanceError

import pytest

from ordessa_execution_agents.profiles.definitions.models import (
    Profile, ProfileContent, ProfileRevision, ProfileRevisionRef, ConfigurationDeclaration,
)
from ordessa_execution_agents.profiles.definitions.json_values import OMITTED
from ordessa_execution_agents.profiles.definitions.codec import (
    decode_content, encode_content, decode_revision, encode_revision, content_digest,
    decode_declaration, encode_declaration, encode_profile, encode_revision_ref,
)
from ordessa_execution_agents.profiles.definitions.validation import canonical, ProfileValidationError


def content():
    return {"schemaVersion": "profile/1", "harnessDefinitionRef": {
        "environmentNamespace": "typed-test", "definitionId": "unknown", "revision": "1"},
        "declarations": [{"declarationId": "settings", "configurationKind": "unknown.settings",
            "schemaVersion": "unknown/1", "action": "value", "requirement": "required",
            "payload": {"nested": [{"enabled": False, "values": [None, 0, 0.5, "猫"]}],
                        "password": {"secretRef": {"ref": "secret-one", "revision": "1",
                            "owner_namespace": "owner", "access_purpose": "configuration"}}},
            "resourceRefs": [{"environmentNamespace": "typed-test", "ref": "opaque", "revision": "1",
                              "nested": {"values": [1, None]}}]}],
        "metadata": {"nested": {"values": ["preserved"]}}}


def revision(parsed):
    return decode_revision({"ref": {"environmentNamespace": "typed-test", "profileId": "preset",
        "manifestRevision": 1, "contentDigest": content_digest(canonical(parsed))}, "content": parsed})


def test_content_is_typed_and_single_authority_with_derived_json():
    parsed = content()
    value = revision(parsed)
    assert type(value) is ProfileRevision
    assert type(value.ref) is ProfileRevisionRef
    assert type(value.content) is ProfileContent
    assert type(value.content.declarations[0]) is ConfigurationDeclaration
    assert canonical(encode_content(value.content)) == canonical(parsed)
    assert encode_revision(value)["content"] == parsed
    assert value.ref.digest == content_digest(canonical(encode_content(value.content)))
    assert not hasattr(value, "content_json")
    with pytest.raises(TypeError):
        ProfileRevision(value.ref, value.content, content_json="another authority")
    with pytest.raises(ProfileValidationError):
        ProfileRevision(value.ref, parsed)
    with pytest.raises((FrozenInstanceError, AttributeError)):
        value.content = value.content


def test_nested_values_are_frozen_and_inputs_outputs_are_defensive_copies():
    parsed = content()
    expected = copy.deepcopy(parsed)
    value = revision(parsed)
    parsed["declarations"][0]["payload"]["nested"][0]["values"].append("input mutation")
    parsed["harnessDefinitionRef"]["revision"] = "999"
    parsed["declarations"][0]["resourceRefs"][0]["nested"]["values"].clear()
    parsed["metadata"]["nested"]["values"].clear()
    declaration = value.content.declarations[0]
    with pytest.raises(TypeError):
        declaration.payload["nested"][0]["enabled"] = True
    with pytest.raises(AttributeError):
        declaration.payload["nested"].append({})
    with pytest.raises(TypeError):
        declaration.resource_refs[0]["nested"]["values"][0] = 2
    with pytest.raises(TypeError):
        value.content.harness_definition_ref["revision"] = "2"
    with pytest.raises(TypeError):
        value.content.metadata["nested"]["new"] = "x"
    with pytest.raises(FrozenInstanceError):
        declaration.action = "reset"
    out = encode_revision(value)
    out["content"]["declarations"][0]["payload"]["nested"][0]["values"].clear()
    assert encode_content(value.content) == expected
    assert encode_revision(value)["ref"]["contentDigest"] == content_digest(canonical(expected))


def test_direct_model_construction_copies_lists_mappings_and_validates_combination():
    payload = {"nested": [1, 2]}
    refs = [{"environmentNamespace": "typed-test", "ref": "resource"}]
    declaration = ConfigurationDeclaration("x", "opaque", "1", "value", "optional", payload, refs)
    items = [declaration]
    reference = {"environmentNamespace": "typed-test", "definitionId": "unknown"}
    value = ProfileContent("1", reference, items)
    payload["nested"].clear(); refs[0]["ref"] = "changed"; items.clear(); reference.clear()
    assert encode_content(value)["declarations"][0]["payload"] == {"nested": [1, 2]}
    assert encode_content(value)["declarations"][0]["resourceRefs"][0]["ref"] == "resource"
    with pytest.raises(ProfileValidationError):
        ConfigurationDeclaration("x", "opaque", "1", "disabled", "required", payload=None)
    with pytest.raises(ProfileValidationError):
        ProfileContent("1", value.harness_definition_ref, (declaration, declaration))
    with pytest.raises(ProfileValidationError):
        ConfigurationDeclaration("x", "opaque", "1", "value", "required",
                                 resource_refs=({"ref": "missing-scope", "revision": "1"},))


def test_omission_null_empty_and_false_values_roundtrip_without_inventing_defaults():
    base = {"declarationId": "x", "configurationKind": "unknown", "schemaVersion": "1",
            "action": "reset", "requirement": "optional"}
    assert decode_declaration(base).payload is OMITTED
    assert decode_declaration(base).resource_refs is None
    assert encode_declaration(decode_declaration(base)) == base
    assert encode_declaration(decode_declaration({**base, "resourceRefs": []})) == {**base, "resourceRefs": []}
    for payload in (None, False, 0, [], {}):
        data = {**base, "action": "value", "payload": payload}
        assert encode_declaration(decode_declaration(data)) == data
    parsed = {"schemaVersion": "1", "harnessDefinitionRef": {
        "environmentNamespace": "typed-test", "definitionId": "unknown"}, "declarations": [base]}
    without = decode_content(parsed, "typed-test")
    with_empty = decode_content({**parsed, "metadata": {}}, "typed-test")
    assert "metadata" not in encode_content(without)
    assert encode_content(with_empty)["metadata"] == {}
    assert canonical(encode_content(without)) != canonical(encode_content(with_empty))


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(extra=True),
    lambda p: p.update(metadata=None),
    lambda p: p["declarations"][0].update(payload=object()),
    lambda p: p["declarations"][0].update(payload=float("inf")),
    lambda p: p["declarations"][0].update(resourceRefs=[1]),
    lambda p: p["declarations"][0].update(resourceRefs=[{"environmentNamespace": "other", "ref": "x"}]),
    lambda p: p["declarations"][0].update(action="unknown"),
    lambda p: p["declarations"][0].update(extra=True),
])
def test_unknown_fields_and_invalid_values_refused_before_typed_construction(mutation):
    parsed = content(); mutation(parsed)
    with pytest.raises(ProfileValidationError):
        decode_content(parsed, "typed-test")


def test_typed_revision_retains_original_profile_digest_golden():
    parsed = {"schemaVersion": "profile/1", "declarations": [],
              "harnessDefinitionRef": {"definitionId": "pi", "environmentNamespace": "env-one"}}
    expected = ('{"declarations":[],"harnessDefinitionRef":{"definitionId":"pi",'
                '"environmentNamespace":"env-one"},"schemaVersion":"profile/1"}')
    value = ProfileRevision(ProfileRevisionRef("env-one", "main", 1,
        "sha256:94d49d8b382b0814b1d6e3bbc69de2a0821332bbac4a9229f5aeb6e32c61dbe9"),
        decode_content(parsed, "env-one"))
    assert canonical(encode_content(value.content)) == expected
    assert value.ref.digest == content_digest(expected)
    profile = Profile("main", 7, "Preset", None, value.ref)
    assert profile.version == 7 and profile.current_revision.revision == 1
    assert profile.archived is False
    assert encode_profile(profile)["catalogRevision"] == 7
    assert encode_profile(profile)["currentManifestRef"]["manifestRevision"] == 1


def test_codec_boundaries_recheck_digest_and_complete_content_size():
    parsed = {"schemaVersion": "profile/1", "declarations": [],
              "harnessDefinitionRef": {"definitionId": "pi", "environmentNamespace": "env-one"}}
    content_value = decode_content(parsed, "env-one")
    forged = ProfileRevision(ProfileRevisionRef("env-one", "main", 1, "sha256:" + "0" * 64),
                             content_value)
    with pytest.raises(ProfileValidationError, match="digest"):
        encode_revision(forged)

    oversized = ProfileContent("profile/1", parsed["harnessDefinitionRef"], (),
                               {"large": "x" * 262144})
    with pytest.raises(ProfileValidationError, match="size"):
        encode_content(oversized)


def test_codec_boundaries_revalidate_post_construction_reference_and_profile_mutation():
    digest = "sha256:" + "0" * 64
    ref = ProfileRevisionRef("env-one", "main", 1, digest)
    object.__setattr__(ref, "revision", True)
    with pytest.raises(ProfileValidationError):
        encode_revision_ref(ref)

    parsed = {"schemaVersion": "profile/1", "declarations": [],
              "harnessDefinitionRef": {"definitionId": "pi", "environmentNamespace": "env-one"}}
    valid_ref = ProfileRevisionRef("env-one", "main", 1,
                                   "sha256:94d49d8b382b0814b1d6e3bbc69de2a0821332bbac4a9229f5aeb6e32c61dbe9")
    profile = Profile("main", 7, "Preset", None, valid_ref)
    object.__setattr__(profile, "version", True)
    with pytest.raises(ProfileValidationError):
        encode_profile(profile)

    profile = Profile("main", 7, "Preset", None, valid_ref)
    object.__setattr__(profile, "profile_id", "other")
    with pytest.raises(ProfileValidationError):
        encode_profile(profile)

    # A revision model may exist with a syntactically valid but mismatched digest;
    # the codec remains the authoritative content/ref binding boundary.
    content_value = decode_content(parsed, "env-one")
    forged = ProfileRevision(ProfileRevisionRef("env-one", "main", 1, "sha256:" + "0" * 64),
                             content_value)
    with pytest.raises(ProfileValidationError, match="digest"):
        encode_revision(forged)
