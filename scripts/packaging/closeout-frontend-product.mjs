#!/usr/bin/env node
// Source-free product/frontend acceptance bridge. This runner imports only
// shipped extension artifacts in Chromium and dispatches every Agent wire
// request to the artifact interpreter's real ServerProductComposition. Only
// native effects, fingerprint key material and explicit local test policy are
// supplied by controlled_native_fixture.py.
import { spawn } from 'node:child_process'
import { access, copyFile, mkdtemp, mkdir, readFile, realpath, rm, stat, writeFile } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import process from 'node:process'
import { fileURLToPath } from 'node:url'

const timeoutMs = 45_000
const argv = process.argv.slice(2)
const option = name => {
  const at = argv.indexOf(name)
  return at < 0 ? undefined : argv[at + 1]
}
const assert = (condition, message) => { if (!condition) throw new Error(message) }

async function firstFile(paths) {
  for (const item of paths) {
    try { if ((await stat(item)).isFile()) return await realpath(item) } catch { /* continue */ }
  }
}
async function firstDirectory(paths) {
  for (const item of paths) {
    try { if ((await stat(item)).isDirectory()) return await realpath(item) } catch { /* continue */ }
  }
}
function isWithin(file, directory) {
  const relative = path.relative(directory, file)
  return relative === '' || (!relative.startsWith(`..${path.sep}`) && relative !== '..' && !path.isAbsolute(relative))
}

function locate(rootInput, electronOverride, pythonOverride) {
  if (!rootInput) throw new Error('usage: closeout-frontend-product.mjs --artifact-root <unpacked product> [--electron <artifact Electron>]')
  const root = path.resolve(rootInput)
  return {
    root,
    prefix: [path.join(root, 'opt/ordessa'), root, path.join(root, 'app')],
    agent: [path.join(root, 'app/dist/extensions/ordessa.agent-contracts'), path.join(root, 'dist/extensions/ordessa.agent-contracts'), path.join(root, 'extensions/ordessa.agent-contracts'), path.join(root, 'products/desktop/dist/extensions/ordessa.agent-contracts')],
    chat: [path.join(root, 'app/dist/extensions/ordessa.chat'), path.join(root, 'dist/extensions/ordessa.chat'), path.join(root, 'extensions/ordessa.chat'), path.join(root, 'products/desktop/dist/extensions/ordessa.chat')],
    shared: [path.join(root, 'app/dist/extensions/ordessa.contracts'), path.join(root, 'dist/extensions/ordessa.contracts'), path.join(root, 'extensions/ordessa.contracts'), path.join(root, 'products/desktop/dist/extensions/ordessa.contracts')],
    api: [path.join(root, 'app/dist/renderer/shared/api.js'), path.join(root, 'dist/renderer/shared/api.js'), path.join(root, 'renderer/shared/api.js'), path.join(root, 'apps/desktop/dist/renderer/shared/api.js')],
    electron: electronOverride ? [path.resolve(electronOverride)] : [path.join(root, 'app/electron/electron'), path.join(root, 'app/electron'), path.join(root, 'electron/electron'), path.join(root, 'electron'), path.join(root, 'apps/desktop/electron/electron')],
    python: pythonOverride ? [path.resolve(pythonOverride)] : [
      path.join(root, 'opt/ordessa/python/bin/python3.12'), path.join(root, 'python/bin/python3.12'),
    ],
    fixture: path.resolve(path.dirname(fileURLToPath(import.meta.url)), 'controlled_native_fixture.py'),
  }
}

