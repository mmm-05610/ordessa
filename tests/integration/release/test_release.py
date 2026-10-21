import hashlib
import json
import os
from pathlib import Path
import subprocess
import zipfile
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[3]

def artifact_root():
    raw=os.environ.get('DECISION_ACCEPTANCE_ARTIFACT_ROOT')
    assert raw,'DECISION_ACCEPTANCE_ARTIFACT_ROOT must name the real acceptance artifact directory'
    root=Path(raw)
    assert root.is_absolute(),'DECISION_ACCEPTANCE_ARTIFACT_ROOT must be an absolute path'
    assert root.is_dir(),f'acceptance artifact directory is absent: {root}'
    return root

def test_T63_independent_wheel_optional_boundaries():
    """Current owner wheels replace the retired Kernel/C1 optional assembly."""
    artifacts = artifact_root()
    wheels = artifacts / 'wheels'
    assert wheels.is_dir(), 'final owner wheel directory is absent'
    expected = {
        'ordessa_decision': ('ordessa_decision', 'decision-runtime', 'packages/execution/decision'),
        'ordessa_decision_jev': ('ordessa_decision_jev', 'ordessa-decision-jev', 'plugins/decision/jev'),
        'ordessa_units': ('ordessa_units', 'ordessa-units', 'packages/execution/units'),
        'ordessa_agents': ('ordessa_agents', 'ordessa-execution-agents', 'packages/execution/agents'),
        'ordessa_environments': ('ordessa_environments', 'ordessa-environments', 'packages/execution/environments'),
    }
    for stem, (namespace, distribution, project) in expected.items():
        matches = list(wheels.glob(stem + '-*.whl'))
        assert len(matches) == 1, (stem, matches)
        with zipfile.ZipFile(matches[0]) as archive:
            names = archive.namelist()
            assert not any(name.endswith(('.pyc', '.so')) for name in names)
            assert not any(name.startswith(('pacthold/', 'ordessa_execution_api/')) for name in names)
            metadata_path, = (name for name in names if name.endswith('.dist-info/METADATA'))
            metadata = archive.read(metadata_path).decode()
            assert 'Name: ' + distribution in metadata
            assert 'Requires-Dist: pacthold' not in metadata
            assert 'Requires-Dist: ordessa-execution-api' not in metadata
            for name in names:
                if not name.startswith(namespace + '/') or name.endswith('/'):
                    continue
                source = ROOT / project / 'src' / name
                assert source.is_file(), (stem, name)
                assert archive.read(name) == source.read_bytes(), (stem, name)
            if stem == 'ordessa_decision':
                assert 'Requires-Dist: pydantic-graph==2.54.0' in metadata
                assert 'Requires-Dist: typesafe-sdk' not in metadata
                assert 'Requires-Dist: httpx2' not in metadata
                assert not any(name.startswith('ordessa_decision/providers/') for name in names)
                for name in ('request.schema.json', 'result.schema.json', 'vectors.json'):
                    assert 'ordessa_decision/definitions/' + name in names
            elif stem == 'ordessa_decision_jev':
                for dependency in ('decision-runtime==0.1.0', 'typesafe-sdk==0.7.2', 'httpx2==2.13.1', 'pydantic==2.13.5'):
                    assert 'Requires-Dist: ' + dependency in metadata
    assert not list(wheels.glob('pacthold-*.whl'))
    assert not list(wheels.glob('ordessa_execution_api-*.whl'))
    executable = artifacts / 'venv/bin/python'
    assert executable.is_file(), 'fresh final owner interpreter is absent'
    outside = artifacts / 'outside-repository'
    outside.mkdir(exist_ok=True)
    script = """
import importlib.util
from importlib.metadata import PackageNotFoundError, distribution
from ordessa_decision import DecisionManager
from ordessa_units.api import UnitManager, UnitSpec
from ordessa_environments import EnvironmentManager, EnvironmentInstance
for module in ('ordessa_decision', 'ordessa_units', 'ordessa_environments', 'ordessa_decision_jev'):
    spec = importlib.util.find_spec(module)
    assert spec is not None and 'site-packages' in spec.origin, (module, spec)
for module in ('pacthold', 'ordessa_execution_api', 'ordessa_server', 'ordessa_engineering'):
    assert importlib.util.find_spec(module) is None, module
for name in ('pacthold', 'ordessa-execution-api'):
    try: distribution(name)
    except PackageNotFoundError: pass
    else: raise AssertionError('retired distribution is installed: ' + name)
"""
    result = subprocess.run([str(executable), '-I', '-c', script], cwd=outside, text=True, capture_output=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    checked = subprocess.run([str(executable), '-I', '-m', 'pip', 'check'], cwd=outside, text=True, capture_output=True, timeout=60)
    assert checked.returncode == 0, checked.stdout + checked.stderr

def test_T64_fixed_baseline_regression_id_comparison():
    artifacts=artifact_root()
    def results(path):
        assert path.exists(),'baseline receipt absent'
        out={}
        for t in ET.parse(path).findall('.//testcase'):
            cls=t.attrib['classname'];cls=cls[cls.index('tests.'):]
            key=cls+'::'+t.attrib['name']
            assert key not in out
            out[key]='failed' if t.find('failure') is not None or t.find('error') is not None else 'skipped' if t.find('skipped') is not None else 'passed'
        return out
    baseline=results(artifacts/'baseline-core.xml'); current=results(artifacts/'current-core.xml')
    assert len(baseline)==len(current)==57 and baseline==current
    assert set(current.values())=={'passed'}
