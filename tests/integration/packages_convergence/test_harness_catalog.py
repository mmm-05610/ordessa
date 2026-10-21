"""Allowlisted actual SDK factories, no imported unselected plugin or legacy owner."""
from importlib.metadata import EntryPoint
from pathlib import Path
import tomllib
import pytest
from ordessa_server.composition.packages_convergence import build_harness_catalog
from ordessa_agents.public import HarnessCatalog
from ordessa_agents.sdk import HarnessError

ROOT=Path(__file__).parents[3]


def points_and_bindings():
    points=[];bindings={}
    for path in sorted((ROOT/'plugins/harness').glob('*/pyproject.toml')):
        data=tomllib.loads(path.read_text())
        for name,value in data['project'].get('entry-points',{}).get('ordessa.harness_providers',{}).items():
            points.append(EntryPoint(name=name,value=value,group='ordessa.harness_providers'))
            bindings[name]={'definition_ref':{'environmentNamespace':'catalog-test','definitionId':name,'revision':'1'},'implementation_digest':'sha256:'+'a'*64}
    return tuple(points),bindings


def test_all_fifteen_actual_declared_factories_resolve_exact_pins_without_native_effects(monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess,'Popen',lambda *a,**k:(_ for _ in ()).throw(AssertionError('factory must not spawn')))
    points,bindings=points_and_bindings()
    assert len(points)==15
    catalog=build_harness_catalog(allowlist=tuple(bindings),bindings_by_provider=bindings,entry_points=points)
    assert type(catalog) is HarnessCatalog and len(catalog.descriptors())==15
    for binding in bindings.values():
        provider=catalog.resolve(binding['definition_ref'])
        assert dict(provider.descriptor.definition_ref)==binding['definition_ref']
    with pytest.raises(HarnessError,match='HARNESS_UNAVAILABLE'):
        catalog.resolve({'environmentNamespace':'catalog-test','definitionId':'unknown','revision':'1'})


def test_allowlist_duplicate_missing_and_unselected_import_fail_closed():
    points,bindings=points_and_bindings();point=next(p for p in points if p.name=='gemini-cli');binding=bindings[point.name]
    unselected=EntryPoint(name='do-not-import',value='missing_unselected_module:factory',group='ordessa.harness_providers')
    catalog=build_harness_catalog(allowlist=(point.name,),bindings_by_provider={point.name:binding},entry_points=(point,unselected))
    assert len(catalog.descriptors())==1
    with pytest.raises(HarnessError,match='HARNESS_ENTRYPOINT_CONFLICT'):
        build_harness_catalog(allowlist=(point.name,),bindings_by_provider={point.name:binding},entry_points=(point,point))
    with pytest.raises(HarnessError,match='HARNESS_UNAVAILABLE'):
        build_harness_catalog(allowlist=(point.name,),bindings_by_provider={point.name:binding},entry_points=())
    with pytest.raises(HarnessError,match='HARNESS_PIN_CONFLICT'):
        HarnessCatalog((catalog.resolve(binding['definition_ref']),)*2)
