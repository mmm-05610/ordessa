"""Pure startup routing; no discovery, credentials or process creation."""
import hashlib
from pathlib import Path
import pytest
from ordessa_harness_pi import PiAcpHarnessPreparation, PiChannelRefused

def preparation(tmp_path, **kwargs):
    executable=tmp_path/'reviewed-bridge'
    executable.write_text('#!/bin/sh\nexit 0\n')
    executable.chmod(0o700)
    return PiAcpHarnessPreparation(bridge_executable=str(executable),
        bridge_sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),pi_executable=str(executable),**kwargs)

def test_explicit_provider_model_is_transported_verbatim(tmp_path):
    owner=preparation(tmp_path,provider='approved-provider',model='exact-model')
    roots={key:str(tmp_path/key) for key in ('cwd','home','profile','tmp')}
    for path in roots.values():
        Path(path).mkdir()
    first=owner.prepare(roots);second=owner.prepare(roots)
    assert first.launch_spec == second.launch_spec
    assert first.launch_spec.argv[-4:]==('--pi-provider','approved-provider','--pi-model','exact-model')
    assert first.launch_spec.env['PI_CODING_AGENT_DIR'] == roots['profile']
    assert first.launch_spec.env['TMPDIR'] == roots['tmp']
    assert first.resources.location == roots['profile']
    assert first.session.location == roots['cwd']
    assert not list(Path(roots['profile']).iterdir())

def test_preparation_requires_exact_four_unit_roots(tmp_path):
    owner=preparation(tmp_path)
    old_roots={key:str(tmp_path/key) for key in ('cwd','home','piHome')}
    with pytest.raises(PiChannelRefused):
        owner.prepare(old_roots)
    roots={key:str(tmp_path/key) for key in ('cwd','home','profile','tmp')}
    roots['piHome']=str(tmp_path/'legacy')
    with pytest.raises(PiChannelRefused):
        owner.prepare(roots)

@pytest.mark.parametrize('mutation', ['duplicate','different-parent','traversal','symlink'])
def test_preparation_rejects_non_private_or_noncanonical_roots(tmp_path, mutation):
    owner=preparation(tmp_path)
    roots={key:str(tmp_path/'unit'/key) for key in ('cwd','home','profile','tmp')}
    if mutation == 'duplicate':
        roots['tmp']=roots['profile']
    elif mutation == 'different-parent':
        roots['tmp']=str(tmp_path/'other'/'tmp')
    elif mutation == 'traversal':
        roots['tmp']=str(tmp_path/'unit'/'nested'/'..'/'tmp')
    else:
        target=tmp_path/'unit'/'real-profile'
        alias=tmp_path/'unit'/'profile'
        target.mkdir(parents=True)
        alias.symlink_to(target, target_is_directory=True)
        roots['profile']=str(alias)
    with pytest.raises(PiChannelRefused):
        owner.prepare(roots)

@pytest.mark.parametrize('kwargs',[{'provider':'p'}, {'model':'m'}, {'provider':'p/q','model':'m'},
    {'provider':'p','model':' m'}, {'provider':'p','model':'m\n'}, {'provider':'p','model':False}])
def test_incomplete_or_invalid_routing_refuses_before_prepare(tmp_path,kwargs):
    with pytest.raises(PiChannelRefused):preparation(tmp_path,**kwargs)
