"""Candidate input admits original nullable Plan JSON, never self-authority."""
import json
from pathlib import Path
import runpy

import pytest
from jsonschema import Draft202012Validator
from ordessa_engineering.domain.reviews.codec import encode_plan, decode_plan

ROOT = Path(__file__).resolve().parents[4]
SCHEMA = ROOT / 'methods/incremental-engineering/candidates/2.6.0/documents/work-inputs/schema.json'


def _validator():
    schema = json.loads(SCHEMA.read_text())
    return Draft202012Validator({'$defs': schema['$defs'], '$ref': '#/$defs/event_value'})


def test_original_plan_json_keeps_nullable_fields_and_roundtrips():
    helpers = runpy.run_path(str(Path(__file__).parents[1] / 'domain/test_review_rules.py'))
    plan = helpers['_case']()[1]
    native = json.loads(encode_plan(plan))
    assert native['aggregation_policy']['threshold'] is None
    assert native['check_policies'][0]['applicability_rule_ref'] is None
    assert decode_plan(encode_plan(plan)) == plan
    _validator().validate(native)


@pytest.mark.parametrize('key', ['ready', 'accepted', 'authorized', 'approval_granted'])
def test_nullable_plan_input_still_rejects_nested_self_authority(key):
    value = {'plan': {'threshold': None, 'nested': {key: True}}}
    assert list(_validator().iter_errors(value))
