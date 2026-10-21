"""Private installed-entry acceptance; local wheels plus existing third-party files.

This does not resolve a complete product dependency set. pip check is retained
separately, including existing metadata conflicts and unavailable externals.
No existing environment, source tree, service, or user state is modified.
"""
from hashlib import sha256
import importlib.metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tomllib
import zipfile


def _run(args, *, cwd, env, timeout=30):
    result = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    assert result.returncode == 0, (args, result.stdout, result.stderr)
    return result


def build_installed_server(root, temporary, *, extra_projects=()):
    """Build all recursive local Server requirements from this exact checkout."""
    temporary = Path(temporary)
    wheels = temporary/'wheels'; wheels.mkdir()
    env = dict(os.environ)
    for key in ('PYTHONPATH','PYTHONHOME','PYTHONUSERBASE','PYTEST_ADDOPTS','PYTEST_PLUGINS'):
        env.pop(key, None)
    env.update(PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1', PIP_NO_INDEX='1', PIP_DISABLE_PIP_VERSION_CHECK='1')
    projects = json.loads((root/'python-workspace.json').read_text())['projects']
    local = {item['distribution']:item for item in projects}
    assert type(extra_projects) is tuple and all(type(name) is str and name in local for name in extra_projects)
    selected = set(); pending = ['ordessa-server', *extra_projects]
    while pending:
        name = pending.pop()
        if name in selected:
            continue
        selected.add(name)
        metadata = tomllib.loads((root/local[name]['path']/'pyproject.toml').read_text())
        assert metadata['build-system']['build-backend'] == 'setuptools.build_meta'
        for dependency in metadata['project'].get('dependencies', ()):
            name = re.split(r'[<>=!;\[ ]', dependency, maxsplit=1)[0]
            if name in local:
                pending.append(name)
    # Use the running interpreter's actual external backend. -I -S avoids .pth
    # editable/source paths, and the explicit backend directory is third-party.
    import setuptools
    backend_site = Path(setuptools.__file__).resolve().parent.parent
    builds = []
    for name in sorted(selected):
        # Build IN PLACE: a distribution may own package roots in sibling trees
        # (one distribution, several plugin packages), so copying just this
        # project to a staging directory would break its package-dir mapping.
        # The build base is redirected out of the checkout so no build/ tree is
        # left behind; *.egg-info is already ignored.
        source = root/local[name]['path']
        # Stale in-source artifacts (from an earlier in-place build) would be
        # copied into the wheel as if they were current packages; remove them.
        for artifact in (source/'build', source/'dist'):
            if artifact.exists():
                shutil.rmtree(artifact)
        for egg in list(source.glob('*.egg-info')) + list((source/'src').glob('*.egg-info')):
            shutil.rmtree(egg)
        build_base = temporary/'build'/name
        code = ('import sys;sys.path.insert(0,'+repr(str(backend_site))+');'
                'import setuptools.build_meta as backend;backend.build_wheel('
                +repr(str(wheels))+','+repr({'--build-base':str(build_base)})+')')
        result = _run([sys.executable,'-I','-S','-c',code], cwd=source, env=env)
        builds.append({'distribution':name,'source':str(source),'stdout':result.stdout,'stderr':result.stderr})
    venv = temporary/'venv'
    _run([sys.executable,'-I','-m','venv',str(venv)], cwd=temporary, env=env)
    python = venv/'bin/python'
    site = Path(_run([str(python),'-I','-c','import sysconfig;print(sysconfig.get_path("purelib"))'],cwd=temporary,env=env).stdout.strip())
    # Expose only external distribution RECORD files. No .pth file, editable
    # loader, local owner metadata or shared source search path enters this venv.
    external = []
    forbidden = {re.sub(r'[-_.]+','-',n).lower() for n in local} | {'pacthold','ordessa-harness-api'}
    for distribution in importlib.metadata.distributions(path=[str(backend_site)]):
        name = re.sub(r'[-_.]+','-',distribution.metadata['Name']).lower()
        if name in forbidden or name.startswith('ordessa-') or name in ('decision-runtime','pip'):
            continue
        linked = 0
        for item in distribution.files or ():
            relative = Path(str(item))
            if relative.is_absolute() or '..' in relative.parts or relative.suffix in ('.pth','.pyc'):
                continue
            source = Path(distribution.locate_file(item)).resolve()
            if not source.is_file() or not source.is_relative_to(backend_site):
                continue
            target = site/relative
            if target.exists():
                continue
            target.parent.mkdir(parents=True,exist_ok=True)
            target.symlink_to(source); linked += 1
        external.append({'name':name,'version':distribution.version,'linkedFiles':linked})
    wheel_files = sorted(wheels.glob('*.whl'))
    install = _run([str(python),'-I','-m','pip','install','--no-index','--no-deps',*[str(p) for p in wheel_files]],cwd=temporary,env=env)
    expected = {}; receipts = []; duplicates = []
    for wheel in wheel_files:
        with zipfile.ZipFile(wheel) as archive:
            members = archive.namelist()
            for name in members:
                if '.dist-info/' not in name and not name.endswith('/'):
                    digest = sha256(archive.read(name)).hexdigest()
                    if name in expected:
                        assert expected[name] == digest, ('conflicting local wheel bytes',name)
                        duplicates.append({'member':name,'wheel':wheel.name,'sha256':digest})
                    expected[name] = digest
        receipts.append({'path':str(wheel),'sha256':sha256(wheel.read_bytes()).hexdigest()})
    # Separate artifact owners must not ship the same member, even equal bytes.
    host_wheel = next(w for w in wheel_files if w.name.startswith('ordessa_interfaces-'))
    contracts_wheel = next(w for w in wheel_files if w.name.startswith('ordessa_interfaces_contracts-'))
    with zipfile.ZipFile(host_wheel) as host, zipfile.ZipFile(contracts_wheel) as contracts:
        assert not set(host.namelist()) & set(contracts.namelist())
        # The `ordessa_interfaces.system_access.contracts` subpackage belongs to
        # the interfaces distribution: a distribution may add subpackages to a
        # package it owns, but it must not ship a second copy of a parent package.
        contract_source = root/'packages/interfaces/system-access/src/ordessa_interfaces/system_access/contracts'
        preserved = list(contract_source.glob('*.py')) + list((contract_source/'schemas').glob('*.json'))
        assert len(list((contract_source/'schemas').glob('*.json'))) == 7
        for source in preserved:
            member = 'ordessa_interfaces/system_access/contracts/'+source.relative_to(contract_source).as_posix()
            assert host.read(member) == source.read_bytes()
            assert member not in contracts.namelist()
    (site/'installed_owner_manifest.json').write_text(json.dumps(expected))
    # Audit each actual entry process at exit; never replace its main() call.
    (site/'sitecustomize.py').write_text('''import atexit,hashlib,json,os,pathlib,sys
_site=pathlib.Path(__file__).parent
_expected=json.loads((_site/'installed_owner_manifest.json').read_text())
_owners={name.split('/')[0] for name in _expected if name.endswith('.py')}
def _audit():
 path=os.environ.get('ORDESSA_IMPORT_RECEIPT')
 if not path:return
 origins={};errors=[]
 for name,module in list(sys.modules.items()):
  if name=='__main__':name=getattr(getattr(module,'__spec__',None),'name',name)
  if not (name.split('.')[0] in _owners or name.startswith(('ordessa_','ordessa_decision'))):continue
  raw=getattr(module,'__file__',None)
  if raw is None:continue
  file=pathlib.Path(raw)
  try:relative=str(file.relative_to(_site))
  except ValueError:errors.append([name,raw,'outside installed venv']);continue
  digest=hashlib.sha256(file.read_bytes()).hexdigest()
  origins[name]={'path':raw,'sha256':digest}
  if file.is_symlink() or _expected.get(relative)!=digest:errors.append([name,raw,'not current wheel bytes'])
 if 'pacthold' in sys.modules:errors.append(['pacthold','retired kernel loaded'])
 if 'pydantic_graph' in sys.modules:errors.append(['pydantic_graph','retired graph loaded'])
 pathlib.Path(path).write_text(json.dumps({'origins':origins,'errors':errors,'sysPath':sys.path},indent=2))
atexit.register(_audit)
''')
    check = subprocess.run([str(python),'-I','-m','pip','check'],cwd=temporary,env=env,capture_output=True,text=True,timeout=30)
    receipt = {'selectedProjects': sorted(selected), 'identicalDuplicateWheelMembers':duplicates,'localWheels':receipts,'builds':builds,'existingThirdParty':external,
        'install':{'stdout':install.stdout,'stderr':install.stderr},
        'pipCheck':{'returncode':check.returncode,'stdout':check.stdout,'stderr':check.stderr},
        'qualification':'Current local wheels installed --no-index --no-deps; existing external files shared by RECORD only. Not full product pip closure.'}
    (temporary/'packaging-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    return python, venv/'bin/ordessa', env, receipt
