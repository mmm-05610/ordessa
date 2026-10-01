"""Locked developer Pi asset: private in-memory provider/key, zero inference.

Usage: python probe-initial-provider.py /absolute/pi-profile-runtime
This proves the real adapter, not root installation or product C4 wiring.
"""
import json
import hashlib
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
from threading import Thread
from time import monotonic
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def probe(artifact, *, register_live=False):
    calls = []
    class Deny(BaseHTTPRequestHandler):
        def do_GET(self):
            calls.append(True)
            self.send_response(403); self.end_headers()
        do_POST = do_GET
        def log_message(self, *_): pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Deny)
    server_thread = Thread(target=server.serve_forever, daemon=True); server_thread.start()
    processes = []
    try:
        with tempfile.TemporaryDirectory(prefix='ordessa-pi-initial-provider-') as temporary:
            root = Path(temporary)
            selected, routes = [], []
            for slot in (1, 2):
                instance = root / f'instance-{slot}'; instance.mkdir(mode=0o700)
                home = root / f'home-{slot}'; home.mkdir(mode=0o700)
                project = root / f'project-{slot}'; project.mkdir(mode=0o700)
                env = dict(PATH=os.defpath, HOME=str(home), PI_OFFLINE='1', ORDESSA_PI_INSTANCE_DIR=str(instance))
                process = subprocess.Popen(['/usr/bin/node', str(artifact / 'node_modules/@automatalabs/pi-acp/dist/ordessa-profile.mjs')],
                    cwd=project, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL, text=True)
                processes.append(process)
                inbox = queue.Queue()
                def collect(proc=process, messages=inbox):
                    for line in proc.stdout: messages.put(json.loads(line))
                    messages.put(None)
                Thread(target=collect, daemon=True).start()
                def request(method, params, proc=process, messages=inbox):
                    assert method != 'session/prompt'
                    rid = str(monotonic())
                    proc.stdin.write(json.dumps(dict(jsonrpc='2.0', id=rid, method=method, params=params)) + '\n'); proc.stdin.flush()
                    deadline = monotonic() + 20
                    while True:
                        answer = messages.get(timeout=max(0, deadline - monotonic()))
                        assert answer is not None, 'Adapter exited before reply'
                        if answer.get('id') == rid:
                            assert 'error' not in answer, 'Adapter rejected ' + method
                            return answer['result']
                request('initialize', dict(protocolVersion=1, clientCapabilities={}))
                endpoint = f'http://127.0.0.1:{server.server_port}/instance-{slot}/v1'
                prepared = request('_ordessa/channel/configuration/prepare', dict(operationId=f'create:instance-{slot}',
                    model='first', models=['first', 'second'], provider=dict(providerId='ordessa-probe',
                        apiType='openai-completions', baseUrl=endpoint, apiKey='!opaque-synthetic-not-a-command')))
                assert prepared['state'] == 'prepared'
                native = request('session/new', dict(cwd=str(project), mcpServers=[]))['sessionId']
                record = request('_ordessa/channel/configuration/operation', dict(operationId=f'create:instance-{slot}'))
                assert record['state'] == 'observed' and record['after']['sessionId'] == native
                assert '!opaque-synthetic-not-a-command' not in json.dumps(record)
                if slot == 1:
                    request('session/set_config_option', dict(sessionId=native, configId='model', value='ordessa-probe/second'))
                state = request('_ordessa/session/configuration', dict(sessionId=native))
                model = next(o for o in state['configOptions'] if o['id'] == 'model')
                selected.append(model['currentValue'])
                facts = next(o['_meta']['ordessaModel'] for o in model['options'] if o['value'] == model['currentValue'])
                assert facts['baseUrl'] == endpoint
                if register_live and slot == 1:
                    capability = request('_ordessa/session/configuration/provider-capability', dict(sessionId=native))
                    assert capability == dict(supported=True, strategy='live-registration', version=1)
                    digest = lambda value: hashlib.sha256(json.dumps(value, sort_keys=True,
                        ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
                    payload = dict(sessionId=native, operationId='provider:live-probe',
                        expectedGeneration=state['generation'], expectedConfigDigest=digest(state['configOptions']),
                        target=dict(server_id='fixture-server', session_id='fixture-canonical', channel_id='fixture-channel', runtime_generation=1),
                        model='third', models=['third'], provider=dict(providerId='ordessa-next',
                            apiType='openai-completions', baseUrl=endpoint + '/next', apiKey='!different-synthetic-private-key'))
                    admitted = request('_ordessa/session/configuration/provider-register', payload)
                    assert admitted['state'] == 'observed' and admitted['kind'] == 'provider-registration'
                    assert admitted['after']['generation'] == state['generation']
                    assert next(o for o in admitted['after']['configOptions'] if o['id'] == 'model')['currentValue'] == model['currentValue']
                    assert '!different-synthetic-private-key' not in json.dumps(admitted)
                    assert request('_ordessa/session/configuration/provider-register', payload) == admitted
                    assert request('_ordessa/session/configuration/operation', dict(sessionId=native, operationId=payload['operationId'])) == admitted
                    applied = request('_ordessa/session/configuration/apply', dict(sessionId=native,
                        operationId='live-probe-select', expectedGeneration=state['generation'],
                        expectedConfigDigest=digest(admitted['after']['configOptions']), configId='model', value='ordessa-next/third'))
                    assert applied['state'] == 'observed' and applied['after']['generation'] == state['generation']
                    assert next(o for o in applied['after']['configOptions'] if o['id'] == 'model')['currentValue'] == 'ordessa-next/third'
                    # The original provider remains usable, with no restart or new.
                    request('session/set_config_option', dict(sessionId=native, configId='model', value='ordessa-probe/second'))
                routes.append(endpoint)
                auth = instance / 'auth.json'
                # The upstream file-lock storage creates an empty auth.json
                # while reading. Empty bookkeeping is not a persisted key.
                assert not auth.exists() or json.loads(auth.read_text()) == {}, 'Credential unexpectedly persisted'
                assert not (instance / 'models.json').exists(), 'Provider unexpectedly persisted'
                request('session/close', dict(sessionId=native))
            assert selected == ['ordessa-probe/second', 'ordessa-probe/first'] and routes[0] != routes[1]
            assert calls == [], 'No provider network permitted in this probe'
            return dict(scope='real-developer-pi-initial-provider', instances=2, selected=selected,
                independentRoutes=True, liveRegistration=register_live, sameNativeGeneration=register_live,
                persistedCredentials=0, modelFiles=0, prompt=0, http=0)
    finally:
        for process in processes:
            if process.stdin: process.stdin.close()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
        server.shutdown(); server.server_close(); server_thread.join(timeout=5)


if __name__ == '__main__':
    print(json.dumps(probe(Path(sys.argv[1]).resolve(), register_live='--register-live' in sys.argv[2:])))
