"""Real JEV ask acceptance through the single `ordessa` CLI.

Requires ``OPEN_CODE_GO_API_KEY`` in the process environment. The decision
configuration contains only ``secretEnv`` (an environment variable name), not
the key. A single short choice question is sent; the result, query replay and
scoped evidence read are checked. The key is never written to the state.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


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


def _run(argv):
    result = subprocess.run([str(item) for item in argv], capture_output=True, text=True,
                            env=dict(os.environ), timeout=180)
    try:
        value = json.loads(result.stdout.splitlines()[-1]) if result.stdout.strip() else None
    except ValueError:
        value = None
    return result.returncode, value, result.stderr


def run(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--state', required=True)
    parser.add_argument('--receipt')
    parser.add_argument('--module', action='store_true')
    parser.add_argument('--base-url', default='https://opencode.ai/inference/systemone')
    parser.add_argument('--model', default='jev-1.13-free')
    args = parser.parse_args(argv)
    key = _key()
    state = Path(args.state).absolute()
    if state.exists():
        raise SystemExit('state must not exist for a fresh acceptance run')
    state.mkdir(parents=True, mode=0o700)
    (state / 'decision.json').write_text(json.dumps({
        'provider': 'jev', 'baseUrl': args.base_url, 'model': args.model,
        'secretEnv': 'OPEN_CODE_GO_API_KEY', 'timeoutSeconds': 60}))
    job = state / 'ask-job.json'
    job.write_text(json.dumps({
        'spec_version': 'decision-job/1', 'job_id': 'cli-jev-ask', 'version': 1,
        'input': {'score': 7},
        'limits': {'max_model_calls': 1, 'max_steps': 2, 'max_value_bytes': 4096,
                   'timeout_seconds': 30.0},
        'steps': [{'id': 'ask', 'type': 'ask', 'engine': None,
                   'when': {'fact': 'input.score', 'op': 'gte', 'value': 1},
                   'payload': {'question': {'kind': 'choice', 'text': 'Proceed?',
                                            'options': {'yes': 'Yes', 'no': 'No'}}}}],
        'result': {'from': 'ask', 'path': ['answer']}}))
    # Fixed rubric score case: criteria are ordered levels (official semantics).
    score_job = state / 'score-job.json'
    score_job.write_text(json.dumps({
        'spec_version': 'decision-job/1', 'job_id': 'cli-jev-score', 'version': 1,
        'input': {'rows': 9},
        # The default host limit for timeout_seconds is 30; a larger value is
        # refused as an invalid job before any effect.
        'limits': {'max_model_calls': 1, 'max_steps': 2, 'max_value_bytes': 4096,
                   'timeout_seconds': 30.0},
        'steps': [{'id': 'rate', 'type': 'ask', 'engine': None,
                   'when': {'fact': 'input.rows', 'op': 'gte', 'value': 1},
                   'payload': {'question': {'kind': 'score',
                       'text': 'How complete is the acceptance evidence package?',
                       'scale': ['none', 'thin', 'partial', 'solid', 'complete']}}}],
        'result': {'from': 'rate', 'path': ['answer']}}))
    prefix = ([sys.executable, '-m', 'ordessa_agent_tools'] if args.module
              else [str(Path(sys.executable).parent / 'ordessa')])
    prefix += ['--state', str(state)]
    cases = []
    try:
        code, run_value, error = _run(prefix + [
            'decisions', 'run', '--job', job, '--request-id', 'jev-001',
            '--save-result', state / 'decision-result.json', '--json'])
        result = run_value or {}
        cases.append({'name': 'decision.ask.completed', 'status': 'PASS' if (
            code == 0 and result.get('status') == 'completed'
            and result.get('data', {}).get('result') in ('yes', 'no')
            and result.get('data', {}).get('evidence', {}).get('digest')) else 'FAIL',
            'exit': code, 'value': result, 'stderr': error[-500:]})
        code, query_value, error = _run(prefix + [
            'decisions', 'query', '--original-request-id', 'jev-001',
            '--job', job, '--json'])
        query = query_value or {}
        cases.append({'name': 'decision.ask.query', 'status': 'PASS' if (
            code == 0 and query.get('data') == result.get('data')) else 'FAIL',
            'exit': code, 'value': query})
        digest = ((result.get('data') or {}).get('evidence') or {}).get('digest')
        if digest:
            code, evidence_value, error = _run(prefix + [
                'decisions', 'get', '--digest', digest, '--json'])
            summary = ((evidence_value or {}).get('data') or {}).get('summary') or {}
            cases.append({'name': 'decision.ask.evidence', 'status': 'PASS' if (
                code == 0 and summary.get('usage', {}).get('ask', {}).get('status') == 'reported')
                else 'FAIL', 'exit': code, 'value': evidence_value})
        # Same request id and input replay the recorded result without a new call.
        code, replay_value, error = _run(prefix + [
            'decisions', 'run', '--job', job, '--request-id', 'jev-001', '--json'])
        replay = replay_value or {}
        cases.append({'name': 'decision.ask.replay', 'status': 'PASS' if (
            code == 0 and replay.get('data') == result.get('data')) else 'FAIL',
            'exit': code, 'value': replay})
    except Exception as error:
        cases.append({'name': 'decision-model', 'status': 'FAIL', 'error': repr(error)})
    # 5-level rubric score through the same CLI and endpoint.
    score_result = {}
    try:
        code, score_result, error = _run(prefix + [
            'decisions', 'run', '--job', score_job, '--request-id', 'jev-score-001',
            '--save-result', state / 'score-result.json', '--json'])
        value = (score_result or {}).get('data') or {}
        number = value.get('result')
        cases.append({'name': 'decision.score.completed', 'status': 'PASS' if (
            code == 0 and (score_result or {}).get('status') == 'completed'
            and type(number) in (int, float) and not isinstance(number, bool)
            and 0 <= number <= 4
            and value.get('evidence', {}).get('digest')) else 'FAIL',
            'exit': code, 'value': score_result, 'stderr': error[-500:]})
        code, query_value, error = _run(prefix + [
            'decisions', 'query', '--original-request-id', 'jev-score-001',
            '--job', score_job, '--json'])
        cases.append({'name': 'decision.score.query', 'status': 'PASS' if (
            code == 0 and (query_value or {}).get('data') == (score_result or {}).get('data')
            and (query_value or {}).get('data', {}).get('result') == number) else 'FAIL',
            'exit': code, 'value': query_value})
    except Exception as error:
        cases.append({'name': 'decision-score', 'status': 'FAIL', 'error': repr(error)})

    # The key must not be persisted in the state or the saved result.
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
        'schemaVersion': 'lower-cli-decision-model-acceptance/1',
        'state': str(state), 'baseUrl': args.base_url, 'model': args.model,
        'realModelCall': True, 'cases': cases,
        'passed': len(cases) - len(failures), 'failed': len(failures),
        'failures': failures,
        'status': 'PASS' if not failures else 'FAIL',
    }
    if args.receipt:
        Path(args.receipt).write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'status': receipt['status'], 'passed': receipt['passed'],
                      'failed': receipt['failed'], 'failures': failures}))
    return 0 if not failures else 1


if __name__ == '__main__':
    raise SystemExit(run())
