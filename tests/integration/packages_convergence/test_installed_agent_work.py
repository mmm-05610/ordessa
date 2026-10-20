"""Installed owner bytes through the real controlled Agent Work composition.

Only test helpers are loaded from the checkout. Product, SDK, Environment,
Engineering and harness implementations must come from freshly built wheels.
The controlled peer performs no model call and supplies no production authority.
"""
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]


def test_installed_product_and_agent_work_use_current_wheel_owners(tmp_path):
    from installed_server_fixture import build_installed_server
    python, console, env, packaging = build_installed_server(ROOT, tmp_path,
        extra_projects=('ordessa-server-product', 'ordessa-harness-gemini-cli'))
    assert {'ordessa-server-product','ordessa-harness-gemini-cli'} <= set(packaging['selectedProjects'])
    assert_installed_agent_work(tmp_path, python, env)


def assert_installed_agent_work(tmp_path, python, env):
    runner = tmp_path/'run_installed_agent_work.py'
    imports = tmp_path/'agent-work-imports.json'
    env['ORDESSA_IMPORT_RECEIPT'] = str(imports)
    env['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
    runner.write_text('''import json,sys
from pathlib import Path
root=Path('''+repr(str(ROOT))+''')
sys.path[:0]=[str(root),str(root/'tests/integration/packages_convergence'),
 str(root/'packages/engineering/tests/application')]
from ordessa_server.composition.product_selection import _resolve_product_composition
from ordessa_server_product.composition import ServerProductComposition
assert type(_resolve_product_composition()) is ServerProductComposition
import pytest
def main():
 return pytest.main(['-q','--noconftest','--import-mode=importlib','-o','pythonpath=',
 '-p','no:cacheprovider','--rootdir',str(root),
 '--basetemp','''+repr(str(tmp_path/'child-state'))+''',
 '''+repr('--junitxml='+str(tmp_path/'installed-agent-work.xml'))+''',
 str(root/'tests/integration/packages_convergence/test_root_agent_work_assembly.py')])
if __name__=='__main__': raise SystemExit(main())
''')
    compile(runner.read_text(), str(runner), 'exec')
    result = subprocess.run([str(python), '-I', str(runner)],cwd=tmp_path,env=env,
        capture_output=True,text=True,timeout=100)
    (tmp_path/'installed-agent-work-result.json').write_text(json.dumps({
        'args':result.args,'returncode':result.returncode,'stdout':result.stdout,'stderr':result.stderr},indent=2))
    assert result.returncode == 0, (result.stdout,result.stderr)
    origins=json.loads(imports.read_text())
    assert origins['errors']==[],origins
    for module in ('ordessa_server_product.composition',
                   'ordessa_server.composition.engineering_agent_work_assembly',
                   'ordessa_system_access_bindings.engineering',
                   'ordessa_engineering.adapters.native_records.agent_recorded_dispatch',
                   'ordessa_execution_agents.sdk.manager', 'ordessa_harness_gemini_cli'):
        assert module in origins['origins'],module
