#!/usr/bin/env node
// Real Electron/Chromium IndexedDB durability closeout for the Agent-owned
// frontend submission journal. All files and browser profiles are temporary;
// this script serves only built public contract artifacts and never starts a
// Server, Harness, connector, model, or user service.
import { spawn } from 'node:child_process'
import { access, mkdir, mkdtemp, readFile, readdir, realpath, rm, stat, writeFile } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import process from 'node:process'

const timeoutMs = 30_000
const argv = process.argv.slice(2)
function option(name) {
  const index = argv.indexOf(name)
  return index < 0 ? undefined : argv[index + 1]
}

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

function isWithin(file, directory) {
  const relative = path.relative(directory, file)
  return relative === '' || (!relative.startsWith(`..${path.sep}`) && relative !== '..' && !path.isAbsolute(relative))
}

async function assertTreeWithin(root, boundary, seen = new Set()) {
  const resolved = await realpath(root)
  assert(isWithin(resolved, boundary), `artifact member escapes ${boundary}: ${root} -> ${resolved}`)
  if (seen.has(resolved)) return
  seen.add(resolved)
  if (!(await stat(resolved)).isDirectory()) return
  for (const entry of await readdir(resolved)) {
    const child = path.join(resolved, entry)
    const childResolved = await realpath(child)
    assert(isWithin(childResolved, boundary), `artifact member escapes ${boundary}: ${child} -> ${childResolved}`)
    if ((await stat(childResolved)).isDirectory()) await assertTreeWithin(childResolved, boundary, seen)
  }
}

async function firstFile(paths, boundary) {
  for (const candidate of paths) {
    try {
      if (!(await stat(candidate)).isFile()) continue
      const resolved = await realpath(candidate)
      assert(isWithin(resolved, boundary), `artifact file escapes ${boundary}: ${candidate} -> ${resolved}`)
      return resolved
    } catch (error) {
      if (String(error?.message).includes('escapes')) throw error
    }
  }
  return undefined
}

async function firstDirectory(paths, boundary) {
  for (const candidate of paths) {
    try {
      if (!(await stat(candidate)).isDirectory()) continue
      const resolved = await realpath(candidate)
      assert(isWithin(resolved, boundary), `artifact directory escapes ${boundary}: ${candidate} -> ${resolved}`)
      return resolved
    } catch (error) {
      if (String(error?.message).includes('escapes')) throw error
    }
  }
  return undefined
}

function locate(input) {
  if (!input) throw new Error('usage: closeout-frontend-journal.mjs --artifact-root <unpacked deb root containing opt/ordessa>')
  const root = path.resolve(input)
  const prefix = path.join(root, 'opt/ordessa')
  return {
    root, prefix,
    agentContracts: [path.join(prefix, 'app/dist/extensions/ordessa.agent-contracts')],
    sharedContracts: [path.join(prefix, 'app/dist/extensions/ordessa.contracts')],
    sharedApi: [path.join(prefix, 'app/dist/renderer/shared/api.js')],
    electron: [path.join(prefix, 'app/electron')],
  }
}

