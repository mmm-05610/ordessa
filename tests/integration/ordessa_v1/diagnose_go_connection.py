"""Explicitly authorized single Go SDK comparison; not a Unit retry or acceptance."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from ordessa_agents.harness.transport.channel import LaunchSpec
from ordessa_server.composition.temporary_process_capability import ExistingOpenCodeInput


def run(output, max_tokens, session_header):
    output = Path(output).absolute()
    output.parent.mkdir(parents=True, exist_ok=True)
    intent = output.with_suffix('.intent.json')
    script = Path(__file__).with_suffix('.mjs')
    node = shutil.which('node')
    if not node:
        raise RuntimeError('node_unavailable')
    # Exclusive reservation forbids an accidental repeat even after a crash.
    with intent.open('x') as stream:
        root = Path(tempfile.mkdtemp(prefix='ordessa-go-connection-diagnostic-'))
        roots = {k: root/k for k in ('home','cwd','piHome')}
        for directory in roots.values():
            directory.mkdir()
        (roots['home']/'tmp').mkdir()
        spec = LaunchSpec.build([node, str(script), str(max_tokens),
            'session-header' if session_header else 'no-session-header'], home=str(roots['home']),
            cwd=str(roots['cwd']), extra_env={'PI_CODING_AGENT_DIR': str(roots['piHome'])})
        stream.write(json.dumps({'root': str(root), 'diagnostic_only': True,
            'old_unit_replays': 0, 'maximum_post_intents': 1,
            'model': 'opencode-go/glm-5.3-flash', 'max_tokens': max_tokens,
            'opencode_session_header_present': session_header,
            'environment_keys': sorted(spec.env), 'script_sha256': hashlib.sha256(script.read_bytes()).hexdigest(),
            'environment_differences': ['new isolated HOME/cwd/piHome; no old Unit/session/config consumed',
                'Node invoked directly; managed Pi wrapper PI_MANAGED_INSTALL_ROOT not needed by SDK'],
            'authorization': 'parent bounded SDK diagnostic with provider error capture; no automatic retry'})+'\n')
    secret = ExistingOpenCodeInput('/home/maoqh/projects/ordessa/.env').read()
    env = dict(spec.env)
    env['OPENCODE_API_KEY'] = secret.decode('ascii')
    try:
        result = subprocess.run(spec.argv, cwd=spec.cwd, env=env,
            capture_output=True, timeout=45)
        try:
            report = json.loads(result.stdout)
        except (ValueError, UnicodeError):
            report = {'outcome': 'diagnostic_output_unavailable', 'post_state': 'unknown'}
        report['process_exit_code'] = result.returncode
        report['stderr_bytes'] = len(result.stderr)
        report['stderr_sha256'] = hashlib.sha256(result.stderr).hexdigest()
        # Never persist stdout/stderr if the credential appears anywhere in either.
        if bytes(secret) in result.stdout or bytes(secret) in result.stderr:
            report = {'outcome': 'credential_output_refused', 'post_state': 'unknown'}
    except subprocess.TimeoutExpired:
        report = {'outcome': 'diagnostic_process_timeout', 'post_state': 'unknown',
            'process_cleanup': 'subprocess.run killed and waited for its own Node process'}
    finally:
        env.pop('OPENCODE_API_KEY', None)
        for index in range(len(secret)):
            secret[index] = 0
    with output.open('x') as stream:
        stream.write(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--authorize-live', action='store_true', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--max-tokens', type=int, default=32, choices=range(1,4097))
    parser.add_argument('--session-header', action='store_true')
    args = parser.parse_args()
    run(args.output, args.max_tokens, args.session_header)
