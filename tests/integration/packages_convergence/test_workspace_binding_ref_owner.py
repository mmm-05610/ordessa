"""Workspace owns current binding facts; original serialized identity stays exact."""
import ast,runpy,re
from dataclasses import dataclass
from pathlib import Path
import pytest
from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_workspace.public import DirectoryBindingRef


def historical_type():
    admission=runpy.run_path('packages/execution/units/src/ordessa_units/definitions/admission_identity.py')['AdmissionNamespace']
    tree=ast.parse(Path('packages/execution/units/src/ordessa_units/bindings/contracts.py').read_text())
    node=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='DirectoryBindingRef')
    scope={'__name__':'historical_binding_fixture','dataclass':dataclass,'re':re,'AdmissionNamespace':admission}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'historical_binding_fixture','exec'),scope)
    return scope['DirectoryBindingRef']


@pytest.mark.parametrize('namespace,binding,revision,digest',[
    ('same-namespace','dir-one',1,'sha256:'+'a'*64),
    ('a'*64,'b'*64,20,'sha256:'+'0'*64)])
def test_original_binding_bytes_roundtrip_and_no_authority(namespace,binding,revision,digest):
    old=historical_type()(namespace,binding,revision,digest)
    current=DirectoryBindingRef(namespace,binding,revision,digest)
    assert canonical_bytes(old.to_dict())==canonical_bytes(current.to_dict())
    assert DirectoryBindingRef.from_dict(old.to_dict())==current
    assert type(current).__module__=='ordessa_workspace.directory_binding'
    assert not hasattr(current,'grant') and not hasattr(current,'invocation')
    with pytest.raises(ValueError):DirectoryBindingRef.from_dict({**current.to_dict(),'grant':'not-authority'})


@pytest.mark.parametrize('field,value',[('environment_namespace','Upper'),('environment_namespace','x'*65),
    ('binding_id','Upper'),('binding_id','x'*65),('binding_revision',0),('binding_revision',True),
    ('content_digest','sha256:'+'A'*64),('content_digest','not-a-digest')])
def test_original_invalid_identity_invariants_preserved(field,value):
    args=dict(environment_namespace='namespace',binding_id='dir-one',binding_revision=1,content_digest='sha256:'+'a'*64)
    args[field]=value
    for constructor in (historical_type(),DirectoryBindingRef):
        with pytest.raises(ValueError):constructor(**args)