function fixtureMainSource({ artifactRoots, userData, mode, requestId, expectedState }) {
  const importMap = {
    imports: {
      '@extensions/ordessa.agent-contracts/': '/extensions/ordessa.agent-contracts/',
      '@extensions/ordessa.contracts/': '/extensions/ordessa.contracts/',
      '@ordessa/extension-api': '/shared/api.js',
      '@ordessa/ui-components/api': '/shared/ui-components-api.js',
    },
  }
  const html = `<!doctype html><meta charset="utf-8"><div id="root"></div><script type="importmap">${JSON.stringify(importMap)}</script><script>
window.__frontendJournalErrors = [];
window.__frontendJournalPhase = 'module-import-pending';
window.__frontendJournalIdb = { opens: 0, openState: 'idle', transactions: 0, transactionState: 'idle' };
const nativeOpen = IDBFactory.prototype.open;
IDBFactory.prototype.open = function(...args) {
  window.__frontendJournalIdb.opens += 1;
  window.__frontendJournalIdb.openState = 'pending';
  window.__frontendJournalPhase = 'indexeddb.open:pending';
  const request = nativeOpen.apply(this, args);
  request.addEventListener('blocked', () => { window.__frontendJournalIdb.openState = 'blocked'; window.__frontendJournalPhase = 'indexeddb.open:blocked'; });
  request.addEventListener('upgradeneeded', () => { window.__frontendJournalIdb.openState = 'upgrading'; window.__frontendJournalPhase = 'indexeddb.open:upgradeneeded'; });
  request.addEventListener('success', () => { window.__frontendJournalIdb.openState = 'success'; window.__frontendJournalPhase = 'indexeddb.open:success'; });
  request.addEventListener('error', () => { window.__frontendJournalIdb.openState = 'error'; window.__frontendJournalPhase = 'indexeddb.open:error'; });
  return request;
};
const nativeTransaction = IDBDatabase.prototype.transaction;
IDBDatabase.prototype.transaction = function(...args) {
  window.__frontendJournalIdb.transactions += 1;
  window.__frontendJournalIdb.transactionState = 'pending';
  window.__frontendJournalPhase = 'indexeddb.transaction:pending';
  const transaction = nativeTransaction.apply(this, args);
  transaction.addEventListener('complete', () => { window.__frontendJournalIdb.transactionState = 'complete'; window.__frontendJournalPhase = 'indexeddb.transaction:complete'; });
  transaction.addEventListener('abort', () => { window.__frontendJournalIdb.transactionState = 'abort'; window.__frontendJournalPhase = 'indexeddb.transaction:abort'; });
  transaction.addEventListener('error', () => { window.__frontendJournalIdb.transactionState = 'error'; window.__frontendJournalPhase = 'indexeddb.transaction:error'; });
  return transaction;
};
window.__frontendJournalSetPhase = value => { window.__frontendJournalPhase = value; };
window.addEventListener('error', event => window.__frontendJournalErrors.push({
  kind: 'error', message: event.message || String(event.error || 'renderer error'), filename: event.filename || '',
}));
window.addEventListener('unhandledrejection', event => window.__frontendJournalErrors.push({
  kind: 'unhandledrejection', reason: String(event.reason?.stack || event.reason),
}));
</script><script type="module">
import * as agent from '@extensions/ordessa.agent-contracts/contract.js';
window.__frontendJournalSetPhase('module-imports:complete');
const mode = ${JSON.stringify(mode)};
const requestId = ${JSON.stringify(requestId)};
const expectedState = ${JSON.stringify(expectedState)};
const key = { namespace: 'closeout-environment', principalScope: 'controlled-local', requestId };
const capture = {
  key, target: 'controlled-agent-target:history', guarantee: 'reliable', generation: 3,
  binding: { ownerRef: 'controlled-native-owner', generation: 3 },
  inputSchema: 'agent-input/v1', submissionMode: 'existing',
  draft: { draftId: 'controlled-draft', draftRevision: 4, text: 'temporary QA capture',
    attachmentIds: [], attachmentRefs: [] },
  configOperationIds: [],
};
const report = (value) => { window.__frontendJournalResult = value; };
const requireArtifactApi = () => {
  if (typeof agent.createFrontendSubmissionJournal !== 'function'
      || typeof agent.createDurableSubmissionClient !== 'function') {
    throw new Error('built public Agent contracts artifact lacks the frontend journal/recovery exports');
  }
};
try {
  window.__frontendJournalSetPhase('artifact-api:checking');
  requireArtifactApi();
  window.__frontendJournalSetPhase('artifact-api:ready');
  window.__frontendJournalSetPhase('journal.create:starting');
  const journal = agent.createFrontendSubmissionJournal({ databaseName: 'ordessa.closeout.frontend-submission.v1' });
  window.__frontendJournalSetPhase('journal.create:returned');
  if (mode === 'capture-crash' || mode === 'marker-crash') {
    window.__frontendJournalSetPhase('journal.capture:waiting');
    const captured = await journal.capture(capture);
    window.__frontendJournalSetPhase('journal.capture:resolved');
    if (captured.status !== 'created' || captured.record.state !== 'captured')
      throw new Error('capture transaction did not commit a new captured record');
    if (mode === 'marker-crash') {
      window.__frontendJournalSetPhase('journal.markPossiblySubmitted:waiting');
      const claim = await journal.markPossiblySubmitted(key);
      window.__frontendJournalSetPhase('journal.markPossiblySubmitted:resolved');
      if (claim.status !== 'dispatch-authorized' || claim.record.state !== 'possibly-submitted')
        throw new Error('possibly-submitted transaction did not commit its dispatch marker');
    }
    window.__frontendJournalSetPhase('journal.get-after-write:waiting');
    const persisted = await journal.get(key);
    window.__frontendJournalSetPhase('journal.get-after-write:resolved');
    const stage = mode === 'capture-crash' ? 'captured' : 'possibly-submitted';
    if (persisted?.state !== stage) throw new Error('journal record was not visible after its commit promise resolved');
    window.__frontendJournalStage = { ok: true, stage, requestId, state: persisted.state };
  } else {
    window.__frontendJournalSetPhase('journal.get-cold-record:waiting');
    const record = await journal.get(key);
    window.__frontendJournalSetPhase('journal.get-cold-record:resolved');
    if (!record || record.state !== expectedState || record.target !== capture.target
        || record.key.namespace !== key.namespace || record.key.principalScope !== key.principalScope
        || record.key.requestId !== requestId) {
      throw new Error('cold Chromium process did not recover the original committed mapping');
    }
    const calls = [];
    const client = agent.createDurableSubmissionClient({ journal, wire: async (method, params) => {
      calls.push({ method, params });
      if (method !== 'agent.submission.query')
        throw new Error('controlled recovery wire permits query only; submit is forbidden');
      if (params.target !== capture.target || params.submissionId !== requestId)
        throw new Error('recovery did not query the original frozen target and request key');
      return { kind: 'Unknown', reason: 'controlled fixture has no backend receipt' };
    } });
    window.__frontendJournalSetPhase('reconcile:waiting');
    const answer = await client.reconcile(key);
    window.__frontendJournalSetPhase('reconcile:resolved');
    window.__frontendJournalSetPhase('journal.get-after-reconcile:waiting');
    const after = await journal.get(key);
    window.__frontendJournalSetPhase('journal.get-after-reconcile:resolved');
    if (answer.status !== 'unknown') throw new Error('unavailable backend evidence must remain unknown');
    if (calls.length !== 1 || calls[0].method !== 'agent.submission.query')
      throw new Error('recovery must make exactly one query-only wire call');
    if (calls[0].params.target !== record.target || calls[0].params.submissionId !== record.key.requestId)
      throw new Error('recovery query identity differs from the persisted original key');
    if (!after || after.target !== record.target || after.key.requestId !== record.key.requestId
        || after.state !== expectedState) {
      throw new Error('unknown query changed or discarded the original dispatch state');
    }
    if (after.results.some(result => result.outcome !== 'unknown'))
      throw new Error('controlled unknown query fabricated an authoritative result');
    await journal.dispose();
    report({ ok: true, mode, stateBeforeQuery: record.state, stateAfterQuery: after.state,
      originalTarget: record.target, originalRequestId: record.key.requestId,
      answer: answer.status, calls: calls.map(call => call.method), results: after.results.length });
  }
} catch (error) {
  report({ ok: false, phase: window.__frontendJournalPhase, idb: window.__frontendJournalIdb,
    error: String(error && error.stack || error) });
}
</script>`

  return `
const { app, BrowserWindow, protocol } = require('electron');
const fs = require('node:fs/promises');
const path = require('node:path');
protocol.registerSchemesAsPrivileged([{ scheme: 'ordessa', privileges: {
  standard: true, secure: true, supportFetchAPI: true, corsEnabled: true,
} }]);
app.setPath('userData', ${JSON.stringify(userData)});
const roots = ${JSON.stringify(artifactRoots)};
const page = ${JSON.stringify(html)};
function contentType(filename) {
  if (filename.endsWith('.js') || filename.endsWith('.mjs')) return 'text/javascript; charset=utf-8';
  if (filename.endsWith('.json')) return 'application/json; charset=utf-8';
  if (filename.endsWith('.css')) return 'text/css; charset=utf-8';
  return 'application/octet-stream';
}
async function serveFile(base, relative) {
  const target = path.resolve(base, relative);
  if (target !== base && !target.startsWith(base + path.sep)) return new Response('Denied', { status: 403 });
  try { return new Response(await fs.readFile(target), { headers: { 'content-type': contentType(target), 'cache-control': 'no-store' } }); }
  catch { return new Response('Not found', { status: 404 }); }
}
let win;
let finished = false;
function finish(result) {
  if (finished) return;
  finished = true;
  console.log('FJ_COLD_RESULT ' + JSON.stringify(result));
  app.quit();
}
app.whenReady().then(async () => {
  protocol.handle('ordessa', async request => {
    const url = new URL(request.url);
    if (url.host !== 'desktop' || request.method !== 'GET') return new Response('Denied', { status: 403 });
    if (url.pathname === '/' || url.pathname === '/index.html') return new Response(page, { headers: { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' } });
    if (url.pathname.startsWith('/extensions/ordessa.agent-contracts/'))
      return serveFile(roots.agent, decodeURIComponent(url.pathname.slice('/extensions/ordessa.agent-contracts/'.length)));
    if (url.pathname.startsWith('/extensions/ordessa.contracts/'))
      return serveFile(roots.sharedContracts, decodeURIComponent(url.pathname.slice('/extensions/ordessa.contracts/'.length)));
    if (url.pathname.startsWith('/shared/'))
      return serveFile(roots.shared, decodeURIComponent(url.pathname.slice('/shared/'.length)));
    return new Response('Not found', { status: 404 });
  });
  win = new BrowserWindow({ show: false, width: 420, height: 240, webPreferences: {
    contextIsolation: true, nodeIntegration: false, sandbox: true, backgroundThrottling: false,
  } });
  win.webContents.on('render-process-gone', (_event, details) => finish({ ok: false, error: 'renderer process gone', details }));
  win.webContents.on('did-fail-load', (_event, code, description) => finish({ ok: false, error: 'renderer load failed', code, description }));
  const consoleErrors = [];
  win.webContents.on('console-message', (_event, detailsOrLevel, message, lineNumber, sourceId) => {
    const item = typeof detailsOrLevel === 'object' && detailsOrLevel !== null
      ? detailsOrLevel : { level: detailsOrLevel, message, lineNumber, sourceId };
    const level = item.level ?? item.type;
    if (level === 2 || level === 'error' || level === 'ERROR') consoleErrors.push({
      message: item.message ?? String(message ?? ''), lineNumber: item.lineNumber ?? lineNumber,
      sourceId: item.sourceId ?? sourceId, level,
    });
  });
  await win.loadURL('ordessa://desktop/index.html');
  const deadline = Date.now() + 20000;
  while (!finished && Date.now() < deadline) {
    const state = await win.webContents.executeJavaScript('({ value: window.__frontendJournalStage || window.__frontendJournalResult || null, rendererErrors: window.__frontendJournalErrors || [], phase: window.__frontendJournalPhase || null, idb: window.__frontendJournalIdb || null })').catch(error => ({ value: { ok: false, error: String(error) }, rendererErrors: [], phase: null, idb: null }));
    const value = state.value || (state.rendererErrors.length ? { ok: false, error: 'renderer error event', rendererErrors: state.rendererErrors, consoleErrors, phase: state.phase, idb: state.idb } : null);
    if (value && value.stage) {
      console.log('FJ_CRASH_READY ' + JSON.stringify(value));
      // Parent will SIGKILL this Electron process group only after the IndexedDB
      // transaction completed and the renderer observed its committed state.
      await new Promise(() => {});
    }
    if (value && Object.hasOwn(value, 'ok')) { finish(value); return; }
    await new Promise(resolve => setTimeout(resolve, 30));
  }
  const rendererState = await win.webContents.executeJavaScript('({ errors: window.__frontendJournalErrors || [], phase: window.__frontendJournalPhase || null, idb: window.__frontendJournalIdb || null })').catch(error => ({ inspectionError: String(error) }));
  finish({ ok: false, error: 'frontend journal renderer did not reach a barrier/result', phase: rendererState.phase ?? null,
    idb: rendererState.idb ?? null, rendererErrors: rendererState.errors ?? [], consoleErrors });
}).catch(error => finish({ ok: false, error: String(error && error.stack || error) }));
`
}

