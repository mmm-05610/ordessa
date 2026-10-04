"""Install released wheel and exercise its executable against an owned Server.

No pytest helper imports, model calls or global Agent configuration changes.
Runtime secrets and databases exist only in an ignored temporary directory.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[3]
PRODUCT = ROOT / 'products/agent-tools'
BUNDLE = PRODUCT / 'dist/bundle-0.1.0a2-init'
EVIDENCE = ROOT / "docs/implementation/agent-tools/evidence"
records = []
SERVER_SCRIPT = r'''
import json, socket, sys, threading
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from deployment import AgentServiceConfiguration, build_agent_runtime
from ordessa_persistence_sqlite import ProtectedFingerprintHmac
from ordessa_server.transport.http.app import create_app
import uvicorn
key = bytes.fromhex(sys.stdin.readline().strip())
root, ready = Path(sys.argv[2]), Path(sys.argv[3])
runtime = build_agent_runtime(AgentServiceConfiguration(root), fingerprint_port=ProtectedFingerprintHmac({'owned-check': key}, active_key_id='owned-check'))
sock = socket.socket()
sock.bind(('127.0.0.1', 0))
sock.listen(128)
def on_bound():
    ready.write_text(json.dumps({'port': sock.getsockname()[1], 'environment': runtime.core_binding.environment.environment_id}))
server = uvicorn.Server(uvicorn.Config(create_app(runtime, on_bound=on_bound), log_level='error'))
def stop():
    if sys.stdin.readline().strip() == 'stop':
        server.should_exit = True
threading.Thread(target=stop, daemon=True).start()
server.run(sockets=[sock])
'''


def command(label, argv, cwd, env=None, expected=0):
    completed = subprocess.run([str(x) for x in argv], cwd=cwd, env=env, capture_output=True, text=True, timeout=60)
    if env and env.get('AT_INSTALL_USE_TOKEN'):
        assert env['AT_INSTALL_USE_TOKEN'] not in completed.stdout + completed.stderr
    records.append({'label': label, 'argv': [str(x) for x in argv], 'exit': completed.returncode,
                    'stdout': completed.stdout, 'stderr': completed.stderr})
    if completed.returncode != expected:
        raise RuntimeError(f'{label}: expected {expected}, got {completed.returncode}')
    return completed


def exercise():
    for line in (BUNDLE / 'SHA256SUMS').read_text().splitlines():
        digest, name = line.split('  ', 1)
        assert hashlib.sha256((BUNDLE / name).read_bytes()).hexdigest() == digest
    with tempfile.TemporaryDirectory(prefix='installed-cli-check-', dir=PRODUCT / 'dist') as tmp:
        workspace = Path(tmp)
        venv = workspace / 'client-venv'
        command('create-fresh-client-venv', [sys.executable, '-m', 'venv', venv], workspace)
        python = venv / 'bin/python'
        cli = venv / 'bin/ordessa-agent'
        wheel = next((BUNDLE / 'cli').glob('*.whl'))
        command('install-local-wheel', [python, '-m', 'pip', 'install', '--no-index', '--no-deps', wheel], workspace)
        command('backend-packages-absent', [python, '-c',
            "import importlib.util; names=('pacthold','ordessa_server','ordessa_harness'); assert all(importlib.util.find_spec(n) is None for n in names); print('backend packages absent')"], workspace)
        command('installed-help', [cli, '--help'], workspace)
        initialized = command('installed-local-init', [cli, 'init', '--json'], workspace)
        observations = json.loads(initialized.stdout)
        assert observations['evidence']['executedBinaries'] is False
        assert all(x['runtimeReady'] == 'unknown' for x in observations['data']['harnesses'])
        caller_skills = workspace / 'caller-project/skills'
        shutil.copytree(BUNDLE / 'skills', caller_skills)
        assert len(list(caller_skills.glob('*/SKILL.md'))) == 3
        config, ready = workspace / 'services.json', workspace / 'ready.json'
        server_root = workspace / 'isolated-server'
        process = None
        log = (workspace / 'server.log').open('wb')

        def start():
            nonlocal process
            ready.unlink(missing_ok=True)
            process = subprocess.Popen([sys.executable, '-c', SERVER_SCRIPT, str(PRODUCT), str(server_root), str(ready)],
                                       cwd=workspace, stdin=subprocess.PIPE, stdout=log, stderr=log)
            process.stdin.write(key.hex().encode() + b'\n')
            process.stdin.flush()
            deadline = time.monotonic() + 15
            while not ready.exists():
                if process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError('owned server failed readiness')
                time.sleep(0.05)
            facts = json.loads(ready.read_text())
            config.write_text(json.dumps({'services': {'check': {'endpoint': f"http://127.0.0.1:{facts['port']}", 'tokenEnv': 'AT_INSTALL_USE_TOKEN'}}}))
            config.chmod(0o600)
            env = os.environ.copy()
            env['AT_INSTALL_USE_TOKEN'] = (server_root / 'secrets/http-token').read_text().strip()
            return facts, env

        def stop():
            nonlocal process
            if process is not None:
                if process.poll() is None:
                    process.stdin.write(b'stop\n')
                    process.stdin.flush()
                    process.wait(timeout=10)
                records.append({'label': 'owned-server-stop', 'exit': process.returncode})
                assert process.returncode == 0
                process.stdin.close()
                process = None

        key = os.urandom(32)
        try:
            facts, env = start()
            namespace = facts['environment']
            def run(label, args, expected=0, chosen_env=None):
                result = command(label, [cli, *args, '--config', config, '--service', 'check', '--json'],
                                 workspace, chosen_env or env, expected)
                return json.loads(result.stdout)
            doctor = run('doctor-installed-wheel', ['doctor'])
            assert doctor['data']['coreAgent']['supports']['nodes'] is False
            assert doctor['data']['coreAgent']['supports']['managedInput'] is False
            run('capabilities', ['capabilities'])
            assert run('empty-catalog', ['profiles', 'list'])['data']['entries'] == []
            denied_env = dict(env, AT_INSTALL_USE_TOKEN='deliberately-invalid-owned-check-token')
            run('auth-refusal', ['profiles', 'list'], 3, denied_env)
            manifest = workspace / 'manifest.json'
            original = {'harnessDefinitionRef': {'environmentNamespace': namespace, 'definitionId': 'deliberately-absent-catalog-check', 'revision': '1'},
                        'schemaVersion': '1', 'declarations': [], 'metadata': {'purpose': 'catalog-only; no runnable harness'}}
            manifest.write_text(json.dumps(original))
            create = ['profiles', 'create', '--profile-id', 'install-check', '--name', 'Installed CLI check', '--file', str(manifest), '--request-id', 'install-create']
            first = run('create-catalog-only-profile', create)['data']
            assert run('confirmed-request-replay', create)['data'] == first
            old_ref = workspace / 'old-ref.json'
            old_ref.write_text(json.dumps(first['currentManifestRef']))
            assert run('read-original', ['profiles', 'show', '@' + str(old_ref)])['data']['content'] == original
            changed = dict(original, metadata={'purpose': 'edited catalog-only check'})
            manifest.write_text(json.dumps(changed))
            edit = ['profiles', 'edit', 'install-check', '--file', str(manifest), '--expected-catalog-revision', '1', '--base-manifest', '@' + str(old_ref), '--request-id', 'install-edit']
            second = run('edit-double-cas', edit)['data']
            stale = edit.copy(); stale[stale.index('install-edit')] = 'install-stale'
            run('stale-revision-refusal', stale, 5)
            assert run('historical-ref-after-edit', ['profiles', 'show', '@' + str(old_ref)])['data']['content'] == original
            run('clone-historical-profile', ['profiles', 'clone', '@' + str(old_ref), '--profile-id', 'cloned-check', '--name', 'Historical clone', '--request-id', 'install-clone'])
            run('archive-profile', ['profiles', 'archive', 'install-check', '--expected-catalog-revision', '2', '--request-id', 'install-archive'])
            run('restore-profile', ['profiles', 'restore', 'install-check', '--expected-catalog-revision', '3', '--request-id', 'install-restore'])
            current_ref = workspace / 'current-ref.json'; current_ref.write_text(json.dumps(second['currentManifestRef']))
            preview = run('missing-real-provider-preview', ['profiles', 'preview', '@' + str(current_ref)], 4)
            assert preview['data']['ready'] is False
            command('node-command-not-implemented', [cli, 'nodes', 'list'], workspace, env, 2)
            command('task-command-not-implemented', [cli, 'run', 'hello'], workspace, env, 2)
            stop()
            run('offline-doctor', ['doctor'], 4)
            resumed_facts, env = start()
            assert resumed_facts['environment'] == namespace
            assert run('restart-historical-read', ['profiles', 'show', '@' + str(old_ref)])['data']['content'] == original
            assert run('restart-original-edit-replay', edit)['data'] == second
            run('final-catalog', ['profiles', 'list'])
        finally:
            try:
                stop()
            finally:
                log.close()
                if process is not None and process.poll() is None:
                    # Only the child spawned by this exercise; never a user service.
                    process.terminate()
                    process.wait(timeout=5)
        result = {'exit': 0, 'bundle': str(BUNDLE), 'installed_entrypoint': 'fresh venv bin/ordessa-agent',
                  'records': records, 'temporary_runtime_removed': True, 'real_model_calls': 0,
                  'limitations': ['Profile references deliberately absent: catalog-only check', 'nodes/run unavailable',
                                  'Skill files copied locally; no separate model-agent behavioral evaluation',
                                  'no public per-request Profile outcome query']}
    (EVIDENCE / 'install-use-exercise.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'exit': 0, 'commands': len(records), 'real_model_calls': 0, 'runtime_cleaned': True}))


if __name__ == '__main__':
    try:
        exercise()
    except Exception as exc:
        (EVIDENCE / 'install-use-exercise-failed.json').write_text(json.dumps({'errorType': type(exc).__name__, 'records': records}, indent=2) + '\n')
        raise
