"""Pure-byte encoding vectors; record-specific hashing remains with its owner."""
import pytest

from ordessa_infrastructure.encoding.canonical_json import canonical_bytes, decode_json
from ordessa_infrastructure.encoding.digests import sha256
from ordessa_execution_agents.profiles import canonical_content as profile_canonical
from ordessa_execution_agents.profiles import (canonical_content, content_digest as profile_digest,
    decode_content, encode_content)


GOLDEN_BYTES = b'{"a":[2,1],"s":"\xc3\xa9\\n","z":"\xe7\x8c\xab"}'
GOLDEN_SHA256 = "efba7099c86a4e1d4cd0735f020c3f9326bb6d04486f6e87130ef9256b81d24d"


def test_canonical_utf8_key_order_and_explicit_sha256_golden():
    value = {"z": "猫", "s": "é\n", "a": [2, 1]}
    assert canonical_bytes(value) == GOLDEN_BYTES
    digest = sha256(GOLDEN_BYTES)
    assert type(digest) is bytes and len(digest) == 32
    assert digest.hex() == GOLDEN_SHA256
    assert decode_json(GOLDEN_BYTES) == value


def test_unicode_and_line_endings_are_preserved_without_normalization():
    assert canonical_bytes("é") == b'"\xc3\xa9"'
    assert canonical_bytes("e\u0301") == b'"e\xcc\x81"'
    assert canonical_bytes("é") != canonical_bytes("e\u0301")
    assert canonical_bytes("x\r\ny") == b'"x\\r\\ny"'
    assert canonical_bytes("x\r\ny") != canonical_bytes("x\ny")


def test_sequence_order_and_missing_null_are_distinct():
    assert canonical_bytes([2, 1]) == b"[2,1]"
    assert canonical_bytes((2, 1)) == b"[2,1]"
    assert canonical_bytes([2, 1]) != canonical_bytes([1, 2])
    assert canonical_bytes({}) != canonical_bytes({"x": None})
    assert canonical_bytes([True, False, None]) == b"[true,false,null]"


@pytest.mark.parametrize("value", [-2**63, 2**63 - 1])
def test_integer_range_endpoints_are_exact(value):
    assert canonical_bytes(value) == str(value).encode("ascii")
    assert decode_json(str(value)) == value


@pytest.mark.parametrize("value", [-2**63 - 1, 2**63])
def test_out_of_range_integers_fail_both_ingress_paths(value):
    with pytest.raises(ValueError):
        canonical_bytes(value)
    with pytest.raises(ValueError):
        decode_json(str(value))


@pytest.mark.parametrize("value", [0.0, 1.5, float("nan"), float("inf"), float("-inf")])
def test_even_finite_float_values_are_not_canonical(value):
    with pytest.raises(ValueError):
        canonical_bytes(value)


@pytest.mark.parametrize("raw", ["0.0", "1e0", "NaN", "Infinity", "-Infinity"])
def test_float_and_nonfinite_json_text_is_rejected(raw):
    with pytest.raises(ValueError):
        decode_json(raw)


@pytest.mark.parametrize("raw", ['{"x":1,"x":2}', '{"nested":{"x":1,"x":1}}',
                                '{"x":1,"\\u0078":2}'])
def test_duplicate_keys_cannot_be_collapsed_before_hashing(raw):
    with pytest.raises(ValueError):
        decode_json(raw)


@pytest.mark.parametrize("value", [{1: "key"}, {"set": {1, 2}}, b"payload"])
def test_non_json_values_do_not_gain_a_serialized_identity(value):
    with pytest.raises(ValueError):
        canonical_bytes(value)


def test_sha256_has_no_owner_prefix_or_json_policy():
    assert sha256(b"").hex() == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert sha256(b"abc").hex() == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert sha256(b"abc") != sha256(b"ordessa/artifact/v1\nabc")
    with pytest.raises(TypeError):
        sha256("abc")


def test_existing_profile_canonical_and_digest_remain_unchanged():
    manifest = {"schemaVersion": "profile/1", "declarations": [],
                "harnessDefinitionRef": {"definitionId": "pi", "environmentNamespace": "env-one"}}
    expected = ('{"declarations":[],"harnessDefinitionRef":{"definitionId":"pi",'
                '"environmentNamespace":"env-one"},"schemaVersion":"profile/1"}')
    assert canonical_content(manifest, "env-one") == expected
    assert profile_canonical(manifest, "env-one") == expected
    assert canonical_bytes(encode_content(decode_content(manifest, "env-one"))).decode() == expected
    assert profile_digest(expected) == "sha256:94d49d8b382b0814b1d6e3bbc69de2a0821332bbac4a9229f5aeb6e32c61dbe9"


def test_explicit_library_profile_preserves_numeric_and_mapping_acceptance():
    from collections import UserDict
    from ordessa_infrastructure.encoding.canonical_json import LIBRARY_JSON_PROFILE, CanonicalJSONError
    assert canonical_bytes({"integer": 2**80, "float": 1.5}, profile=LIBRARY_JSON_PROFILE) == b'{"float":1.5,"integer":1208925819614629174706176}'
    with pytest.raises(CanonicalJSONError) as failed:
        canonical_bytes(UserDict({"a": 1}), profile=LIBRARY_JSON_PROFILE)
    assert failed.value.stage == "encode" and failed.value.reason == "encode"
    for value, reason in [(float("nan"), "non_finite"), ({1: 2}, "key_type"), (object(), "type")]:
        with pytest.raises(CanonicalJSONError) as failed:
            canonical_bytes(value, profile=LIBRARY_JSON_PROFILE)
        assert failed.value.stage == "validation" and failed.value.reason == reason
    nested = None
    for _ in range(32):
        nested = [nested]
    assert canonical_bytes(nested, profile=LIBRARY_JSON_PROFILE)
    with pytest.raises(CanonicalJSONError) as failed:
        canonical_bytes([nested], profile=LIBRARY_JSON_PROFILE)
    assert failed.value.reason == "depth"
    assert canonical_bytes([nested])  # default acceptance remains depth 64
