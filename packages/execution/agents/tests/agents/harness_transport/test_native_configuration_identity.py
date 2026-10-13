"""Actual JS codec/reader parity; no alternate hash implementation fixture."""
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from ordessa_execution_agents.harness.configuration.compilation.native_digest import configuration_digest

ROOT = Path(__file__).resolve().parents[6]
DIGEST = ROOT / "packages/execution/agents/src/ordessa_execution_agents/harness/configuration/acp/digest.mjs"
READER = ROOT / "plugins/harness/pi/src/ordessa_harness_pi/acp/profile/configuration-query.mjs"


def js_result(options):
    script = f"""
      import {{ configurationDigest }} from {json.dumps(DIGEST.as_uri())};
      import {{ configurationReader }} from {json.dumps(READER.as_uri())};
      import fs from 'node:fs';
      const options = JSON.parse(fs.readFileSync(0, 'utf8'));
      const session = {{ configOptions: () => options }};
      const read = configurationReader({{ live: new Map([['s', session]]) }}, m => new Error(m));
      try {{ const observed = read({{sessionId:'s'}});
        console.log(JSON.stringify({{digest:configurationDigest(observed), options:observed.configOptions}}));
      }} catch (error) {{ console.log(JSON.stringify({{error:error.message}})); }}
    """
    return json.loads(subprocess.run(["node", "--input-type=module", "-e", script],
        input=json.dumps(options), text=True, capture_output=True, check=True).stdout)


@pytest.mark.parametrize("metadata", [
    {"epsilon": 1, "empty": None, "ok": True},
    {"😀": "first", "\ue000": "second", "10": 10, "2": 2},
    {"n": 9007199254740991, "negative": -9007199254740991},
    {"integral": 1.0, "zero": -0.0, "nested": ["雪", {"line": "\n\t\u0001"}]},
])
def test_actual_pi_reader_preserves_all_supported_metadata_and_matches_python(metadata):
    options = [{"id": "thinkingLevel", "currentValue": "low", "_meta": metadata}]
    result = js_result(options)
    assert result["options"] == options
    assert result["digest"] == configuration_digest(options)


@pytest.mark.parametrize("number", [1e-7, 1.5, 9007199254740992, -9007199254740992])
def test_both_read_boundaries_explicitly_refuse_unsupported_numbers(number):
    options = [{"id": "model", "_meta": {"epsilon": number}}]
    with pytest.raises(ValueError, match="expected safe integer"):
        configuration_digest(options)
    assert "expected safe integer" in js_result(options)["error"]


def test_existing_ascii_string_selector_identity_is_unchanged():
    options = [{"id": "model", "type": "select", "currentValue": "p/m", "options": [{"value": "p/m"}]}]
    original = hashlib.sha256(json.dumps(options, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    assert configuration_digest(options) == original == js_result(options)["digest"]


def test_metadata_remains_identity_bearing():
    first = [{"id": "model", "_meta": {"other": "first"}}]
    second = [{"id": "model", "_meta": {"other": "second"}}]
    assert configuration_digest(first) != configuration_digest(second)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), "\ud800", {1: "value"}])
def test_non_wire_identity_values_are_refused(bad):
    with pytest.raises((ValueError, UnicodeError)):
        configuration_digest([{"_meta": bad}])


def test_cyclic_identity_is_refused_without_mutation():
    options = []
    options.append(options)
    with pytest.raises(ValueError, match="Cyclic"):
        configuration_digest(options)
    assert options[0] is options