function pythonDriverSource() {
  return String.raw`import dataclasses, enum, importlib.util, json, os, signal, sqlite3, sys, threading, traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

prefix = Path(sys.argv[1]).resolve()
fixture_path = Path(sys.argv[2]).resolve(strict=True)
data_path = Path(sys.argv[3]).resolve()
effects_path = Path(sys.argv[4]).resolve()
include_profile = sys.argv[5] == 'true'
fixture_spec = importlib.util.spec_from_file_location('ordessa_closeout_controlled_fixture', fixture_path)
fixture_module = importlib.util.module_from_spec(fixture_spec)
sys.modules[fixture_spec.name] = fixture_module
fixture_spec.loader.exec_module(fixture_module)
native = fixture_module.ControlledNativeFixture(
    effects_path, mode='createWithConfig',
    attachment_bytes={'attachment-controlled-1': b'controlled immutable fixture bytes'},
)
composition = fixture_module.controlled_product_composition(
    native_submit_port=native,
    fingerprint_port=fixture_module.test_protected_fingerprint(),
    submission_policy=fixture_module.controlled_submission_policy(),
)
runtime = composition.default_runtime(data_path, include_profile=include_profile)
runtime.start()
selected_ids = [plugin.descriptor().id for plugin in runtime.plugin_selection]
calls = []
closing = threading.Event()

def plain(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, enum.Enum):
        return value.value
    if dataclasses.is_dataclass(value):
        return plain(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(v) for v in value]
    dump = getattr(value, 'model_dump', None)
    if callable(dump):
        return plain(dump(mode='json'))
    dump = getattr(value, 'dict', None)
    if callable(dump):
        return plain(dump())
    if hasattr(value, '__dict__'):
        return plain(vars(value))
    return str(value)

def respond(handler, status, value):
    raw = json.dumps(value, separators=(',', ':'), default=str, allow_nan=False).encode()
    handler.send_response(status)
    handler.send_header('Content-Type', 'application/json; charset=utf-8')
    handler.send_header('Content-Length', str(len(raw)))
    handler.send_header('Access-Control-Allow-Origin', '*')
    handler.send_header('Access-Control-Allow-Headers', 'content-type')
    handler.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
    handler.end_headers()
    handler.wfile.write(raw)

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        return
    def do_OPTIONS(self):
        respond(self, 200, {})
    def do_GET(self):
        if self.path != '/ready':
            respond(self, 404, {'error': 'unknown route'}); return
        respond(self, 200, {'ready': bool(runtime.started), 'includeProfile': include_profile,
            'pluginIds': selected_ids, 'controlledRuntimeGeneration': 1,
            'nativeEffectCounts': {json.dumps(k): v for k, v in native.all_effect_counts().items()},
            'transport': 'loopback-http-to-runtime.wire.dispatch'})
    def do_POST(self):
        try:
            size = int(self.headers.get('Content-Length', '0'))
            body = json.loads(self.rfile.read(size) or b'{}')
            if self.path == '/control/mode':
                mode = body.get('mode')
                native.set_mode(mode)
                respond(self, 200, {'selectedMode': mode, 'externalSelection': True}); return
            if self.path == '/control/stats':
                with sqlite3.connect(effects_path) as connection:
                    rows = connection.execute(
                        'SELECT environment_namespace, principal_scope, request_id, dispatch_count, mode, payload '
                        'FROM native_effects ORDER BY request_id'
                    ).fetchall()
                effects = []
                for env, principal, request_id, count, mode, payload_json in rows:
                    payload = json.loads(payload_json)
                    effects.append({'key': [env, principal, request_id], 'count': count, 'mode': mode,
                        'target': payload.get('target'), 'binding': payload.get('binding'),
                        'configOperationIds': payload.get('configOperationIds')})
                respond(self, 200, {'methodCalls': list(calls), 'effects': effects,
                    'effectCounts': [{'key': list(key), 'count': count} for key, count in native.all_effect_counts().items()]}); return
            if self.path == '/control/stop':
                respond(self, 200, {'stopping': True})
                closing.set()
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            if self.path != '/dispatch' or not runtime.started:
                respond(self, 404, {'kind': 'Refused', 'reason': 'wire route unavailable'}); return
            method, params = body.get('method'), body.get('params')
            if not isinstance(method, str) or not isinstance(params, dict):
                respond(self, 400, {'kind': 'Refused', 'reason': 'invalid wire request'}); return
            calls.append(method)
            try:
                result = plain(runtime.wire.dispatch(method, params))
                if method == 'agent.session.resolve' and isinstance(result, dict):
                    resolved = result.get('result', result)
                    target = resolved.get('target') if isinstance(resolved, dict) else None
                    if isinstance(target, str) and target:
                        native.bind_backend_target(target)
                # Adapt the real dispatcher result to the public extension
                # WireCall shape. Method handling stays in runtime.wire.dispatch.
                respond(self, 200, {'kind': 'Accepted', 'result': result})
            except BaseException as error:
                respond(self, 200, {'kind': 'Refused', 'reason': type(error).__name__ + ': ' + str(error),
                    'code': getattr(error, 'code', None), 'details': plain(getattr(error, 'details', None))})
        except BaseException as error:
            respond(self, 500, {'error': type(error).__name__ + ': ' + str(error), 'traceback': traceback.format_exc(limit=3)})

server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
server.daemon_threads = True
print('PRODUCT_READY ' + json.dumps({'port': server.server_address[1], 'includeProfile': include_profile,
    'pluginIds': selected_ids}, separators=(',', ':')), flush=True)
try:
    server.serve_forever(poll_interval=0.1)
finally:
    server.server_close()
    if runtime.started:
        runtime.stop()
    print('PRODUCT_STOPPED', flush=True)
`
}

