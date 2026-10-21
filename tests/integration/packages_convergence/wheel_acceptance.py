"""Audit built wheel contents/metadata and import neutrality without installation."""
import argparse
import ast
import email
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

OWNERS={'ordessa_server','ordessa_environments','ordessa_environments_local',
        'ordessa_agents','ordessa_engineering','ordessa_units','plugins'}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--wheel-dir',required=True)
    parser.add_argument('--receipt')
    args=parser.parse_args()
    directory=Path(args.wheel_dir).resolve()
    wheels={}
    evidence=[]
    for distribution in ('ordessa_interfaces_contracts','ordessa_interfaces','ordessa_server'):
        found=list(directory.glob(distribution+'-[0-9]*.whl'))
        if not found and distribution=='ordessa_server':
            # The Server is not part of the lower CLI closure. Its absence is
            # reported, not silently treated as a pass: this audit then cannot
            # claim anything about the Server console entry.
            evidence.append({'distribution':'ordessa-server','status':'NOT_RUN',
                'reason':'wheel not present in the selected closure'})
            continue
        assert len(found)==1,(distribution,found)
        path=found[0];wheels[distribution]=str(path)
        with zipfile.ZipFile(path) as wheel:
            names=wheel.namelist()
            assert len(names)==len(set(names))
            assert not any(n.endswith(('.pyc','.so','.dll')) or '__pycache__/' in n for n in names)
            metadata=email.message_from_bytes(wheel.read(next(n for n in names if n.endswith('.dist-info/METADATA'))))
            entries=[n for n in names if n.endswith('.dist-info/entry_points.txt')]
            script=wheel.read(entries[0]).decode() if entries else ''
            requires=metadata.get_all('Requires-Dist',[])
            # The Server and interface distributions never own the `ordessa`
            # console; the single CLI distribution does (checked below when built).
            assert 'ordessa =' not in script
            for name in names:
                if not name.endswith('.py'):continue
                tree=ast.parse(wheel.read(name),filename=name)
                for node in ast.walk(tree):
                    imports=[]
                    if isinstance(node,ast.Import):imports=[a.name for a in node.names]
                    elif isinstance(node,ast.ImportFrom) and node.level==0 and node.module:imports=[node.module]
                    assert not any(i.split('.')[0] in OWNERS for i in imports),(name,imports)
                    if distribution=='ordessa_interfaces_contracts':
                        # Pinned third-party admission engine; no wider dependency.
                        allowed=sys.stdlib_module_names|{'__future__','jsonschema','referencing'}
                        assert all(i.split('.')[0] in allowed for i in imports),(name,imports)
                assert not any('/capability_host/' in n or n.endswith('/cli_generic.py') or n.endswith('/environments.py') for n in names)
            if distribution=='ordessa_interfaces_contracts':
                pinned={r.replace(' ','').split(';')[0] for r in requires}
                assert any(r.startswith('jsonschema') for r in pinned),(requires,)
                assert any(r.startswith('referencing==') for r in pinned),(requires,)
                assert not any(r.startswith(('ordessa-','pacthold')) for r in pinned),(requires,)
                # This distribution owns the contracts subpackage only; it must
                # not ship the host's own modules.
                foreign=[n for n in names if n.startswith('ordessa_interfaces/')
                         and not n.startswith('ordessa_interfaces/system_access/contracts/')]
                assert foreign==[],foreign
            if distribution=='ordessa_interfaces':
                assert any(r.replace(' ','').startswith('ordessa-interfaces-contracts==0.1.0') for r in requires)
                assert not any(n.startswith('ordessa_interfaces_contracts/') for n in names)
                for module in ('registry','discovery','operations','queries','projections','assembly'):
                    assert f'ordessa_interfaces/system_access/{module}.py' in names
            evidence.append({'distribution':metadata['Name'],'wheel':str(path),
                'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
                'requires':requires,'entryPoints':script,'files':len(names)})
    cli_wheels=list(directory.glob('ordessa_cli-[0-9]*.whl'))
    if cli_wheels:
        with zipfile.ZipFile(cli_wheels[0]) as wheel:
            names=wheel.namelist()
            entries=[n for n in names if n.endswith('.dist-info/entry_points.txt')]
            script=wheel.read(entries[0]).decode() if entries else ''
            assert 'ordessa = ordessa_cli.cli:main' in script
            evidence.append({'distribution':'ordessa-cli','wheel':str(cli_wheels[0]),
                'sha256':hashlib.sha256(cli_wheels[0].read_bytes()).hexdigest(),
                'entryPoints':script})
    contracts=wheels['ordessa_interfaces_contracts'];host=wheels['ordessa_interfaces']
    code='import sys,json;sys.path.insert(0,'+repr(contracts)+');import ordessa_interfaces_contracts as c;assert c.__file__.startswith('+repr(contracts)+');print(json.dumps({"contractsOrigin":c.__file__}))'
    pure=subprocess.run([sys.executable,'-I','-S','-c',code],capture_output=True,text=True,timeout=10)
    assert pure.returncode==0,pure.stderr
    code='''import sys,importlib.abc,json
sys.path[:0]=WHEELS
class BlockOwners(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname.split('.')[0] in OWNERS:raise RuntimeError('forbidden owner import: '+fullname)
sys.meta_path.insert(0,BlockOwners())
from ordessa_interfaces.system_access import CapabilityHost,build_registry
from ordessa_interfaces.channels.cli import run
from ordessa_interfaces.channels.mcp import tool_specs,call_tool
import ordessa_interfaces,ordessa_interfaces_contracts
assert ordessa_interfaces.__file__.startswith(WHEELS[0])
assert ordessa_interfaces_contracts.__file__.startswith(WHEELS[1])
print(json.dumps({'hostOrigin':ordessa_interfaces.__file__,'contractsOrigin':ordessa_interfaces_contracts.__file__}))
'''.replace('WHEELS',[host,contracts].__repr__()).replace('OWNERS',repr(OWNERS))
    neutral=subprocess.run([sys.executable,'-I','-c',code],capture_output=True,text=True,timeout=10)
    assert neutral.returncode==0,neutral.stderr
    receipt={'status':'PASS','wheels':evidence,'standardLibraryOnlyImport':json.loads(pure.stdout),
             'ownerBlockedWheelImport':json.loads(neutral.stdout),
             'scope':'metadata/content/import boundary; no full server dependency/runtime acceptance'}
    if args.receipt:Path(args.receipt).write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({'status':receipt['status'],'wheels':len(evidence),'pureContractsModuleImport':True,'hostOwnerBlocked':True}))


if __name__=='__main__':main()