function minimalEnvironment(tempHome) {
  const env = {
    PATH: process.env.PATH ?? '', HOME: tempHome,
    XDG_CONFIG_HOME: path.join(tempHome, '.config'),
    XDG_CACHE_HOME: path.join(tempHome, '.cache'),
  }
  delete env.ELECTRON_RUN_AS_NODE
  for (const name of ['DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY', 'LANG']) {
    if (process.env[name] !== undefined) env[name] = process.env[name]
  }
  return env
}

async function startElectron(executable, mainFile, tempHome, label) {
  const child = spawn(executable, ['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage', mainFile], {
    cwd: path.dirname(mainFile), env: minimalEnvironment(tempHome), detached: process.platform !== 'win32',
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  let output = ''
  let closed = false
  const waiters = []
  const consume = chunk => {
    output += chunk.toString()
    for (const waiter of [...waiters]) {
      const line = output.split(/\r?\n/).find(value => value.startsWith(waiter.prefix))
      if (line) {
        waiters.splice(waiters.indexOf(waiter), 1)
        waiter.resolve(line.slice(waiter.prefix.length))
      }
    }
  }
  child.stdout.on('data', consume)
  child.stderr.on('data', consume)
  const close = new Promise(resolve => child.once('close', (code, signal) => { closed = true; resolve({ code, signal }) }))
  const waitLine = async prefix => {
    if (closed) throw new Error(`${label} exited before ${prefix}: ${output.slice(-5000)}`)
    const existing = output.split(/\r?\n/).find(value => value.startsWith(prefix))
    if (existing) return existing.slice(prefix.length)
    let timer
    try {
      return await Promise.race([
        new Promise((resolve, reject) => waiters.push({ prefix, resolve, reject })),
        new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(`${label} timed out waiting for ${prefix}: ${output.slice(-5000)}`)), timeoutMs) }),
        close.then(({ code, signal }) => { throw new Error(`${label} exited (code=${code}, signal=${signal}) before ${prefix}: ${output.slice(-5000)}`) }),
      ])
    } finally { clearTimeout(timer) }
  }
  return {
    child, close, waitLine,
    async killGroup() {
      if (closed) return close
      try {
        if (process.platform !== 'win32') process.kill(-child.pid, 'SIGKILL')
        else child.kill('SIGKILL')
      } catch (error) {
        if (error?.code !== 'ESRCH') throw error
      }
      return close
    },
    output: () => output,
  }
}