function browserHtml({ port, variant, phase, databaseName, requestPrefix, keys = [] }) {
  const importMap = { imports: {
    '@extensions/ordessa.agent-contracts/': '/extensions/ordessa.agent-contracts/',
    '@extensions/ordessa.chat/': '/extensions/ordessa.chat/',
    '@extensions/ordessa.contracts/': '/extensions/ordessa.contracts/',
    '@ordessa/extension-api': '/shared/api.js',
  } }
  const script = `import * as agent from '@extensions/ordessa.agent-contracts/contract.js';
import { createReliableChatSubmission } from '@extensions/ordessa.chat/submission.js';
const port = ${port};
const variant = ${JSON.stringify(variant)};
const phase = ${JSON.stringify(phase)};
const databaseName = ${JSON.stringify(databaseName)};
const requestPrefix = ${JSON.stringify(requestPrefix)};
const originalKeys = ${JSON.stringify(keys)};
const base = 'http://127.0.0.1:' + port;
const calls = [];
const report = value => { window.__closeoutProductResult = value; };
async function control(path, body) {
  const response = await fetch(base + path, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body ?? {}) });
  const value = await response.json();
  if (!response.ok) throw new Error('fixture control failed: ' + JSON.stringify(value));
  return value;
}
const wire = {
  ready: true,
  scope: 'controlled-product-wire:' + variant,
  async call(method, params) {
    calls.push(method);
    const response = await fetch(base + '/dispatch', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ method, params }) });
    const value = await response.json();
    if (!response.ok) throw new Error('product runtime wire bridge failed: ' + JSON.stringify(value));
    return value;
  },
};
const readyResponse = await fetch(base + '/ready');
const ready = await readyResponse.json();
if (!ready.ready || ready.includeProfile !== (variant === 'withProfile')) throw new Error('unexpected actual product runtime variant: ' + JSON.stringify(ready));
if (ready.pluginIds.includes('ordessa.profile') !== (variant === 'withProfile'))
  throw new Error('actual ServerProductComposition selected the wrong Profile plugin set: ' + JSON.stringify(ready.pluginIds));
if (typeof agent.createWireConfigurationClient !== 'function'
    || typeof agent.createFrontendSubmissionJournal !== 'function'
    || typeof agent.createDurableSubmissionClient !== 'function'
    || typeof createReliableChatSubmission !== 'function') {
  throw new Error('built public artifacts lack a required Agent/Chat production export');
}
const sessionSnapshot = Object.freeze({ runtimeGeneration: ready.controlledRuntimeGeneration });
const sessions = Object.freeze({ getSnapshot: () => sessionSnapshot, subscribe: () => () => undefined });
const location = Object.freeze({ kind: 'draft', draftId: 'closeout-draft-' + variant,
  connectionId: 'controlled-connection', contextRevision: 1,
  runtimeGeneration: ready.controlledRuntimeGeneration });
const config = agent.createWireConfigurationClient({ wire, sessions });
const journal = agent.createFrontendSubmissionJournal({ databaseName });
const durable = agent.createDurableSubmissionClient({ wire: wire.call.bind(wire), journal });
const captured = [];
const chat = createReliableChatSubmission(config, {
  async submit(capture) {
    captured.push(capture);
    const result = await durable.submit(capture);
    if (result.status === 'accepted') return { status: 'accepted' };
    if (result.status === 'refused') return { status: 'refused', reason: result.reason };
    if (result.status === 'unavailable') return { status: 'refused', reason: result.reason };
    return { status: 'unknown', reason: result.queryHint };
  },
});
function assertCapture(capture, index) {
  const expectedMode = index === 0 ? 'createWithConfig' : 'existing';
  if (capture.guarantee !== 'reliable' || capture.submissionMode !== expectedMode
      || capture.inputSchema !== 'agent-input/v1' || capture.key.requestId !== requestPrefix + '-' + (index + 1)
      || !capture.key.namespace || !capture.key.principalScope
      || capture.target !== capture.binding.target || capture.generation !== capture.binding.generation
      || !capture.binding.expectedConditions || !capture.binding.expectedConditions.binding
      || !capture.binding.expectedConditions.baseRevision || !capture.binding.expectedConditions.sourceRevision
      || !capture.binding.expectedConditions.configOwnerRef
      || capture.draft.attachmentIds.length !== 1 || capture.draft.attachmentRefs.length !== 1
      || capture.draft.attachmentRefs[0] !== 'attachment-controlled-1'
      || capture.configOperationIds.length !== 1) {
    throw new Error('Chat adapter did not capture complete reliable C2/expectedConditions fields: ' + JSON.stringify(capture));
  }
  for (const field of ['ownerRef', 'surfaceId', 'environment', 'environmentContextRevision', 'providerActivation']) {
    if (!capture.binding.expectedConditions.binding[field]) throw new Error('expectedConditions.binding lacks ' + field);
  }
}
try {
  if (phase === 'warm') {
    const rounds = [];
    for (let index = 0; index < 2; index += 1) {
      const expectedMode = index === 0 ? 'createWithConfig' : 'existing';
      const selected = await control('/control/mode', { mode: expectedMode });
      if (selected.selectedMode !== expectedMode || selected.externalSelection !== true)
        throw new Error('native mode was not externally selected before location resolution');
      const projection = await config.forLocation(location);
      const operation = await projection.dispatch(index === 0
        ? { model: 'controlled-model-M1', prompt: 'Keep this prompt across profile operations' }
        : { model: 'controlled-model-M2' }, { sourceRef: variant === 'withProfile'
          ? 'controlled-profile-fixture' : 'controlled-default-fixture' });
      if (operation.kind !== 'ok' || !operation.value?.operationId) throw new Error('real Agent config owner refused operation: ' + JSON.stringify(operation));
      await projection.refresh();
      await config.forLocation(location); // Refreshes authorized projection and expected conditions.
      const projected = projection.getSnapshot();
      const expectedModel = index === 0 ? 'controlled-model-M1' : 'controlled-model-M2';
      if (projected.status !== 'ready' || projected.config?.resolved.model !== expectedModel
          || projected.config?.resolved.prompt !== 'Keep this prompt across profile operations') {
        throw new Error('Agent configuration owner lost the expected model/prompt projection: ' + JSON.stringify(projected));
      }
      const submissionId = requestPrefix + '-' + (index + 1);
      const snapshot = Object.freeze({ submissionId, target: location, draftId: location.draftId,
        draftRevision: index + 1, text: index === 0 ? 'controlled first prompt' : 'controlled second prompt',
        attachmentIds: Object.freeze(['item-' + (index + 1)]),
        attachmentRefs: Object.freeze(['attachment-controlled-1']) });
      const gateway = chat.capture(snapshot);
      const result = await gateway.submit(snapshot);
      const capture = captured[index];
      if (!capture) throw new Error('Chat production adapter did not submit a captured request');
      assertCapture(capture, index);
      if (result.status !== 'accepted') throw new Error('real Agent/Product submission was not accepted: ' + JSON.stringify(result));
      const stored = await journal.get(capture.key);
      if (!stored || stored.state !== 'result-recorded' || stored.results.at(-1)?.outcome !== 'accepted')
        throw new Error('frontend IndexedDB journal did not durably retain accepted result');
      rounds.push({ requestId: submissionId, target: capture.target, generation: capture.generation,
        configOperationIds: capture.configOperationIds, expectedConditions: capture.binding.expectedConditions,
        resolved: projected.config.resolved, outcome: result.status, journalState: stored.state, nativeMode: expectedMode });
    }
    const records = await durable.list({ namespace: captured[0].key.namespace, principalScope: captured[0].key.principalScope });
    if (records.length !== 2) throw new Error('journal did not list both Agent submissions in the same logical principal scope');
    const stats = await control('/control/stats', {});
    const submitCalls = stats.methodCalls.filter(method => method === 'agent.submitInput');
    if (submitCalls.length !== 2) throw new Error('actual runtime.wire.dispatch did not receive exactly two submits: ' + JSON.stringify(stats));
    if (stats.effects.length !== 2 || stats.effects.some((item, index) => item.count !== 1
        || item.mode !== (index === 0 ? 'createWithConfig' : 'existing')
        || item.key[2] !== requestPrefix + '-' + (index + 1)
        || item.key[0] !== captured[index].key.namespace
        || item.key[1] !== captured[index].key.principalScope
        || item.target !== captured[index].target
        || JSON.stringify(item.configOperationIds) !== JSON.stringify(captured[index].configOperationIds)))
      throw new Error('controlled native effects did not record one expected mode/effect per original key: ' + JSON.stringify(stats.effects));
    if (captured[0].target !== captured[1].target || captured[0].generation !== captured[1].generation
        || JSON.stringify(stats.effects[0].binding) !== JSON.stringify(stats.effects[1].binding))
      throw new Error('create-then-existing dispatch changed canonical/native binding identity');
    await journal.dispose(); config.dispose();
    report({ ok: true, phase, variant, pluginIds: ready.pluginIds, rounds,
      modeSequence: rounds.map(round => round.nativeMode), keys: captured.map(item => item.key),
      journalRecords: records.length, wireCalls: calls, serverStats: stats,
      boundary: { frontend: 'real Chromium + shipped public Agent and Chat adapter artifacts',
        product: 'artifact interpreter real ServerProductComposition and runtime.wire.dispatch',
        native: 'ControlledNativeFixture only', fingerprint: 'fixture-only ProtectedFingerprintHmac',
        transport: 'owned loopback HTTP bridge; not production transport' } });
  } else {
    const recovered = [];
    for (let index = 0; index < 2; index += 1) {
      const requestId = requestPrefix + '-' + (index + 1);
      const key = originalKeys[index];
      if (!key || key.requestId !== requestId) throw new Error('warm run did not provide the original durable key');
      const list = await journal.list({ namespace: key.namespace, principalScope: key.principalScope });
      const record = list.find(item => item.key.requestId === requestId);
      const expectedMode = index === 0 ? 'createWithConfig' : 'existing';
      if (!record || record.state !== 'result-recorded' || record.target !== record.binding.target
          || record.submissionMode !== expectedMode || record.results.every(item => item.outcome !== 'accepted'))
        throw new Error('real IndexedDB did not recover the original complete submission record: ' + requestId);
      const before = calls.length;
      const result = await durable.reconcile(record.key);
      const queryCalls = calls.slice(before);
      if (result.status !== 'accepted' || queryCalls.length !== 1 || queryCalls[0] !== 'agent.submission.query')
        throw new Error('cold recovery must query only the original request key: ' + JSON.stringify({ result, queryCalls }));
      const after = await journal.get(record.key);
      if (!after || after.key.requestId !== requestId || after.target !== record.target
          || after.state !== 'result-recorded' || after.binding.expectedConditions.sourceRevision !== record.binding.expectedConditions.sourceRevision)
        throw new Error('recovery rewrote the original durable identity/conditions');
      const facts = after.results.at(-1)?.facts;
      if (!facts || facts.outcome !== 'accepted' || !facts.configApply || !facts.inputAcceptance || !facts.runResult)
        throw new Error('backend query did not return separate config/input/run facts: ' + JSON.stringify(facts));
      recovered.push({ requestId, target: record.target, originalKey: record.key,
        nativeMode: expectedMode, configOperationIds: record.configOperationIds,
        calls: queryCalls, outcome: result.status, facts });
    }
    const stats = await control('/control/stats', {});
    if (stats.methodCalls.some(method => method === 'agent.submitInput'))
      throw new Error('restart recovery attempted a second dispatch');
    if (stats.methodCalls.filter(method => method === 'agent.submission.query').length !== 2)
      throw new Error('restart recovery did not query both original request IDs');
    if (stats.effects.length !== 2 || stats.effects.some((item, index) => item.count !== 1
        || item.mode !== (index === 0 ? 'createWithConfig' : 'existing')
        || item.key[2] !== requestPrefix + '-' + (index + 1)
        || item.key[0] !== originalKeys[index].namespace
        || item.key[1] !== originalKeys[index].principalScope
        || item.target !== recovered[index].target
        || JSON.stringify(item.configOperationIds) !== JSON.stringify(recovered[index].configOperationIds)))
      throw new Error('native effect facts changed across frontend/product restart: ' + JSON.stringify(stats.effects));
    if (stats.effects[0].target !== stats.effects[1].target
        || JSON.stringify(stats.effects[0].binding) !== JSON.stringify(stats.effects[1].binding))
      throw new Error('native query history contains inconsistent target/binding identity across modes');
    await journal.dispose();
    report({ ok: true, phase, variant, recovered, serverStats: stats,
      boundary: { frontend: 'new Chromium process and same real IndexedDB userData',
        product: 'new artifact interpreter runtime with original product data root',
        native: 'same controlled native-effects SQLite reopened; dispatch counter not deduplicated',
        recovery: 'DurableSubmissionClient.reconcile queried only original keys' } });
  }
} catch (error) {
  report({ ok: false, phase, variant, error: String(error && error.stack || error), wireCalls: calls });
}
</script>`
  return `<!doctype html><meta charset="utf-8"><script type="importmap">${JSON.stringify(importMap)}</script><script type="module">${script}</script>`
}

