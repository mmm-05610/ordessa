"""Explicit current 126->127 planner guards, separate from R1's old authority."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

from ordessa_engineering.adapters.registry import source_integrity as si
from ordessa_engineering.domain.artifacts.library_material_codec import content_digest

ROOT = Path(__file__).resolve().parents[3]


def _tool():
    spec = importlib.util.spec_from_file_location('refresh_current_registry', ROOT/'tooling/registry/refresh_current_registry.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _inputs(tool):
    return {'old_bytes':tool.BASE_FIXTURE.read_bytes(), 'facts':si.implementation_facts(),
            'operations':tool.current_operations()}


def test_current_plan_is_explicit_new_revision_with_actual_reviewed_contract_delta():
    tool = _tool()
    inputs = _inputs(tool)
    before = inputs['old_bytes']
    plan = tool.build_plan(**inputs)
    value = json.loads(plan['bytes'])
    assert value['revision'] == 127
    assert value['implementation'] == inputs['facts']
    assert value['implementation']['decision_contract_version'] == 'decision-job/1'
    assert 'pydantic_graph_version' not in value['implementation']
    assert set(plan['receipt']['changed_operations']) == {'engineering.reviews.assign_reviewer'}
    changed = plan['receipt']['changed_operations']['engineering.reviews.assign_reviewer']
    assert changed['before']['version'] == '1' and changed['after']['version'] == '2'
    assert tool.BASE_FIXTURE.read_bytes() == before
    assert tool.build_plan(**{**inputs,'old_bytes':plan['bytes']}) is None


@pytest.mark.parametrize('mutation', ['extra-operation', 'other-operation', 'old-reviewer-contract'])
def test_current_plan_refuses_unreviewed_or_incomplete_contract_changes(mutation):
    tool = _tool()
    inputs = _inputs(tool)
    old = json.loads(inputs['old_bytes'])
    if mutation == 'extra-operation':
        inputs['operations']['engineering.unreviewed'] = {'version':'1','inputs':{},'results':[]}
    elif mutation == 'other-operation':
        inputs['operations']['engineering.packages.freeze']['version'] = '99'
    else:
        inputs['operations']['engineering.reviews.assign_reviewer'] = old['operations']['engineering.reviews.assign_reviewer']
    with pytest.raises(tool.RefreshRefused, match='operation contract change'):
        tool.build_plan(**inputs)


@pytest.mark.parametrize('mutation', ['source-content', 'source-omission', 'dependency', 'contract', 'graph'])
def test_current_plan_refuses_source_or_foreign_facts_drift(mutation):
    tool = _tool()
    inputs = _inputs(tool)
    if mutation == 'source-content':
        inputs['facts']['engineering']['adapters/decision/source_job.py'] = 'sha256:'+'0'*64
    elif mutation == 'source-omission':
        del inputs['facts']['ordessa_decision']['historical/reader.py']
    elif mutation == 'dependency':
        inputs['facts']['jsonschema_version'] = '4.19.2'
    elif mutation == 'contract':
        inputs['facts']['decision_contract_version'] = 'decision/1'
    else:
        inputs['facts']['pydantic_graph_version'] = '2.54.0'
    with pytest.raises(tool.RefreshRefused):
        tool.build_plan(**inputs)


def test_current_plan_refuses_same_path_other_valid_bytes_and_frozen_target_drift(monkeypatch):
    tool = _tool()
    inputs = _inputs(tool)
    other = json.loads(inputs['old_bytes'])
    other['revision'] = 128
    other['registry_digest'] = content_digest({k:v for k,v in other.items() if k!='registry_digest'})
    with pytest.raises(tool.RefreshRefused, match='neither exact revision-126'):
        tool.build_plan(**{**inputs,'old_bytes':tool._encoded(other)})
    monkeypatch.setattr(tool, 'EXPECTED_TARGET_SHA256', '0'*64)
    with pytest.raises(tool.RefreshRefused, match='frozen revision-127'):
        tool.build_plan(**inputs)


def test_write_without_final_source_freeze_makes_no_changes(monkeypatch, tmp_path):
    tool = _tool()
    inputs = _inputs(tool)
    resource = tmp_path/'operation_registry.v1.json'
    resource.write_bytes(inputs['old_bytes'])
    monkeypatch.setattr(tool, 'RESOURCE', resource)
    monkeypatch.setattr(tool, 'EXPECTED_TARGET_SHA256', None)
    evidence = tmp_path/'evidence'
    with pytest.raises(tool.RefreshRefused, match='writing requires frozen target hash'):
        tool.main(['--write','--evidence',str(evidence)])
    assert resource.read_bytes() == inputs['old_bytes']
    assert not evidence.exists()
