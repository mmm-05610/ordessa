from types import MappingProxyType

import pytest

from ordessa_infrastructure.encoding.immutable_json import safe_json, sealed_mapping


def test_stored_payload_bytes_and_nested_snapshot_are_preserved():
    source = {"é": [1.25, 2**80], "a": {"z": True}}
    sealed = sealed_mapping(source)
    source["é"][0] = 0
    source["a"]["z"] = False
    assert safe_json(sealed) == '{"a":{"z":true},"é":[1.25,1208925819614629174706176]}'
    with pytest.raises(TypeError):
        sealed["a"]["z"] = False
    assert isinstance(sealed, MappingProxyType)
    assert sealed["é"] == (1.25, 2**80)


@pytest.mark.parametrize("value", [{"a": float("nan")}, {"a": float("inf")},
                                  {1: "bad"}, {"a": object()}, [1]])
def test_invalid_payloads_are_rejected(value):
    with pytest.raises(ValueError):
        safe_json(value)


def test_limits_apply_before_persistence_to_utf8_and_nested_mappings():
    assert len(safe_json({"s": "a" * (262144 - 8)}).encode("utf-8")) == 262144
    with pytest.raises(ValueError):
        safe_json({"s": "é" * 131069})
    value = 1
    for _ in range(32):
        value = {"v": value}
    assert safe_json(value)
    with pytest.raises(ValueError):
        safe_json({"v": value})


def test_explicit_owner_budget_does_not_change_default_or_snapshot_integrity():
    value = {"s": "é" * 150000}
    with pytest.raises(ValueError):
        safe_json(value)
    encoded = safe_json(value, max_bytes=400000)
    assert len(encoded.encode("utf-8")) == 300008
    sealed = sealed_mapping(value, max_bytes=400000)
    assert safe_json(sealed, max_bytes=400000) == encoded
    with pytest.raises(TypeError):
        sealed["s"] = "changed"
    with pytest.raises(ValueError):
        safe_json(value, max_bytes=300007)
    with pytest.raises(ValueError):
        safe_json(value)


@pytest.mark.parametrize("limit", [True, False, 0, -1, 1.5, None])
def test_owner_budget_must_be_an_explicit_positive_integer(limit):
    with pytest.raises(ValueError):
        safe_json({}, max_bytes=limit)