function electronMainSource({ userData, html, roots }) {
  return `const { app, BrowserWindow, protocol } = require('electron');
const fs = require('node:fs/promises'); const path = require('node:path');
protocol.registerSchemesAsPrivileged([{ scheme: 'ordessa', privileges: { standard:true, secure:true, supportFetchAPI:true, corsEnabled:true } }]);
app.setPath('userData', ${JSON.stringify(userData)});
const roots=${JSON.stringify(roots)}, page=${JSON.stringify(html)};
function typeOf(file){return file.endsWith('.js')||file.endsWith('.mjs')?'text/javascript; charset=utf-8':file.endsWith('.json')?'application/json; charset=utf-8':'application/octet-stream'}
async function file(base, rel){const target=path.resolve(base,rel);if(target!==base&&!target.startsWith(base+path.sep))return new Response('Denied',{status:403});try{return new Response(await fs.readFile(target),{headers:{'content-type':typeOf(target),'cache-control':'no-store'}})}catch{return new Response('Not found',{status:404})}}
let win, done=false; function finish(value){if(done)return;done=true;console.log('PRODUCT_BROWSER_RESULT '+JSON.stringify(value));app.quit()}
protocol.handle('ordessa',async req=>{const url=new URL(req.url);if(url.host!=='desktop'||req.method!=='GET')return new Response('Denied',{status:403});if(url.pathname==='/'||url.pathname==='/index.html')return new Response(page,{headers:{'content-type':'text/html; charset=utf-8','cache-control':'no-store'}});
for(const [prefix,key] of [['/extensions/ordessa.agent-contracts/','agent'],['/extensions/ordessa.chat/','chat'],['/extensions/ordessa.contracts/','contracts']])if(url.pathname.startsWith(prefix))return file(roots[key],decodeURIComponent(url.pathname.slice(prefix.length)));
if(url.pathname==='/shared/api.js')return file(path.dirname(roots.api),path.basename(roots.api));return new Response('Not found',{status:404})});
app.whenReady().then(async()=>{win=new BrowserWindow({show:false,width:700,height:500,webPreferences:{contextIsolation:true,nodeIntegration:false,sandbox:true}});
win.webContents.on('render-process-gone',(_e,d)=>finish({ok:false,error:'renderer process gone',details:d}));win.webContents.on('did-fail-load',(_e,c,d)=>finish({ok:false,error:'renderer load failed',code:c,description:d}));
await win.loadURL('ordessa://desktop/index.html');const until=Date.now()+${timeoutMs};while(!done&&Date.now()<until){const value=await win.webContents.executeJavaScript('window.__closeoutProductResult || null').catch(e=>({ok:false,error:String(e)}));if(value&&Object.hasOwn(value,'ok')){finish(value);return}await new Promise(r=>setTimeout(r,30))}finish({ok:false,error:'browser scenario timed out'})}).catch(e=>finish({ok:false,error:String(e&&e.stack||e)}));`
}