async function runCrashWindow({ electron, mainFile, home, mode, requestId, expectedStage }) {
  const processHandle = await startElectron(electron, mainFile, home, mode)
  const stage = JSON.parse(await processHandle.waitLine('FJ_CRASH_READY '))
  assert(stage.ok === true && stage.stage === expectedStage && stage.requestId === requestId,
    `${mode} did not reach the intended committed IndexedDB stage: ${JSON.stringify(stage)}`)
  const closed = await processHandle.killGroup()
  assert(closed.signal === 'SIGKILL', `${mode} process group did not end by SIGKILL: ${JSON.stringify(closed)}`)
  return { mode, requestId, stage: stage.stage, parentKilledProcessGroup: true, signal: closed.signal }
}

async function runColdRecovery({ electron, mainFile, home, mode, requestId, expectedState }) {
  const processHandle = await startElectron(electron, mainFile, home, mode)
  const cold = JSON.parse(await processHandle.waitLine('FJ_COLD_RESULT '))
  const closed = await processHandle.close
  assert(closed.code === 0 && closed.signal === null, `${mode} cold recovery process did not exit cleanly: ${JSON.stringify(closed)} ${processHandle.output().slice(-3000)}`)
  assert(cold.ok === true, `${mode} cold recovery failed: ${JSON.stringify(cold)}`)
  assert(cold.mode === mode && cold.stateBeforeQuery === expectedState && cold.stateAfterQuery === expectedState,
    `${mode} lost or changed its original journal state: ${JSON.stringify(cold)}`)
  assert(cold.originalRequestId === requestId, `${mode} queried another request identity`)
  assert(JSON.stringify(cold.calls) === JSON.stringify(['agent.submission.query']),
    `${mode} attempted dispatch or did not query once: ${JSON.stringify(cold.calls)}`)
  return { mode, state: cold.stateBeforeQuery, requestId: cold.originalRequestId,
    answer: cold.answer, calls: cold.calls, unknownResultCount: cold.results,
    coldProcessExit: closed.code }
}

