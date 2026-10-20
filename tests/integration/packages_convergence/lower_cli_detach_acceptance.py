"""Real detach acceptance: detach, explicit exit observation, transport/Use release.

Detach is not cleanup: it releases the Agent association/transport while the
original process handle remains owned by the Environment. This script keeps
that distinction and performs the explicit stop, exit observation, process
transport release and Use release. It runs in a loopback-only network namespace
when available and sends no model prompt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


def _read(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def run(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--state', required=True)
    parser.add_argument('--receipt')
    parser.add_argument('--module', action='store_true')
    parser.add_argument('--no-namespace', action='store_true',
                        help='run on the current network namespace (unshare may be denied)')
    args = parser.parse_args(argv)
    state = Path(args.state).absolute()
    inputs = state / 'inputs'
    if state.exists():
        raise SystemExit('state must not exist for a fresh acceptance run')
    inputs.mkdir(parents=True, mode=0o700)
    os.chmod(state, 0o700)
    (inputs / 'roots.json').write_text(json.dumps(
        {'work': '.', 'home': 'home', 'config': 'config', 'data': 'data',
         'state': 'state', 'cache': 'cache', 'tmp': 'tmp'}))
    prefix = ([sys.executable, '-m', 'ordessa_agent_tools'] if args.module
              else [str(Path(sys.executable).parent / 'ordessa')])
    command = prefix + ['--state', str(state), 'session']
    isolated = False
    if not args.no_namespace and shutil.which('unshare') and shutil.which('ip'):
        command = ['unshare', '-rn', 'sh', '-c', 'ip link set lo up; exec ' + ' '.join(
            json.dumps(part) for part in command)]
        isolated = True
    # Admission is read when the session builds its harness catalog, so it must
    # exist before the process starts; writing it mid-session has no effect.
    (state / 'harness.json').write_text(json.dumps({'allowlist': ['kilo']}))
    stdout_path = inputs / 'session.stdout'
    stderr_path = inputs / 'session.stderr'
    stdout = stdout_path.open('w')
    stderr = stderr_path.open('w')
    proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=stdout,
                            stderr=stderr, text=True, cwd=str(state))
    cases = []

    def send(line, wait=1.0):
        proc.stdin.write(line + '\n')
        proc.stdin.flush()
        time.sleep(wait)

    try:
        send('environments create local --root ' + str(state / 'work') + ' --alias demo '
             '--request-id env-001 --json', 2)
        send('environments acquire demo true --request-id use-001 --json '
             '--save-result ' + str(inputs / 'use.json'), 2)
        send('environments export-endpoint --use-identity ' + str(inputs / 'use.json') +
             '#/data/useIdentity launcher observe communicate terminate detach files '
             '--roots ' + str(inputs / 'roots.json') + ' --request-id ep-001 --json '
             '--save-result ' + str(inputs / 'endpoint.json'), 2)
        send('agents harness list --json --save-result ' + str(inputs / 'harness.json'), 1)
        harnesses = (_read(inputs / 'harness.json') or {}).get('data', {}).get('harnesses', ())
        if not harnesses:
            raise RuntimeError('no installed harness provider')
        pin = next(item['definitionRef'] for item in harnesses
                   if item['definitionRef']['definitionId'] == 'kilo')
        (inputs / 'profile-manifest.json').write_text(json.dumps(
            {'schemaVersion': '1', 'harnessDefinitionRef': pin, 'declarations': []}))
        send('agents profiles create demo-profile --name Demo --manifest ' +
             str(inputs / 'profile-manifest.json') + ' --request-id prof-001 --json '
             '--save-result ' + str(inputs / 'profile.json'), 2)
        send('agents start --profile-ref ' + str(inputs / 'profile.json') +
             '#/data/currentManifestRef --endpoint-ref ' + str(inputs / 'endpoint.json') +
             '#/data/endpointRef --request-id start-001 --timeout 30 --json '
             '--save-result ' + str(inputs / 'start.json'), 25)
        started = _read(inputs / 'start.json')
        if not started or started.get('status') != 'completed':
            raise RuntimeError('agent start failed')
        send('agents detach --instance-ref ' + str(inputs / 'start.json') +
             '#/data/instanceRef --request-id detach-001 --timeout 30 --json '
             '--save-result ' + str(inputs / 'detach.json'), 2)
        detached = _read(inputs / 'detach.json')
        cases.append({'name': 'agent.detach.completed', 'status': 'PASS' if (
            detached and detached.get('status') == 'completed'
            and detached.get('data', {}).get('facts', {}).get('associationDetached') is True
            and detached.get('data', {}).get('facts', {}).get('exitClaimed') is False) else 'FAIL',
            'value': detached})
        send('agents stop --instance-ref ' + str(inputs / 'start.json') +
             '#/data/instanceRef --request-id stop-001 --timeout 30 --json '
             '--save-result ' + str(inputs / 'stop.json'), 2)
        cases.append({'name': 'agent.stop.after_detach', 'status': 'PASS'
                      if (_read(inputs / 'stop.json') or {}).get('status') == 'completed' else 'FAIL',
                      'value': _read(inputs / 'stop.json')})
        exited = None
        for attempt in range(6):
            send('agents reconcile --instance-ref ' + str(inputs / 'start.json') +
                 '#/data/instanceRef --request-id rec-00' + str(attempt) + ' --json', 4)
            for line in stdout_path.read_text().splitlines():
                try:
                    value = json.loads(line)
                except ValueError:
                    continue
                if value.get('requestId') == 'rec-00' + str(attempt):
                    exited = value
            if (exited or {}).get('data', {}).get('state') == 'exited':
                break
        cases.append({'name': 'agent.reconcile.after_detach', 'status': 'PASS' if (
            exited and exited.get('data', {}).get('state') == 'exited') else 'FAIL',
            'value': exited})
        send('environments process-release --endpoint-ref ' + str(inputs / 'start.json') +
             '#/data/processEndpointRef --request-id prel-001 --json '
             '--save-result ' + str(inputs / 'prelease.json'), 1)
        released_process = _read(inputs / 'prelease.json')
        cases.append({'name': 'process.release.after_detach', 'status': 'PASS' if (
            released_process and released_process.get('status') == 'completed'
            and released_process.get('data', {}).get('exitClaimed') is False) else 'FAIL',
            'value': released_process})
        send('environments release --use-identity ' + str(inputs / 'use.json') +
             '#/data/useIdentity --request-id rel-001 --json '
             '--save-result ' + str(inputs / 'release.json'), 1)
        released_use = _read(inputs / 'release.json')
        cases.append({'name': 'use.release.after_detach', 'status': 'PASS' if (
            released_use and released_use.get('status') == 'completed'
            and released_use.get('data', {}).get('resourcePreserved') is True) else 'FAIL',
            'value': released_use})
        send('exit', 1)
        try:
            code = proc.wait(timeout=45)
        except subprocess.TimeoutExpired:
            proc.kill()
            code = 'TIMEOUT'
        cases.append({'name': 'session.exit', 'status': 'PASS' if code == 0 else 'FAIL',
                      'exit': code})
    except Exception as error:
        cases.append({'name': 'detach-lifecycle', 'status': 'FAIL', 'error': repr(error)})
        try:
            proc.kill()
        except Exception:
            pass
    finally:
        stdout.close()
        stderr.close()
    failures = [case['name'] for case in cases if case['status'] != 'PASS']
    receipt = {
        'schemaVersion': 'lower-cli-detach-acceptance/1',
        'state': str(state), 'networkIsolated': isolated,
        'cases': cases, 'passed': len(cases) - len(failures), 'failed': len(failures),
        'failures': failures, 'stderrTail': stderr_path.read_text()[-2000:],
        'status': 'PASS' if not failures else 'FAIL',
    }
    if args.receipt:
        Path(args.receipt).write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'status': receipt['status'], 'passed': receipt['passed'],
                      'failed': receipt['failed'], 'failures': failures,
                      'networkIsolated': isolated}))
    return 0 if not failures else 1


if __name__ == '__main__':
    raise SystemExit(run())
