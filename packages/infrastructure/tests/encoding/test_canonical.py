import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from ordessa_infrastructure.encoding import canonical_bytes, decode_json, sha256
from ordessa_infrastructure.encoding.canonical_json import (
    CanonicalJSONError, LIBRARY_JSON_PROFILE, canonical_text,
)


MIRROR = Path(__import__('ordessa_infrastructure.encoding.canonical_json', fromlist=['x']).__file__).with_suffix('.mjs')


def javascript(value):
    code = "import {stableJSON,jsonDigest} from " + json.dumps(MIRROR.as_uri()) + "; " \
           "let raw=''; for await (const chunk of process.stdin) raw+=chunk; " \
           "const value=JSON.parse(raw); console.log(JSON.stringify([stableJSON(value),jsonDigest(value)]));"
    result = subprocess.run(['node', '--input-type=module', '-e', code],
                            input=json.dumps(value), text=True, capture_output=True, timeout=5)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize('value,expected', [
    ({'z': [True, None, -7], 'a': '中\n"\\'}, b'{"a":"\xe4\xb8\xad\\n\\"\\\\","z":[true,null,-7]}'),
    ({'nested': {'b': 2, 'a': 1}, 'array': [3, 1, 2]}, b'{"array":[3,1,2],"nested":{"a":1,"b":2}}'),
    ({'e': 'e\u0301', 'é': 'é', 'emoji': '😀'}, '{"e":"e\u0301","emoji":"😀","é":"é"}'.encode()),
    ([-(2**53-1), 2**53-1], b'[-9007199254740991,9007199254740991]'),
])
def test_common_python_javascript_golden_bytes_and_digest(value, expected):
    assert canonical_bytes(value) == expected
    assert canonical_text(value).encode() == expected
    encoded, digest = javascript(value)
    assert encoded.encode() == expected
    assert digest == hashlib.sha256(expected).hexdigest() == sha256(expected).hex()


def test_python_int64_endpoints_and_library_historical_floats():
    assert canonical_bytes([-(2**63), 2**63-1]) == b'[-9223372036854775808,9223372036854775807]'
    assert canonical_bytes({'x': 1.0, 'n': -0.0}, profile=LIBRARY_JSON_PROFILE) == b'{"n":-0.0,"x":1.0}'
    assert canonical_bytes(2**100, profile=LIBRARY_JSON_PROFILE) == str(2**100).encode()


@pytest.mark.parametrize('value,reason', [
    (1.0, 'type'), (float('nan'), 'type'), (float('inf'), 'type'),
    (2**63, 'type'), (-(2**63)-1, 'type'), ({1: 'a'}, 'key_type'), (b'bytes', 'type'),
])
def test_strict_rejects_noncanonical_values(value, reason):
    with pytest.raises(CanonicalJSONError) as caught:
        canonical_bytes(value)
    assert caught.value.reason == reason


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -float('inf')])
def test_library_still_rejects_nonfinite(value):
    with pytest.raises(CanonicalJSONError) as caught:
        canonical_bytes(value, profile=LIBRARY_JSON_PROFILE)
    assert caught.value.reason == 'non_finite'


def test_depth_boundary_and_cycle_fail_without_infinite_recursion():
    value = None
    for _ in range(64):
        value = [value]
    canonical_bytes(value)
    with pytest.raises(CanonicalJSONError, match='json_depth'):
        canonical_bytes([value])
    cycle = []
    cycle.append(cycle)
    with pytest.raises(CanonicalJSONError, match='json_depth'):
        canonical_bytes(cycle)


@pytest.mark.parametrize('raw', ['{"a":1,"a":2}', '{"x":{"a":1,"a":2}}', 'NaN', 'Infinity', '1.0', str(2**63)])
def test_decode_rejects_duplicates_and_strict_invalid_values(raw):
    with pytest.raises(ValueError):
        decode_json(raw)


def test_decode_preserves_array_order_and_unicode_without_normalization():
    assert decode_json(b'{"z":[2,1],"a":"e\\u0301"}') == {'z': [2, 1], 'a': 'e\u0301'}
    assert canonical_bytes('e\u0301') != canonical_bytes('é')
    assert sha256(b'abc').hex() == 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'
    with pytest.raises(TypeError, match='digest_requires_bytes'):
        sha256(bytearray(b'abc'))


@pytest.mark.parametrize('value', [2**53+1, {'😀': 1, '\ue000': 2}])
def test_existing_mirror_limitations_are_explicit(value):
    # Historical acceptance/sort differences are recorded, not silently fixed.
    encoded, _ = javascript(value)
    assert encoded.encode() != canonical_bytes(value)


def test_javascript_rejects_nonjson_cycles_and_sparse_arrays():
    code = "import {stableJSON} from " + json.dumps(MIRROR.as_uri()) + "; " + r'''
        import assert from 'node:assert/strict';
        const cycle = {}; cycle.self = cycle;
        const sparseWithProperty = new Array(1); sparseWithProperty.other = 1;
        for (const value of [undefined, NaN, Infinity, new Date(), cycle,
                             new Array(1), sparseWithProperty, {x:undefined}]) {
          assert.throws(() => stableJSON(value), TypeError);
        }
        console.log('8 rejected non-JSON vectors');
    '''
    result = subprocess.run(['node', '--input-type=module', '-e', code], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
