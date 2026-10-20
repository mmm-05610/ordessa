"""Exercise real fixture validator against escaping and stale repository bindings."""
from pathlib import Path
import json
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('defect,reason', [
    ('parent', 'Escaping repository path'),
    ('absolute', 'Escaping repository path'),
    ('missing', 'Missing repository file'),
    ('symlink', 'Repository path escapes repository'),
    ('modified', 'Fixture lock mismatch'),
])
def test_repository_script_lock_refuses_actual_invalid_binding(tmp_path, defect, reason):
    repo = tmp_path / 'repo'
    resources = repo / 'methods/incremental-engineering'
    shutil.copytree(ROOT / 'methods/incremental-engineering', resources)
    scripts = repo / 'tooling/checks/method-fixture'
    scripts.mkdir(parents=True)
    for name in ['build_fixture.py', 'validate_fixture.py']:
        shutil.copy2(ROOT / 'tooling/checks/method-fixture' / name, scripts / name)
    lock_path = resources / 'fixture-lock.json'
    lock = json.loads(lock_path.read_text())
    entry = next(item for item in lock['files'] if item['path'] == 'build_fixture.py')
    external = tmp_path / 'external.py'
    external.write_text('# controlled outside candidate\n')
    if defect == 'parent':
        entry['repository_path'] = '../external.py'
    elif defect == 'absolute':
        entry['repository_path'] = str(external)
    elif defect == 'missing':
        entry['repository_path'] = 'tooling/checks/method-fixture/absent.py'
    elif defect == 'symlink':
        (scripts / 'build_fixture.py').unlink()
        (scripts / 'build_fixture.py').symlink_to(external)
    else:
        with (scripts / 'build_fixture.py').open('a') as stream:
            stream.write('\n# controlled changed source\n')
    lock_path.write_text(json.dumps(lock))
    before = {str(p.relative_to(resources)): p.read_bytes()
              for p in resources.rglob('*') if p.is_file()}
    result = subprocess.run([sys.executable, str(scripts / 'validate_fixture.py')],
                            cwd=repo, capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    assert reason in result.stdout + result.stderr
    assert {str(p.relative_to(resources)): p.read_bytes()
            for p in resources.rglob('*') if p.is_file()} == before
    assert external.read_text() == '# controlled outside candidate\n'