function cleanEnvironment(home, python = false) {
  const env = {
    HOME: home, PATH: process.env.PATH ?? '/usr/bin:/bin',
    XDG_CONFIG_HOME: path.join(home, '.config'), XDG_CACHE_HOME: path.join(home, '.cache'),
    XDG_DATA_HOME: path.join(home, '.local/share'), LANG: 'C.UTF-8', LC_ALL: 'C.UTF-8',
    ELECTRON_RUN_AS_NODE: python ? undefined : '0',
  }
  for (const key of ['DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY']) if (process.env[key]) env[key] = process.env[key]
  if (python) {
    env.PYTHONNOUSERSITE = '1'
    env.ORDESSA_BUNDLED_ROOT = process.env.ORDESSA_BUNDLED_ROOT
  }
  for (const key of Object.keys(env)) if (env[key] === undefined) delete env[key]
  return env
}

function terminateChildTree(child, processGroup = false) {
  if (child.exitCode !== null || child.signalCode !== null) return
  if (processGroup && process.platform !== 'win32' && child.pid) {
    try { process.kill(-child.pid, 'SIGTERM'); return } catch { /* fall back to child handle */ }
  }
  child.kill('SIGTERM')
}

function childLines(child, label) {
  let output = ''
  const waiters = []
  let closed = false
  const collect = chunk => {
    output += chunk.toString()
    for (const waiter of [...waiters]) {
      const found = output.split(/\r?\n/).find(line => line.startsWith(waiter.prefix))
      if (found) { waiters.splice(waiters.indexOf(waiter), 1); waiter.resolve(found.slice(waiter.prefix.length)) }
    }
  }
  child.stdout?.on('data', collect); child.stderr?.on('data', collect)
  const close = new Promise(resolve => child.once('close', (code, signal) => { closed = true; resolve({ code, signal }) }))
  return {
    close, output: () => output,
    waitLine(prefix) {
      if (closed) return Promise.reject(new Error(`${label} closed before ${prefix}: ${output.slice(-4000)}`))
      const found = output.split(/\r?\n/).find(line => line.startsWith(prefix))
      if (found) return Promise.resolve(found.slice(prefix.length))
      return new Promise((resolve, reject) => {
        const timer = setTimeout(() => {
          const waiter = waiters.find(item => item.prefix === prefix && item.resolve === onLine)
          if (waiter) waiters.splice(waiters.indexOf(waiter), 1)
          reject(new Error(`${label} timed out at ${prefix}: ${output.slice(-4000)}`))
        }, timeoutMs)
        const onLine = value => { clearTimeout(timer); resolve(value) }
        waiters.push({ prefix, resolve: onLine, reject })
        close.then(value => {
          if (closed) {
            clearTimeout(timer)
            const waiter = waiters.find(item => item.prefix === prefix && item.resolve === onLine)
            if (waiter) waiters.splice(waiters.indexOf(waiter), 1)
            reject(new Error(`${label} exited before ${prefix}: ${JSON.stringify(value)} ${output.slice(-4000)}`))
          }
        })
      })
    },
  }
}

