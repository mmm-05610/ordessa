import hashlib
import json
from pathlib import Path
import subprocess
import zipfile
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[6]

def test_T63_independent_wheel_optional_boundaries():
    wheel=ROOT/'.decision-tmp/dist/pacthold-2.0.0a1-py3-none-any.whl'
    assert wheel.exists(),'offline entry must build wheel first'
    with zipfile.ZipFile(wheel) as z:
        names=z.namelist()
        assert not any(n.endswith(('.pyc','.so')) for n in names)
        for n in names:
            if n.startswith('pacthold/decision/') and n.endswith(('.py','.json')):
                source=ROOT/'packages/backend/pacthold/src'/n
                assert source.exists() and z.read(n)==source.read_bytes(),f'stale wheel member {n}'
        metadata=z.read('pacthold-2.0.0a1.dist-info/METADATA').decode()
        assert 'Requires-Dist: pydantic-graph==2.54.0' in metadata
        assert 'extra == "jev"' in metadata
        # Replacement for the retired ordessa-decision "ordessa" extra: the
        # kernel read seam is now a main dependency of the pacthold wheel.
        assert 'Requires-Dist: ordessa-environment-api' in metadata
    executable=ROOT/'.decision-tmp/wheel-env/bin/python'
    assert executable.exists(),'offline entry must prepare clean base wheel environment'
    script="""import asyncio,importlib.util,sys
import pacthold
assert 'pacthold.decision' not in sys.modules and importlib.util.find_spec('typesafe_sdk') is None
import pacthold.decision
from pacthold.decision.offline import run_offline
for alternate in (False,True):
 result=asyncio.run(run_offline(alternate=alternate));assert result.outcome.disposition=='ready'
assert 'site-packages' in pacthold.decision.__file__
print('base wheel standalone: default+alternate; SDK absent, decision opt-in')
"""
    result=subprocess.run([str(executable),'-I','-c',script],cwd=wheel.parent,text=True,capture_output=True)
    assert result.returncode==0,result.stdout+result.stderr
    # Core direction: outside the decision module itself, no kernel source
    # reaches into the optional decision framework or the Jev SDK.
    for p in (ROOT/'packages/backend/pacthold/src').rglob('*.py'):
        if str(p.relative_to(ROOT/'packages/backend/pacthold/src')).startswith('pacthold/decision/'):
            continue
        text=p.read_text()
        assert 'pacthold.decision' not in text and 'typesafe_sdk' not in text

def test_T64_fixed_baseline_regression_id_comparison():
    def results(path):
        assert path.exists(),'baseline receipt absent'
        out={}
        for t in ET.parse(path).findall('.//testcase'):
            cls=t.attrib['classname'];cls=cls[cls.index('tests.'):]
            key=cls+'::'+t.attrib['name']
            assert key not in out
            out[key]='failed' if t.find('failure') is not None or t.find('error') is not None else 'skipped' if t.find('skipped') is not None else 'passed'
        return out
    baseline=results(ROOT/'.decision-tmp/baseline-core.xml'); current=results(ROOT/'.decision-tmp/current-core.xml')
    assert len(baseline)==len(current)==57 and baseline==current
    assert set(current.values())=={'passed'}