const artifact = locate(option('--artifact-root') ?? process.env.ORDESSA_ARTIFACT_ROOT)
assert(!argv.includes('--electron'), 'artifact acceptance does not allow an external Electron override')
artifact.root = await realpath(artifact.root)
const prefix = await realpath(artifact.prefix)
assert(isWithin(prefix, artifact.root) && path.basename(prefix) === 'ordessa',
  `expected unpacked artifact prefix at ${artifact.prefix}`)
const agentRoot = await firstDirectory(artifact.agentContracts, prefix)
const sharedContractsRoot = await firstDirectory(artifact.sharedContracts, prefix)
const sharedApi = await firstFile(artifact.sharedApi, prefix)
const electron = await firstFile(artifact.electron, prefix)
assert(agentRoot, `built Agent contracts artifact missing under ${artifact.root}`)
assert(sharedContractsRoot, `built shared contracts artifact missing under ${artifact.root}`)
assert(sharedApi, `built extension API artifact missing under ${artifact.root}`)
assert(electron, `packaged Electron executable missing under ${artifact.root}`)
for (const tree of [agentRoot, sharedContractsRoot, path.dirname(sharedApi)]) await assertTreeWithin(tree, prefix)
for (const modulePath of [
  path.join(agentRoot, 'contract.js'),
  path.join(sharedContractsRoot, 'contract.js'),
]) await access(modulePath)