async function startPython({ python, prefix, fixtureCopy, dataRoot, effectsPath, includeProfile, home, work }) {
  const env = cleanEnvironment(home, true)
  env.ORDESSA_BUNDLED_ROOT = prefix
  env.ORDESSA_DATA_ROOT = dataRoot
  const child = spawn(python, ['-I', '-c', pythonDriverSource(), prefix, fixtureCopy, dataRoot, effectsPath, String(includeProfile)], {
    cwd: work, env, stdio: ['ignore', 'pipe', 'pipe'],
  })
  const lines = childLines(child, 'artifact Python product runtime')
  try {
    const ready = JSON.parse(await lines.waitLine('PRODUCT_READY '))
    assert(ready.port > 0 && ready.includeProfile === includeProfile, 'artifact runtime did not select requested product variant')
    return { child, ...lines, port: ready.port, pluginIds: ready.pluginIds }
  } catch (error) {
    terminateChildTree(child)
    await lines.close
    throw error
  }
}

async function stopPython(processHandle) {
  try { await fetch(`http://127.0.0.1:${processHandle.port}/control/stop`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: '{}' }) } catch { /* process may already be exiting */ }
  let timer
  const closed = await Promise.race([
    processHandle.close,
    new Promise((_, reject) => { timer = setTimeout(() => reject(new Error('artifact Python runtime stop timed out')), timeoutMs) }),
  ]).catch(async error => {
    processHandle.child.kill('SIGTERM')
    await processHandle.close.catch(() => undefined)
    throw error
  }).finally(() => clearTimeout(timer))
  assert(closed.code === 0 && closed.signal === null, `artifact product runtime did not stop cleanly: ${JSON.stringify(closed)} ${processHandle.output().slice(-2000)}`)
}

