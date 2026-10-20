"""Real foreground lifecycle acceptance for the single `ordessa` CLI.

The script drives one session process: create/acquire/export, Profile, Agent
start/get/reconcile/stop, process transport release and Use release, then a
clean exit. It uses the installed console (or ``-m ordessa_agent_tools``) and a
real Harness brand from the installed catalog. When available, the whole
session runs in a network namespace with only loopback up, so the native
handshake can be shown without external network access.

No model prompt is sent. Missing brand, unavailable runtime or a failed
handshake is reported as BLOCKED/failure with the observed stderr, never as a
pass.
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
import tempfile
import time


def _command(executable, state, *, module):
    prefix = ([sys.executable, '-m', 'ordessa_agent_tools'] if module
              else [str(Path(executable).parent / 'ordessa')])
    return prefix + ['--state', str(state), 'session']


def _maybe_namespace(command, enabled=True):
    if not enabled or shutil.which('unshare') is None or shutil.which('ip') is None:
        return command, False
    return (['unshare', '-rn', 'sh', '-c', 'ip link set lo up; exec ' + ' '.join(
        json.dumps(part) for part in command)]), True


class Blocked(RuntimeError):
    """A required external resource (brand/runtime/authorization) is absent."""


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
    parser.add_argument('--harness', default=None,
                        help='definitionId of an installed harness (default: first)')
    args = parser.parse_args(argv)
    state = Path(args.state).absolute()
    work = state / 'work'
    inputs = state / 'inputs'
    if state.exists():
        raise SystemExit('state must not exist for a fresh acceptance run')
    inputs.mkdir(parents=True, mode=0o700)
    os.chmod(state, 0o700)
    (inputs / 'roots.json').write_text(json.dumps(
        {'work': '.', 'home': 'home', 'config': 'config', 'data': 'data',
         'state': 'state', 'cache': 'cache', 'tmp': 'tmp'}))
    command, isolated = _maybe_namespace(_command(sys.executable, state, module=args.module),
                                        enabled=not args.no_namespace)
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
    pin = None

    def send(line, wait=1.0):
        proc.stdin.write(line + '\n')
        proc.stdin.flush()
        time.sleep(wait)

    def record(name, path, expected):
        value = _read(path)
        okay = value is not None and value.get('status') == expected
        cases.append({'name': name, 'path': str(path), 'expected': expected,
                      'status': 'PASS' if okay else 'FAIL',
                      'value': value})
        return value

    try:
        send('environments create local --root ' + str(work) + ' --alias demo '
             '--request-id env-001 --json', 1)
        send('environments acquire demo true --request-id use-001 --json '
             '--save-result ' + str(inputs / 'use.json'), 1)
        use = _read(inputs / 'use.json')
        if use is None or use.get('status') != 'completed':
            raise RuntimeError('Use acquisition failed: ' + repr(_read(inputs / 'use.json')))
        send('environments export-endpoint --use-identity ' + str(inputs / 'use.json') +
             '#/data/useIdentity launcher observe communicate terminate detach files '
             '--roots ' + str(inputs / 'roots.json') + ' --request-id ep-001 --json '
             '--save-result ' + str(inputs / 'endpoint.json'), 1)
        send('agents harness list --json --save-result ' + str(inputs / 'harness.json'), 1)
        harnesses = (_read(inputs / 'harness.json') or {}).get('data', {}).get('harnesses', ())
        if not harnesses:
            raise Blocked('no installed harness provider')
        selected = next((item for item in harnesses
                         if args.harness in (None, item['definitionRef']['definitionId'])), None)
        if selected is None:
            raise Blocked('requested harness is not installed: ' + str(args.harness))
        pin = selected['definitionRef']
        (inputs / 'profile-manifest.json').write_text(json.dumps(
            {'schemaVersion': '1', 'harnessDefinitionRef': pin, 'declarations': []}))
        send('agents profiles create demo-profile --name Demo --manifest ' +
             str(inputs / 'profile-manifest.json') + ' --request-id prof-001 --json '
             '--save-result ' + str(inputs / 'profile.json'), 1)
        record('profile.create', inputs / 'profile.json', 'completed')
        send('agents start --profile-ref ' + str(inputs / 'profile.json') +
             '#/data/currentManifestRef --endpoint-ref ' + str(inputs / 'endpoint.json') +
             '#/data/endpointRef --request-id start-001 --timeout 30 --json '
             '--save-result ' + str(inputs / 'start.json'), 20)
        started = record('agent.start', inputs / 'start.json', 'completed')
        if started:
            receipt = started.get('data') or {}
            cases.append({'name': 'agent.start.running', 'status': 'PASS'
                          if receipt.get('state') == 'running'
                          and receipt.get('instanceRef') and receipt.get('sessionId')
                          and receipt.get('processEndpointRef') else 'FAIL'})
        send('agents get --start-request-id start-001 --json '
             '--save-result ' + str(inputs / 'get.json'), 1)
        record('agent.get', inputs / 'get.json', 'completed')
        # ACP session/cancel is a notification: accepted means the frame was
        # written, not that the provider already cancelled anything.
        send('agents cancel --instance-ref ' + str(inputs / 'start.json') +
             '#/data/instanceRef --request-id cancel-001 --timeout 30 --json '
             '--save-result ' + str(inputs / 'cancel.json'), 1)
        cancelled = _read(inputs / 'cancel.json')
        accepted = bool(cancelled and cancelled.get('status') == 'accepted'
                        and cancelled.get('data', {}).get('state') == 'accepted'
                        and cancelled.get('data', {}).get('delivery') in ('confirmed', 'possibly_sent', 'completed')
                        and cancelled.get('data', {}).get('bytesSent', 0) > 0
                        and started and cancelled['data'].get('sessionId') == started['data'].get('sessionId'))
        cases.append({'name': 'agent.cancel.accepted', 'status': 'PASS' if accepted else 'FAIL',
                      'value': cancelled})
        # Replay reads the original receipt and never resends the notification.
        send('agents cancel --instance-ref ' + str(inputs / 'start.json') +
             '#/data/instanceRef --request-id cancel-001 --timeout 30 --json', 1)
        replay = None
        for line in stdout_path.read_text().splitlines():
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if value.get('requestId') == 'cancel-001':
                replay = value
        cases.append({'name': 'agent.cancel.replay', 'status': 'PASS'
                      if replay and replay.get('data') == (cancelled or {}).get('data') else 'FAIL',
                      'value': replay})
        send('agents stop --instance-ref ' + str(inputs / 'start.json') +
             '#/data/instanceRef --request-id stop-001 --timeout 30 --json '
             '--save-result ' + str(inputs / 'stop.json'), 1)
        record('agent.stop', inputs / 'stop.json', 'completed')
        send('agents reconcile --instance-ref ' + str(inputs / 'start.json') +
             '#/data/instanceRef --request-id rec-001 --json', 5)
        send('agents reconcile --instance-ref ' + str(inputs / 'start.json') +
             '#/data/instanceRef --request-id rec-002 --json', 5)
        observation = None
        for line in stdout_path.read_text().splitlines():
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if value.get('requestId') == 'rec-002':
                observation = value
        exited = bool(observation and observation.get('data', {}).get('state') == 'exited')
        cases.append({'name': 'agent.reconcile.exited', 'status': 'PASS' if exited else 'FAIL',
                      'value': observation})
        send('environments process-release --endpoint-ref ' + str(inputs / 'start.json') +
             '#/data/processEndpointRef --request-id prel-001 --json '
             '--save-result ' + str(inputs / 'prelease.json'), 1)
        released_process = record('process.release', inputs / 'prelease.json', 'completed')
        cases.append({'name': 'process.release.exitClaimedFalse', 'status': 'PASS'
                      if released_process and released_process['data'].get('exitClaimed') is False
                      and released_process['data'].get('receipt', {}).get('transportReleased') is True
                      else 'FAIL'})
        send('environments release --use-identity ' + str(inputs / 'use.json') +
             '#/data/useIdentity --request-id rel-001 --json '
             '--save-result ' + str(inputs / 'release.json'), 1)
        released_use = record('use.release', inputs / 'release.json', 'completed')
        cases.append({'name': 'use.release.resourcePreserved', 'status': 'PASS'
                      if released_use and released_use['data'].get('resourcePreserved') is True
                      else 'FAIL'})
        send('exit', 1)
        try:
            code = proc.wait(timeout=45)
        except subprocess.TimeoutExpired:
            proc.kill()
            code = 'TIMEOUT'
        cases.append({'name': 'session.exit', 'status': 'PASS' if code == 0 else 'FAIL',
                      'exit': code})
    except Blocked as error:
        cases.append({'name': 'lifecycle', 'status': 'BLOCKED', 'error': str(error)})
        try:
            proc.kill()
        except Exception:
            pass
    except Exception as error:  # report the failing case, never a silent success
        cases.append({'name': 'lifecycle', 'status': 'FAIL', 'error': repr(error)})
        try:
            proc.kill()
        except Exception:
            pass
    finally:
        stdout.close()
        stderr.close()
    failures = [case['name'] for case in cases if case['status'] == 'FAIL']
    blocked = [case['name'] for case in cases if case['status'] == 'BLOCKED']
    receipt = {
        'schemaVersion': 'lower-cli-lifecycle-acceptance/1',
        'command': command,
        'networkIsolated': isolated,
        'state': str(state),
        'harness': pin,
        'modelPromptSent': False,
        'cases': cases,
        'passed': len(cases) - len(failures),
        'failed': len(failures),
        'failures': failures,
        'stderrTail': stderr_path.read_text()[-2000:],
        'blocked': blocked,
        'status': 'PASS' if not failures and not blocked else ('BLOCKED' if blocked and not failures else 'FAIL'),
    }
    if args.receipt:
        Path(args.receipt).write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'status': receipt['status'], 'passed': receipt['passed'],
                      'failed': receipt['failed'], 'failures': failures,
                      'blocked': blocked, 'networkIsolated': isolated,
                      'harness': pin}))
    return 0 if receipt['status'] == 'PASS' else (4 if receipt['status'] == 'BLOCKED' else 1)


if __name__ == '__main__':
    raise SystemExit(run())