const tempRoot = await mkdtemp(path.join(os.tmpdir(), 'ordessa-frontend-journal-kill-'))
const artifactRoots = { agent: agentRoot, sharedContracts: sharedContractsRoot, shared: path.dirname(sharedApi), sharedApi }
const scenarios = [
  { crashMode: 'capture-crash', coldMode: 'recover-capture', stage: 'captured', id: 'closeout-capture-window' },
  { crashMode: 'marker-crash', coldMode: 'recover-marker', stage: 'possibly-submitted', id: 'closeout-marker-window' },
]
const results = []
try {
  for (const scenario of scenarios) {
    const profile = path.join(tempRoot, scenario.id, 'user-data')
    const fixtureHome = path.join(tempRoot, scenario.id, 'home')
    await Promise.all([
      mkdir(profile, { recursive: true, mode: 0o700 }),
      mkdir(fixtureHome, { recursive: true, mode: 0o700 }),
    ])
    const mainFile = path.join(tempRoot, `${scenario.id}.cjs`)
    const mainSource = fixtureMainSource({
      artifactRoots, userData: profile, mode: scenario.crashMode,
      requestId: scenario.id, expectedState: scenario.stage,
    })
    await writeFile(mainFile, mainSource, { mode: 0o600 })
    const killed = await runCrashWindow({
      electron, mainFile, home: fixtureHome, mode: scenario.crashMode,
      requestId: scenario.id, expectedStage: scenario.stage,
    })

    const recoveryMain = path.join(tempRoot, `${scenario.id}-recovery.cjs`)
    await writeFile(recoveryMain, fixtureMainSource({
      artifactRoots, userData: profile, mode: scenario.coldMode,
      requestId: scenario.id, expectedState: scenario.stage,
    }), { mode: 0o600 })
    const recovered = await runColdRecovery({
      electron, mainFile: recoveryMain, home: fixtureHome, mode: scenario.coldMode,
      requestId: scenario.id, expectedState: scenario.stage,
    })
    results.push({ crashWindow: killed, recovery: recovered })
  }
} finally {
  await rm(tempRoot, { recursive: true, force: true })
}

console.log(JSON.stringify({
  name: 'frontend-submission-journal-real-indexeddb-kill-windows',
  ok: true,
  evidence: {
    source: 'built public ordessa.agent-contracts/contract.js artifact',
    indexedDb: 'real Chromium IndexedDB; strict transactions; no injected storage port',
    origin: 'ordessa://desktop',
    sameUserDataAcrossEachCrashAndColdRestart: true,
    parentSigkill: true,
    recoveryCoordinator: 'createDurableSubmissionClient.reconcile',
    controlledWire: 'query-only stub; no Server/native/model process started',
    noResend: true,
    electron,
    launchFlags: ['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage'],
    chromiumSandbox: 'not proven: fixture uses --no-sandbox; BrowserWindow sandbox option is true',
    windows: results,
  },
}))
