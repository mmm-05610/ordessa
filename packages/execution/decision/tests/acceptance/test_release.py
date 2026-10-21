"""Isolated-wheel proof is executed by the offline acceptance controller."""
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[5]


def _artifact_root():
    raw = os.environ.get('DECISION_ACCEPTANCE_ARTIFACT_ROOT')
    assert raw, 'DECISION_ACCEPTANCE_ARTIFACT_ROOT must name the real acceptance artifact directory'
    root = Path(raw)
    assert root.is_absolute(), 'DECISION_ACCEPTANCE_ARTIFACT_ROOT must be an absolute path'
    assert root.is_dir(), f'acceptance artifact directory is absent: {root}'
    return root


def test_T63_neutral_wheel_has_no_pacthold_dependency_and_runs_two_domains():
    artifacts = _artifact_root()
    dist = artifacts / 'dist'
    wheel = dist / 'ordessa_decision-0.1.0-py3-none-any.whl'
    executable = artifacts / 'runtime-env/bin/python'
    assert wheel.is_file(), f'real neutral runtime wheel is absent: {wheel}'
    assert executable.is_file(), f'clean neutral wheel Python is absent: {executable}'
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        assert not any(name.endswith(('.pyc', '.so')) for name in names)
        assert 'ordessa_decision/definitions/request.schema.json' in names
        assert 'ordessa_decision/definitions/result.schema.json' in names
        assert 'ordessa_decision/definitions/vectors.json' in names
        assert not any(name.startswith('ordessa_decision/providers/jev/') for name in names)
        metadata = archive.read('ordessa_decision-0.1.0.dist-info/METADATA').decode()
        assert 'Requires-Dist: pydantic-graph==2.54.0' in metadata
        assert 'Requires-Dist: pacthold' not in metadata
        assert 'Requires-Dist: typesafe-sdk' not in metadata
        assert 'Requires-Dist: httpx2' not in metadata
        assert 'extra == "jev"' not in metadata
    isolation_script = """import importlib.util
import ordessa_decision
assert 'site-packages' in ordessa_decision.__file__
assert importlib.util.find_spec('ordessa_decision_jev') is None
assert importlib.util.find_spec('ordessa_decision.providers') is None
assert importlib.util.find_spec('typesafe_sdk') is None
"""
    isolated = subprocess.run([str(executable), '-I', '-c', isolation_script], cwd=ROOT,
        capture_output=True, text=True, timeout=60)
    assert isolated.returncode == 0, isolated.stdout + isolated.stderr
    example = ROOT / 'packages/execution/decision/examples/two_domain_runtime.py'
    result = subprocess.run([str(executable), '-I', str(example)], cwd=ROOT,
        capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    rows = json.loads(result.stdout)
    assert [(row['domain'], row['disposition']) for row in rows] == [
        ('materials-screening', 'revise'),
        ('materials-screening-rejected', 'blocked'),
        ('did-evidence-review', 'revise'),
        ('did-evidence-review-incomplete', 'clarify'),
        ('did-evidence-review-stale', 'blocked'),
    ]
    assert all(row['evidence_status'] == 'completed' and row['model_calls'] == 0 for row in rows)
    assert rows[0]['issues'] == [{'candidate_id': 'best-eligible', 'code': 'material-ranked'}]
    assert rows[1]['issues'] == [{'code': 'no-material-within-risk-limit'}]
    assert rows[3]['issues'] == [{'claim_ids': ['service-endpoint'], 'code': 'did-source-version-missing'}]
    assert rows[4]['issues'] == [{'claim_ids': ['controller'], 'code': 'did-source-baseline-mismatch'}]
