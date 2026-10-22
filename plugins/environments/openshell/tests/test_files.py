"""The sandbox file helper itself: the file mode is a real effect, not a claim.

The helper program in ``files.py`` is the code that runs inside the sandbox.
This executes that exact program locally against a temporary directory, so the
mode it applies is observed instead of assumed. The controlled peer in
``test_rpc.py`` covers the transport; this covers the helper's own behaviour.
"""
import json
import subprocess
import sys

import pytest

from ordessa_environments_openshell import files


def run_helper(root, args):
    """Run the plugin's own helper program with one bounded request."""
    argv = json.dumps({**args, 'root': str(root)})
    completed = subprocess.run([sys.executable, '-c', files._SCRIPT, argv],
                               capture_output=True, text=True)
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


@pytest.mark.parametrize('mode', [0o600, 0o644])
def test_atomic_helper_applies_the_requested_mode(tmp_path, mode):
    root = tmp_path / 'area'
    root.mkdir()
    run_helper(root, {'op': 'write_atomic', 'relative': 'credential.json',
                      'content': '{}', 'mode': mode})
    target = root / 'credential.json'
    assert target.read_text(encoding='utf-8') == '{}'
    assert target.stat().st_mode & 0o777 == mode


def test_atomic_helper_replaces_the_target_and_leaves_no_temporary(tmp_path):
    root = tmp_path / 'area'
    root.mkdir()
    run_helper(root, {'op': 'write_atomic', 'relative': 'credential.json',
                      'content': 'first', 'mode': 0o600})
    run_helper(root, {'op': 'write_atomic', 'relative': 'credential.json',
                      'content': 'second', 'mode': 0o600})
    target = root / 'credential.json'
    assert target.read_text(encoding='utf-8') == 'second'
    assert sorted(entry.name for entry in root.iterdir()) == ['credential.json']


def test_atomic_helper_creates_the_missing_parent_directory(tmp_path):
    root = tmp_path / 'area'
    root.mkdir()
    run_helper(root, {'op': 'write_atomic', 'relative': 'nested/dir/credential.json',
                      'content': '{}', 'mode': 0o600})
    target = root / 'nested' / 'dir' / 'credential.json'
    assert target.read_text(encoding='utf-8') == '{}'
    assert target.stat().st_mode & 0o777 == 0o600


def test_atomic_helper_refuses_a_path_outside_the_area(tmp_path):
    root = tmp_path / 'area'
    root.mkdir()
    completed = subprocess.run(
        [sys.executable, '-c', files._SCRIPT,
         json.dumps({'op': 'write_atomic', 'root': str(root), 'relative': '../escape.json',
                     'content': '{}', 'mode': 0o600})],
        capture_output=True, text=True)
    assert completed.returncode != 0
    assert not (tmp_path / 'escape.json').exists()