async function runBrowser({ electron, mainFile, userData, home, label }) {
  const child = spawn(electron, ['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage', mainFile], {
    cwd: path.dirname(mainFile), env: cleanEnvironment(home), detached: process.platform !== 'win32',
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  const lines = childLines(child, label)
  try {
    const result = JSON.parse(await lines.waitLine('PRODUCT_BROWSER_RESULT '))
    const closed = await lines.close
    assert(closed.code === 0 && closed.signal === null, `${label} Electron process did not exit cleanly: ${JSON.stringify(closed)} ${lines.output().slice(-3000)}`)
    assert(result.ok === true, `${label} failed: ${result.error ?? JSON.stringify(result)}`)
    return result
  } finally {
    terminateChildTree(child, true)
  }
}

async function runVariant({ variant, includeProfile, artifact, paths, temp, python, electron }) {
  const root = path.join(temp, variant)
  const dataRoot = path.join(root, 'product-data')
  const effectsPath = path.join(root, 'native-effects.sqlite')
  const userData = path.join(root, 'electron-user-data')
  const warmHome = path.join(root, 'warm-home')
  const coldHome = path.join(root, 'cold-home')
  const work = path.join(root, 'cwd')
  await Promise.all([dataRoot, userData, warmHome, coldHome, work].map(item => mkdir(item, { recursive: true, mode: 0o700 })))
  const dbName = `ordessa.closeout.frontend-product.${variant}.v1`
  const requestPrefix = `closeout-${variant}`
  let warmRuntime
  let coldRuntime
  try {
    warmRuntime = await startPython({ python, prefix: paths.prefix, fixtureCopy: paths.fixtureCopy,
      dataRoot, effectsPath, includeProfile, home: warmHome, work })
    const warmHtml = browserHtml({ port: warmRuntime.port, variant, phase: 'warm', databaseName: dbName, requestPrefix })
    const warmFile = path.join(root, 'warm-main.cjs')
    await writeFile(warmFile, electronMainSource({ userData, html: warmHtml, roots: paths.roots }), { mode: 0o600 })
    const warm = await runBrowser({ electron, mainFile: warmFile, userData, home: warmHome, label: `${variant} warm frontend/product` })
    await stopPython(warmRuntime)
    warmRuntime = undefined

    coldRuntime = await startPython({ python, prefix: paths.prefix, fixtureCopy: paths.fixtureCopy,
      dataRoot, effectsPath, includeProfile, home: coldHome, work })
    const coldHtml = browserHtml({ port: coldRuntime.port, variant, phase: 'cold', databaseName: dbName, requestPrefix, keys: warm.keys })
    const coldFile = path.join(root, 'cold-main.cjs')
    await writeFile(coldFile, electronMainSource({ userData, html: coldHtml, roots: paths.roots }), { mode: 0o600 })
    const cold = await runBrowser({ electron, mainFile: coldFile, userData, home: coldHome, label: `${variant} cold frontend/product recovery` })
    await stopPython(coldRuntime)
    coldRuntime = undefined
    return { variant, includeProfile, pluginIds: warm.pluginIds, warm: warm.rounds, cold: cold.recovered,
    warmWireStats: warm.serverStats, coldWireStats: cold.serverStats,
    boundary: { frontendAndChatAdapter: 'shipped extension artifacts in Chromium; real IndexedDB',
      productOwner: 'artifact Python interpreter and actual ServerProductComposition/runtime.wire.dispatch',
      bridge: 'owned ephemeral 127.0.0.1 HTTP, not production transport',
      controlledSeams: ['ControlledNativeFixture', 'fixture ProtectedFingerprintHmac', 'explicit local test policy'],
      sessionsFacade: 'controlled runtimeGeneration projection only; draft target and binding are backend-issued',
      realModel: false, realBrandConnector: false, chromiumSandbox: 'not established; Electron launched with --no-sandbox' } }
  } finally {
    if (warmRuntime) await stopPython(warmRuntime).catch(() => terminateChildTree(warmRuntime.child))
    if (coldRuntime) await stopPython(coldRuntime).catch(() => terminateChildTree(coldRuntime.child))
  }
}

async function main() {
  const artifact = locate(option('--artifact-root') ?? process.env.ORDESSA_ARTIFACT_ROOT, option('--electron'), option('--python'))
  const agentRoot = await firstDirectory(artifact.agent)
  const chatRoot = await firstDirectory(artifact.chat)
  const contractsRoot = await firstDirectory(artifact.shared)
  const sharedApi = await firstFile(artifact.api)
  const electron = await firstFile(artifact.electron)
  const python = await firstFile(artifact.python)
  const prefix = await firstDirectory(artifact.prefix)
  const report = { schema: 'ordessa.closeout-frontend-product.v1', artifactRoot: artifact.root,
    artifactExports: {}, variants: {}, limitations: [], status: 'fail' }
  if (!agentRoot || !chatRoot || !contractsRoot || !sharedApi || !electron || !python || !prefix
      || !isWithin(electron, artifact.root) || !isWithin(python, artifact.root)) {
    report.artifacts = { agentRoot: !!agentRoot, chatRoot: !!chatRoot, contractsRoot: !!contractsRoot,
      sharedApi: !!sharedApi, electron: !!electron, python: !!python, prefix: !!prefix,
      electronInsideArtifact: !!electron && isWithin(electron, artifact.root),
      pythonInsideArtifact: !!python && isWithin(python, artifact.root) }
    throw Object.assign(new Error('required source-free product artifacts are missing'), { report })
  }
  const agentContract = path.join(agentRoot, 'contract.js')
  const chatAdapter = path.join(chatRoot, 'submission.js')
  const sharedContract = path.join(contractsRoot, 'contract.js')
  const chatManifestPath = path.join(chatRoot, 'manifest.json')
  for (const file of [agentContract, chatAdapter, sharedContract, chatManifestPath]) await access(file)
  const chatManifest = JSON.parse(await readFile(chatManifestPath, 'utf8'))
  report.artifactExports = { agentContract: agentContract, chatAdapter: chatAdapter,
    sharedContract: sharedContract, chatManifestEntry: chatManifest.entry,
    expectedPublicFunctions: ['createWireConfigurationClient', 'createFrontendSubmissionJournal', 'createDurableSubmissionClient', 'createReliableChatSubmission'],
    declaration: 'The current source tree exports these; this runner validates the built artifact at runtime.' }

  const temp = await mkdtemp(path.join(os.tmpdir(), 'ordessa-closeout-frontend-product-'))
  try {
    const fixtureCopy = path.join(temp, 'controlled_native_fixture.py')
    await copyFile(artifact.fixture, fixtureCopy)
    const paths = { prefix, fixtureCopy, roots: { agent: agentRoot, chat: chatRoot, contracts: contractsRoot, api: sharedApi } }
    report.variants.withProfile = await runVariant({ variant: 'withProfile', includeProfile: true, artifact, paths, temp, python, electron })
    report.variants.withoutProfile = await runVariant({ variant: 'withoutProfile', includeProfile: false, artifact, paths, temp, python, electron })
    report.status = 'pass'
  } finally {
    await rm(temp, { recursive: true, force: true })
  }
  return report
}

try {
  const report = await main()
  console.log(JSON.stringify(report, null, 2))
} catch (error) {
  const report = error?.report ?? { schema: 'ordessa.closeout-frontend-product.v1', status: 'fail' }
  report.failure = { type: error?.name ?? 'Error', message: error?.message ?? String(error), stack: error?.stack }
  console.log(JSON.stringify(report, null, 2))
  process.exitCode = 1
}
