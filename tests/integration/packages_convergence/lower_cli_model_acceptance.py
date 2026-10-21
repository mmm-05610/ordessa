"""Real model prompt/query acceptance with the selected kilo brand.

Requires ``OPEN_CODE_GO_API_KEY`` in the process environment (loaded from the
root ``.env`` by the caller; this script never reads or prints it). The state
configuration contains only a credential *reference* (``envFrom``), never the
key. The model call is a single short prompt against the OpenCode Go endpoint.

This is a real-model layer; it is separate from the offline lifecycle
acceptance and is not required when the caller has not authorized model calls.
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


def _key():
    value = os.environ.get('OPEN_CODE_GO_API_KEY', '')
    if not value:
        raise SystemExit('BLOCKED: OPEN_CODE_GO_API_KEY is not in the process environment')
    return value


def _read(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def _command(state, *, module):
    prefix = ([sys.executable, '-m', 'ordessa_cli'] if module
              else [str(Path(sys.executable).parent / 'ordessa')])
    return prefix + ['--state', str(state), 'session']


def run(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--state', required=True)
    parser.add_argument('--receipt')
    parser.add_argument('--module', action='store_true')
    parser.add_argument('--model', default='deepseek-v4.1-flash')
    parser.add_argument('--base-url', default='https://opencode.ai/zen/go/v1')
    parser.add_argument('--prompt', default='Reply with exactly: OK')
    parser.add_argument('--expect', default='OK',
                        help='substring the real model answer must contain')
    args = parser.parse_args(argv)
    key = _key()
    state = Path(args.state).absolute()
    inputs = state / 'inputs'
    if state.exists():
        raise SystemExit('state must not exist for a fresh acceptance run')
    inputs.mkdir(parents=True, mode=0o700)
    os.chmod(state, 0o700)
    (inputs / 'roots.json').write_text(json.dumps(
        {'work': '.', 'home': 'home', 'config': 'config', 'data': 'data',
         'state': 'state', 'cache': 'cache', 'tmp': 'tmp'}))
    config = {
        'autoupdate': False,
        'model': 'opencode-go/' + args.model,
        'provider': {'opencode-go': {
            'npm': '@ai-sdk/openai-compatible',
            'name': 'OpenCode Go',
            'options': {'baseURL': args.base_url,
                        'apiKey': '{env:KILO_PROVIDER_KEY}',
                        'headers': {'x-opencode-session': 'ordessa-lower-cli'}},
            'models': {args.model: {'name': args.model}},
        }},
    }
    (state / 'harness.json').write_text(json.dumps({
        'allowlist': ['kilo'],
        'providers': {'kilo': {
            'env': {'KILO_CONFIG_CONTENT': json.dumps(config)},
            'envFrom': {'KILO_PROVIDER_KEY': 'OPEN_CODE_GO_API_KEY'}}}}))
    stdout_path = inputs / 'session.stdout'
    stderr_path = inputs / 'session.stderr'
    stdout = stdout_path.open('w')
    stderr = stderr_path.open('w')
    environment = dict(os.environ)
    proc = subprocess.Popen(_command(state, module=args.module), stdin=subprocess.PIPE,
                            stdout=stdout, stderr=stderr, text=True, cwd=str(state),
                            env=environment)
    cases = []
    prompt_value = None

    def send(line, wait=1.0):
        proc.stdin.write(line + '\n')
        proc.stdin.flush()
        time.sleep(wait)

    try:
        send('environments create local --root ' + str(state / 'work') + ' --alias demo '
             '--request-id env-001 --json', 1)
        send('environments acquire demo true --request-id use-001 --json '
             '--save-result ' + str(inputs / 'use.json'), 1)
        send('environments export-endpoint --use-identity ' + str(inputs / 'use.json') +
             '#/data/useIdentity launcher observe communicate terminate detach files '
             '--roots ' + str(inputs / 'roots.json') + ' --request-id ep-001 --json '
             '--save-result ' + str(inputs / 'endpoint.json'), 1)
        send('agents harness list --json --save-result ' + str(inputs / 'harness-list.json'), 1)
        harnesses = (_read(inputs / 'harness-list.json') or {}).get('data', {}).get('harnesses', ())
        if not harnesses:
            raise RuntimeError('no installed harness provider')
        pin = next(item for item in harnesses if item['definitionRef']['definitionId'] == 'kilo')['definitionRef']
        (inputs / 'profile-manifest.json').write_text(json.dumps(
            {'schemaVersion': '1', 'harnessDefinitionRef': pin, 'declarations': []}))
        send('agents profiles create demo-profile --name Demo --manifest ' +
             str(inputs / 'profile-manifest.json') + ' --request-id prof-001 --json '
             '--save-result ' + str(inputs / 'profile.json'), 1)
        send('agents start --profile-ref ' + str(inputs / 'profile.json') +
             '#/data/currentManifestRef --endpoint-ref ' + str(inputs / 'endpoint.json') +
             '#/data/endpointRef --request-id start-001 --timeout 30 --json '
             '--save-result ' + str(inputs / 'start.json'), 15)
        started = _read(inputs / 'start.json')
        if not started or started.get('status') != 'completed':
            raise RuntimeError('agent start failed: ' + repr(started))
        session_id = started['data'].get('sessionId')
        (inputs / 'params.json').write_text(json.dumps({
            'sessionId': session_id,
            'prompt': [{'type': 'text', 'text': args.prompt}]}))
        send('agents prompt --instance-ref ' + str(inputs / 'start.json') +
             '#/data/instanceRef --params ' + str(inputs / 'params.json') +
             ' --request-id prompt-001 --timeout 120 --json '
             '--save-result ' + str(inputs / 'prompt.json'), 60)
        prompt_value = _read(inputs / 'prompt.json')
        observed = json.dumps(prompt_value.get('data') if prompt_value else None)
        cases.append({'name': 'agent.prompt.completed', 'status': 'PASS'
                      if prompt_value and prompt_value.get('status') == 'completed'
                      and prompt_value.get('data', {}).get('state') == 'completed'
                      and prompt_value.get('data', {}).get('turnRef')
                      and prompt_value.get('data', {}).get('inputDigest') else 'FAIL',
                      'value': prompt_value})
        cases.append({'name': 'agent.prompt.model_response', 'status': 'PASS'
                      if args.expect in observed else 'FAIL', 'expected': args.expect,
                      'observed': observed[:1200]})
        # Build the original turn query from the same public SDK value.
        from ordessa_agents.sdk.interactions import TurnRef, turn_query
        turn = prompt_value['data']['turnRef']
        query = turn_query(TurnRef.decode(turn), prompt_value['data']['inputDigest'])
        (inputs / 'query.json').write_text(json.dumps(query.projection()))
        send('agents query --query ' + str(inputs / 'query.json') +
             ' --request-id query-001 --json --save-result ' + str(inputs / 'query.json.out'), 2)
        queried = _read(inputs / 'query.json.out')
        cases.append({'name': 'agent.query.original', 'status': 'PASS'
                      if queried and queried.get('status') == 'completed'
                      and queried.get('data') == prompt_value.get('data') else 'FAIL',
                      'value': queried})
        send('agents stop --instance-ref ' + str(inputs / 'start.json') +
             '#/data/instanceRef --request-id stop-001 --timeout 30 --json '
             '--save-result ' + str(inputs / 'stop.json'), 1)
        send('agents reconcile --instance-ref ' + str(inputs / 'start.json') +
             '#/data/instanceRef --request-id rec-001 --json', 5)
        send('agents reconcile --instance-ref ' + str(inputs / 'start.json') +
             '#/data/instanceRef --request-id rec-002 --json', 5)
        send('environments process-release --endpoint-ref ' + str(inputs / 'start.json') +
             '#/data/processEndpointRef --request-id prel-001 --json '
             '--save-result ' + str(inputs / 'prelease.json'), 1)
        send('environments release --use-identity ' + str(inputs / 'use.json') +
             '#/data/useIdentity --request-id rel-001 --json '
             '--save-result ' + str(inputs / 'release.json'), 1)
        send('exit', 1)
        try:
            code = proc.wait(timeout=45)
        except subprocess.TimeoutExpired:
            proc.kill()
            code = 'TIMEOUT'
        cases.append({'name': 'session.exit', 'status': 'PASS' if code == 0 else 'FAIL',
                      'exit': code})
    except Exception as error:
        cases.append({'name': 'model-lifecycle', 'status': 'FAIL', 'error': repr(error)})
        try:
            proc.kill()
        except Exception:
            pass
    finally:
        stdout.close()
        stderr.close()
    # The key must not appear in persisted state or captured output.
    leaked = []
    for path in state.rglob('*'):
        if path.is_file():
            try:
                if key.encode() in path.read_bytes():
                    leaked.append(str(path))
            except OSError:
                pass
    cases.append({'name': 'credential.not_persisted', 'status': 'PASS' if not leaked else 'FAIL',
                  'leaked': leaked})
    failures = [case['name'] for case in cases if case['status'] != 'PASS']
    receipt = {
        'schemaVersion': 'lower-cli-model-acceptance/1',
        'state': str(state),
        'model': args.model,
        'baseUrl': args.base_url,
        'realModelCall': True,
        'cases': cases,
        'passed': len(cases) - len(failures),
        'failed': len(failures),
        'failures': failures,
        'stderrTail': stderr_path.read_text()[-2000:].replace(key, '<redacted>'),
        'status': 'PASS' if not failures else 'FAIL',
    }
    if args.receipt:
        Path(args.receipt).write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'status': receipt['status'], 'passed': receipt['passed'],
                      'failed': receipt['failed'], 'failures': failures}))
    return 0 if not failures else 1


if __name__ == '__main__':
    raise SystemExit(run())
