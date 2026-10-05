import hashlib
import json
from pathlib import Path
import subprocess
import zipfile
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[5]

def test_T63_independent_wheel_optional_boundaries():
    wheel=ROOT/'.decision-tmp/dist/ordessa_decision-0.1.0-py3-none-any.whl'
    assert wheel.exists(),'offline entry must build wheel first'
    with zipfile.ZipFile(wheel) as z:
        names=z.namelist()
        assert not any(n.endswith(('.pyc','.so')) for n in names)
        for n in names:
            if n.startswith('ordessa_decision/') and n.endswith(('.py','.json')):
                source=ROOT/'packages/backend/decision/src'/n
                assert source.exists() and z.read(n)==source.read_bytes(),f'stale wheel member {n}'
        metadata=z.read('ordessa_decision-0.1.0.dist-info/METADATA').decode()
        assert 'Requires-Dist: pydantic-graph==2.54.0' in metadata
        assert 'extra == "jev"' in metadata and 'extra == "ordessa"' in metadata
    executable=ROOT/'.decision-tmp/wheel-env/bin/python'
    assert executable.exists(),'offline entry must prepare clean base wheel environment'
    script="""import asyncio,importlib.util,ordessa_decision
from ordessa_decision.offline import run_offline
assert importlib.util.find_spec('pacthold') is None
assert importlib.util.find_spec('typesafe_sdk') is None
for alternate in (False,True):
 result=asyncio.run(run_offline(alternate=alternate));assert result.outcome.disposition=='ready'
assert '/packages/backend/decision/src/' not in ordessa_decision.__file__
print('base wheel standalone: default+alternate; SDK/core absent')
"""
    result=subprocess.run([str(executable),'-I','-c',script],cwd=wheel.parent,text=True,capture_output=True)
    assert result.returncode==0,result.stdout+result.stderr
    # Core direction source must not introduce the optional module or SDK.
    for p in (ROOT/'packages/backend/pacthold/src').rglob('*.py'):
        assert 'ordessa_decision' not in p.read_text() and 'typesafe_sdk' not in p.read_text()

def test_T64_fixed_baseline_regression_id_comparison():
    def results(path):
        assert path.exists(),'baseline receipt absent'
        out={}
        for t in ET.parse(path).findall('.//testcase'):
            cls=t.attrib['classname'];cls=cls[cls.index('tests.platform'):]
            key=cls+'::'+t.attrib['name']
            assert key not in out
            out[key]='failed' if t.find('failure') is not None or t.find('error') is not None else 'skipped' if t.find('skipped') is not None else 'passed'
        return out
    baseline=results(ROOT/'.decision-tmp/baseline-core.xml'); current=results(ROOT/'.decision-tmp/current-core.xml')
    assert len(baseline)==len(current)==40 and baseline==current
    assert set(current.values())=={'passed'}
