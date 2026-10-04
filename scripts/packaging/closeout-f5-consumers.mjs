#!/usr/bin/env node
// Runtime evidence for the packaged F5 surface. This deliberately imports
// only the built application artifact; it does not resolve source packages.
import { spawn } from 'node:child_process'
import { mkdtemp, cp, writeFile, rm, access } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'

const timeoutMs = 25_000
const args = process.argv.slice(2)
function option(name) {
  const at = args.indexOf(name)
  return at >= 0 ? args[at + 1] : undefined
}

function locateArtifactRoot(input) {
  if (!input) throw new Error('usage: closeout-f5-consumers.mjs --artifact-root <extracted /opt/ordessa>')
  const root = path.resolve(input)
  const sharedCandidates = [
    path.join(root, 'app/dist/renderer/shared'),
    path.join(root, 'dist/renderer/shared'),
    path.join(root, 'renderer/shared'),
  ]
  const electronCandidates = [
    path.join(root, 'app/electron'),
    path.join(root, 'electron'),
    path.join(root, 'app/electron-dist/electron'),
    path.join(root, 'electron-dist/electron'),
    path.join(root, 'app/electron/electron'),
    path.join(root, 'electron/electron'),
  ]
  const nativeUiStorageCandidates = [
    path.join(root, 'app/dist/native-ui-storage.cjs'),
    path.join(root, 'dist/native-ui-storage.cjs'),
    path.join(root, 'native-ui-storage.cjs'),
  ]
  return { root, sharedCandidates, electronCandidates, nativeUiStorageCandidates }
}

async function firstExisting(paths) {
  for (const candidate of paths) {
    try { await access(candidate); return candidate } catch { /* keep searching */ }
  }
  return undefined
}

function assert(condition, message) {
  if (!condition) throw new Error(message)
}

async function withTimeout(promise, label, ms = timeoutMs) {
  let timer
  try {
    return await Promise.race([
      promise,
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(`${label} timed out after ${ms}ms`)), ms) }),
    ])
  } finally { clearTimeout(timer) }
}

async function runArtifactApiScene(sharedDir, tempRoot) {
  const runtimeUrl = pathToFileURL(path.join(sharedDir, 'f5-runtime.js')).href
  const apiUrl = pathToFileURL(path.join(sharedDir, 'f5-api.js')).href
  const bridgeUrl = pathToFileURL(path.join(sharedDir, 'f5-bridge.js')).href
  const [runtime, api, bridge] = await Promise.all([
    import(`${runtimeUrl}?consumer=${Date.now()}-runtime`),
    import(`${apiUrl}?consumer=${Date.now()}-api`),
    import(`${bridgeUrl}?consumer=${Date.now()}-bridge`),
  ])

  assert(runtime.stateStoreFactory?.createOwned, 'artifact f5-runtime does not export stateStoreFactory.createOwned')
  assert(api.createSelector && api.selectionReader, 'artifact f5-api is missing selector exports')
  assert(runtime.createTaskScope && runtime.sessionOnlyUiStore && runtime.fileBackedUiStore && runtime.readUiRevision,
    'artifact f5-runtime is missing task/UI-storage exports')
  assert(bridge.createQueryCache && bridge.projectionFromObservable, 'artifact f5-bridge is missing query/projection exports')

  const shallow = Object.freeze({ nested: { rows: ['initial'] } })
  const sharedLeaf = { label: 'shared' }
  const cyclic = { left: sharedLeaf, right: sharedLeaf }
  cyclic.self = cyclic
  const owner = runtime.stateStoreFactory.createOwned({
    frozenAncestor: shallow,
    graph: cyclic,
    selected: 'A',
    other: 0,
  }, { onSubscriberError: cause => errors.push(String(cause?.message ?? cause)) })
  const errors = []
  const readerA = owner.reader()
  const readerB = owner.reader()
  const selected = api.selectionReader(readerA, api.createSelector(snapshot => snapshot.selected))
  assert(Object.isFrozen(owner.getSnapshot().frozenAncestor.nested), 'shallow-frozen ancestor left a mutable descendant')
  assert(Object.isFrozen(owner.getSnapshot().graph.left), 'shared descendant was not frozen')
  assert(owner.getSnapshot().graph.self === owner.getSnapshot().graph, 'cycle identity was not preserved')
  assert(owner.getSnapshot().graph.left === owner.getSnapshot().graph.right, 'shared reference identity was not preserved')

  let aNotifications = 0
  let bNotifications = 0
  let selectedNotifications = 0
  const releaseA = readerA.subscribe(() => { aNotifications += 1 })
  const releaseB = readerB.subscribe(() => { bNotifications += 1 })
  const releaseSelection = selected.subscribe(() => { selectedNotifications += 1 })
  const firstSnapshot = owner.getSnapshot()
  owner.update(snapshot => snapshot)
  assert(owner.getSnapshot() === firstSnapshot, 'no-op update replaced the stable snapshot')
  assert(aNotifications === 0 && bNotifications === 0, 'no-op update notified subscribers')

  owner.updateBatched([
    snapshot => ({ ...snapshot, selected: 'B' }),
    snapshot => ({ ...snapshot, other: snapshot.other + 1 }),
  ])
  assert(aNotifications === 1 && bNotifications === 1, 'one batch did not publish exactly once to both consumers')
  assert(selectedNotifications === 1 && selected.get() === 'B', 'field selector missed or duplicated its relevant change')
  owner.update(snapshot => ({ ...snapshot, other: snapshot.other + 1 }))
  assert(selectedNotifications === 1, 'field selector notified for an unrelated field')

  let survivorNotifications = 0
  releaseA.release()
  releaseA.release()
  owner.update(snapshot => ({ ...snapshot, other: snapshot.other + 1 }))
  survivorNotifications = bNotifications
  assert(aNotifications === 2 && survivorNotifications === 3, 'released consumer or independent consumer lifetime is incorrect')
  releaseB.release()
  releaseSelection.release()

  let throwingSibling = 0
  const bad = readerA.subscribe(() => { throw new Error('consumer-listener-failure') })
  const good = readerB.subscribe(() => { throwingSibling += 1 })
  owner.update(snapshot => ({ ...snapshot, other: snapshot.other + 1 }))
  assert(throwingSibling === 1, 'throwing listener prevented a sibling notification')
  assert(errors.some(message => message.includes('consumer-listener-failure')), 'subscriber exception was not reported')
  bad.release()
  good.release()

  let reentrantChanges = 0
  const runaway = readerA.subscribe(() => {
    reentrantChanges += 1
    owner.update(snapshot => ({ ...snapshot, other: snapshot.other + 1 }))
  })
  owner.update(snapshot => ({ ...snapshot, other: snapshot.other + 1 }))
  runaway.release()
  assert(reentrantChanges > 0 && reentrantChanges < 200, 'reentrant publication was not bounded')
  assert(errors.some(message => message.toLowerCase().includes('limit')), 'bounded reentrant guard did not report its limit')

  const invalid = new Map([['x', 1]])
  let rejectedUnsupported = false
  try { runtime.stateStoreFactory.createOwned({ invalid }) } catch (cause) {
    rejectedUnsupported = cause instanceof TypeError && /plain objects|arrays/i.test(cause.message)
  }
  assert(rejectedUnsupported, 'unsupported mutable object shape was accepted')

  const taskScope = runtime.createTaskScope({ currentGeneration: () => 1 })
  const task = taskScope.run({ activation: 'artifact-consumer', generation: 1 }, async () => 'done')
  taskScope.releaseAll()
  assert((await task.result()).kind === 'cancelled-wait', 'task scope disposal did not settle its waiter')

  const projectionSource = {
    attach(sink) {
      sink.snapshot('r1', { value: 1 })
      return { detach() { detached += 1 } }
    },
  }
  let detached = 0
  const projection = bridge.projectionFromObservable(projectionSource, { scope: 'fixture', generation: 1 })
  projection.close()
  projection.close()
  assert(detached === 1, 'projection close did not detach exactly once')

  const sessionStore = runtime.sessionOnlyUiStore()
  assert(typeof sessionStore.persistenceNote === 'string', 'missing UI adapter did not expose its session-only persistence note')
  const queryCache = bridge.createQueryCache()
  assert(queryCache && typeof queryCache.clearScope === 'function', 'artifact query cache is unusable')
  queryCache.clearScope('fixture')

  return {
    name: 'artifact-api-consumers',
    ok: true,
    evidence: {
      modules: ['f5-runtime.js', 'f5-api.js', 'f5-bridge.js'],
      consumers: 2,
      deepFreezeCycleAndSharedReferences: true,
      shallowFrozenAncestorDescendantFrozen: true,
      stableNoopAndBatchPublication: true,
      fieldSelectorIgnoresUnrelatedState: true,
      independentConsumerRelease: true,
      throwingSubscriberIsolation: true,
      reentrantLimitObserved: reentrantChanges,
      unsupportedShapeRejected: true,
      taskAndProjectionDisposed: true,
      sessionOnlyStorageExplicit: true,
      tempRoot,
    },
  }
}

async function runJsonChild(entry, args, label) {
  const child = spawn(process.execPath, [entry, ...args], { cwd: path.dirname(entry), env: process.env, stdio: ['ignore', 'pipe', 'pipe'] })
  let stdout = ''
  let stderr = ''
  let timedOut = false
  child.stdout.on('data', chunk => { stdout += chunk.toString() })
  child.stderr.on('data', chunk => { stderr += chunk.toString() })
  const timer = setTimeout(() => { timedOut = true; child.kill('SIGKILL') }, timeoutMs)
  try {
    const code = await withTimeout(new Promise((resolve, reject) => {
      child.once('error', reject)
      child.once('close', resolve)
    }), label)
    if (timedOut || code !== 0) throw new Error(`${label} failed (exit=${code}, timedOut=${timedOut}): ${stderr || stdout}`)
    const line = stdout.split(/\r?\n/).find(value => value.startsWith('F5_UI_STORAGE_RESULT '))
    if (!line) throw new Error(`${label} produced no result: ${stderr || stdout}`)
    return JSON.parse(line.slice('F5_UI_STORAGE_RESULT '.length))
  } finally {
    clearTimeout(timer)
    if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL')
  }
}

async function runArtifactFileUiStorageScene({ sharedDir, nativeUiStoragePath, tempRoot }) {
  const runtimePath = path.join(sharedDir, 'f5-runtime.js')
  await access(runtimePath)
  await access(nativeUiStoragePath)
  const runtimeUrl = pathToFileURL(runtimePath).href
  const dataRoot = path.join(tempRoot, 'native-ui-store-data')
  const childEntry = path.join(tempRoot, 'f5-ui-storage-writer.mjs')
  const namespace = {
    pluginNamespace: 'artifact.closeout.layout', workspace: 'artifact-workspace',
    windowOrSharedPurpose: 'shared-layout', schemaVersion: 1,
  }
  const childSource = `
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const runtime = await import(process.argv[2]);
const native = require(process.argv[3]);
const root = process.argv[4];
const revision = process.argv[5];
const width = Number(process.argv[6]);
const ns = ${JSON.stringify(namespace)};
const adapter = native.createFileUiAdapter(root);
const store = runtime.fileBackedUiStore(adapter);
const status = await store.write(ns, 'layout', { width }, { ifRevision: revision });
const currentRevision = await runtime.readUiRevision(adapter, ns, 'layout');
console.log('F5_UI_STORAGE_RESULT ' + JSON.stringify({ status, currentRevision, pid: process.pid }));
`
  await writeFile(childEntry, childSource)

  const runtime = await import(`${runtimeUrl}?consumer=${Date.now()}-ui-storage`)
  const require = createRequire(import.meta.url)
  const native = require(nativeUiStoragePath)
  const adapterA = native.createFileUiAdapter(dataRoot)
  const storeA = runtime.fileBackedUiStore(adapterA)
  const storeB = runtime.fileBackedUiStore(native.createFileUiAdapter(dataRoot))
  const initialStatus = await storeA.write(namespace, 'layout', { width: 100 }, {})
  assert(initialStatus === 'written', 'artifact-backed initial UI preference write failed')
  const baseRevision = await runtime.readUiRevision(adapterA, namespace, 'layout')
  assert(typeof baseRevision === 'string' && baseRevision.length > 0, 'artifact-backed revision is not observable')

  const races = await Promise.all([
    runJsonChild(childEntry, [runtimeUrl, nativeUiStoragePath, dataRoot, baseRevision, '200'], 'UI storage writer A'),
    runJsonChild(childEntry, [runtimeUrl, nativeUiStoragePath, dataRoot, baseRevision, '300'], 'UI storage writer B'),
  ])
  assert(races.filter(answer => answer.status === 'written').length === 1
    && races.filter(answer => answer.status === 'conflict').length === 1,
  `independent artifact processes did not produce one write and one conflict: ${JSON.stringify(races)}`)
  assert(races[0].pid !== races[1].pid, 'CAS race did not use independent child processes')

  const reopened = runtime.fileBackedUiStore(native.createFileUiAdapter(dataRoot))
  const winner = await reopened.read(namespace, 'layout')
  const winningRevision = await runtime.readUiRevision(native.createFileUiAdapter(dataRoot), namespace, 'layout')
  assert([200, 300].includes(winner?.width), 'reopened artifact store did not return the unique winning value')
  assert(winningRevision && winningRevision !== baseRevision, 'winning artifact write did not advance revision')
  assert(races.some(answer => answer.status === 'written' && answer.currentRevision === winningRevision),
    'winning child did not observe the committed revision')

  await storeB.write(namespace, 'other-record', { width: 10 }, {})
  const otherRevision = await runtime.readUiRevision(adapterA, namespace, 'other-record')
  assert(otherRevision && otherRevision !== winningRevision, 'artifact adapter reused a revision across records')
  assert((await storeA.read(namespace, 'other-record'))?.width === 10,
    'independently constructed artifact stores did not share the same host adapter data')

  const unknownSchema = { ...namespace, schemaVersion: 99 }
  const unknownKey = `${unknownSchema.pluginNamespace}|${unknownSchema.workspace}|${unknownSchema.windowOrSharedPurpose}|${unknownSchema.schemaVersion}`
  const seededUnknown = { schemaVersion: 99, value: { width: 50 } }
  const seedResult = await adapterA.compareAndSwap(unknownKey, 'layout', undefined, seededUnknown)
  assert(seedResult.status === 'written', 'could not seed an existing future-schema record in the artifact adapter')
  const unknownBefore = await adapterA.read(unknownKey, 'layout')
  let unknownRefused = false
  try { await storeA.write(unknownSchema, 'layout', { width: 999 }, {}) }
  catch { unknownRefused = true }
  assert(unknownRefused, 'artifact store accepted an unsupported schema')
  assert(JSON.stringify(await adapterA.read(unknownKey, 'layout')) === JSON.stringify(unknownBefore),
    'unsupported schema write changed its preexisting artifact record')

  const otherPlugin = { ...namespace, pluginNamespace: 'artifact.other-plugin' }
  const otherWindow = { ...namespace, windowOrSharedPurpose: 'window-local' }
  await storeA.write(otherPlugin, 'filter', 'plugin-value', {})
  await storeA.write(otherWindow, 'filter', 'window-value', {})
  await storeA.remove(namespace, 'layout')
  assert(await reopened.read(namespace, 'layout') === undefined, 'artifact deletion did not remove the selected record')
  assert(await reopened.read(otherPlugin, 'filter') === 'plugin-value'
    && await reopened.read(otherWindow, 'filter') === 'window-value',
  'artifact deletion crossed plugin or window namespace boundaries')

  let unsafeRefused = false
  try { await storeA.write(namespace, 'unsafe', { nested: { accessToken: 'fixture-secret' } }, {}) }
  catch { unsafeRefused = true }
  assert(unsafeRefused, 'artifact write path accepted a sensitive UI-storage value')
  assert(await adapterA.read(`${namespace.pluginNamespace}|${namespace.workspace}|${namespace.windowOrSharedPurpose}|${namespace.schemaVersion}`, 'unsafe') === undefined,
    'unsafe artifact write persisted a record before the safety guard')

  return {
    name: 'artifact-file-ui-storage', ok: true,
    evidence: {
      modules: ['f5-runtime.js', 'native-ui-storage.cjs'],
      adapterExport: '@ordessa/native-bridge/ui-storage',
      independentWriterPids: races.map(answer => answer.pid),
      sameRevisionRace: races.map(answer => answer.status).sort(),
      reopenedWinnerWidth: winner.width, revisionChanged: true, revisionsUniqueAcrossRecords: true,
      unsupportedSchemaPreserved: true, namespaceIsolationAndDeletion: true,
      sensitiveValueRejectedBeforePersistence: true,
    },
  }
}

function electronMainSource(htmlPath, userData) {
  return `
const { app, BrowserWindow } = require('electron');
const path = require('node:path');
app.setPath('userData', ${JSON.stringify(userData)});
let win;
let finished = false;
const timeout = setTimeout(() => finish({ ok: false, error: 'renderer fixture timed out' }), 18000);
function finish(result) {
  if (finished) return;
  finished = true;
  clearTimeout(timeout);
  console.log('F5_BROWSER_RESULT ' + JSON.stringify(result));
  try { if (win && !win.isDestroyed()) win.close(); } catch {}
  app.quit();
}
app.whenReady().then(async () => {
  win = new BrowserWindow({ show: false, width: 320, height: 200, webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true } });
  win.webContents.on('render-process-gone', (_event, details) => finish({ ok: false, error: 'renderer process gone', details }));
  win.webContents.on('did-fail-load', (_event, code, description) => finish({ ok: false, error: 'renderer load failed', code, description }));
  await win.loadFile(${JSON.stringify(htmlPath)});
  const deadline = Date.now() + 15000;
  while (!finished && Date.now() < deadline) {
    try {
      const result = await win.webContents.executeJavaScript('window.__f5ConsumerResult || null');
      if (result) { finish(result); return; }
    } catch (error) { finish({ ok: false, error: String(error) }); return; }
    await new Promise(resolve => setTimeout(resolve, 40));
  }
  finish({ ok: false, error: 'renderer result deadline exceeded' });
}).catch(error => finish({ ok: false, error: String(error && error.stack || error) }));
`
}

function browserHtml(sharedDir) {
  const imports = {
    '@ordessa/f5/react': pathToFileURL(path.join(sharedDir, 'f5-react.js')).href,
    '@ordessa/f5/runtime': pathToFileURL(path.join(sharedDir, 'f5-runtime.js')).href,
    '@ordessa/react': pathToFileURL(path.join(sharedDir, 'react.js')).href,
    '@ordessa/react-dom/client': pathToFileURL(path.join(sharedDir, 'react-dom-client.js')).href,
  }
  const script = `
import React from '@ordessa/react';
import { createRoot } from '@ordessa/react-dom/client';
import { stateStoreFactory } from '@ordessa/f5/runtime';
import { useStoreSelection } from '@ordessa/f5/react';
const assert = (condition, message) => { if (!condition) throw new Error(message); };
const owner = stateStoreFactory.createOwned({ selected: 'A', unrelated: 0 });
let activeSubscriptions = 0;
const store = {
  getSnapshot: owner.getSnapshot,
  subscribe(listener) {
    activeSubscriptions += 1;
    const handle = owner.subscribe(listener);
    let released = false;
    return { release() { if (released) return; released = true; activeSubscriptions -= 1; handle.release(); } };
  },
};
const selectSelected = snapshot => snapshot.selected;
let renders = 0;
function Consumer() {
  const selected = useStoreSelection(store, selectSelected);
  renders += 1;
  return React.createElement('output', { id: 'selected' }, selected);
}
const root = createRoot(document.getElementById('root'));
const frame = () => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
try {
  root.render(React.createElement(Consumer));
  await frame();
  assert(document.getElementById('selected')?.textContent === 'A', 'initial artifact React render missing');
  assert(renders === 1 && activeSubscriptions === 1, 'initial render/subscription counts incorrect');
  owner.update(snapshot => ({ ...snapshot, unrelated: 1 }));
  await frame();
  assert(renders === 1, 'unrelated field caused a React render');
  owner.update(snapshot => ({ ...snapshot, selected: 'B' }));
  await frame();
  assert(document.getElementById('selected')?.textContent === 'B' && renders === 2, 'selected field did not render once');
  root.unmount();
  await frame();
  assert(activeSubscriptions === 0, 'unmount did not release the artifact store subscription');
  owner.update(snapshot => ({ ...snapshot, selected: 'C' }));
  await frame();
  assert(renders === 2, 'unmounted consumer still rendered');
  window.__f5ConsumerResult = { ok: true, evidence: { consumer: 'artifact React hook', renders, activeSubscriptions, ignoredUnrelatedUpdate: true, unmountReleasedSubscription: true } };
} catch (error) {
  try { root.unmount(); } catch {}
  window.__f5ConsumerResult = { ok: false, error: String(error && error.stack || error), evidence: { renders, activeSubscriptions } };
}
`
  return `<!doctype html><meta charset="utf-8"><div id="root"></div><script type="importmap">${JSON.stringify({ imports })}</script><script type="module">${script}</script>`
}

async function runArtifactReactScene({ sharedDir, electronPath, tempRoot }) {
  const reactArtifactFiles = ['f5-react.js', 'f5-runtime.js', 'react.js', 'react-dom-client.js']
  for (const file of reactArtifactFiles) {
    await access(path.join(sharedDir, file))
  }
  const fixture = path.join(tempRoot, 'electron-consumer')
  const sharedCopy = path.join(fixture, 'shared')
  const htmlPath = path.join(fixture, 'consumer.html')
  const mainPath = path.join(fixture, 'main.cjs')
  const userData = path.join(fixture, 'isolated-user-data')
  await cp(sharedDir, sharedCopy, { recursive: true })
  await writeFile(path.join(fixture, 'package.json'), JSON.stringify({ type: 'module' }))
  await writeFile(htmlPath, browserHtml(sharedCopy))
  await writeFile(mainPath, electronMainSource(htmlPath, userData))

  // Do not inherit a caller's Electron-as-Node override. A literal "0" makes
  // the browser launch mode explicit while preserving other host variables.
  const env = { ...process.env, ELECTRON_RUN_AS_NODE: '0' }
  const child = spawn(electronPath, ['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage', mainPath], {
    cwd: fixture,
    env,
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  let output = ''
  let timedOut = false
  child.stdout.on('data', chunk => { output += chunk.toString() })
  child.stderr.on('data', chunk => { output += chunk.toString() })
  const timer = setTimeout(() => { timedOut = true; child.kill('SIGKILL') }, timeoutMs)
  try {
    const exitCode = await withTimeout(new Promise((resolve, reject) => {
      child.once('error', reject)
      child.once('close', resolve)
    }), 'artifact Electron browser consumer')
    const resultLine = output.split(/\r?\n/).find(line => line.startsWith('F5_BROWSER_RESULT '))
    if (!resultLine) throw new Error(`Electron fixture returned no result (exit=${exitCode}, timeout=${timedOut}): ${output.slice(-5000)}`)
    const result = JSON.parse(resultLine.slice('F5_BROWSER_RESULT '.length))
    if (!result.ok || exitCode !== 0 || timedOut) throw new Error(`Electron artifact consumer failed: ${JSON.stringify(result)}; exit=${exitCode}; timeout=${timedOut}; output=${output.slice(-5000)}`)
    return { name: 'artifact-react-consumer', ok: true, evidence: {
      ...result.evidence, electronPath, browserWindow: 'hidden', sharedArtifactFiles: reactArtifactFiles,
      isolatedUserData: true, launchFlags: ['--no-sandbox', '--disable-gpu', '--disable-dev-shm-usage'],
      chromiumSandbox: 'not proven: this fixture uses --no-sandbox',
    } }
  } finally {
    clearTimeout(timer)
    if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL')
  }
}

async function scene(name, body) {
  try { return await body() }
  catch (cause) { return { name, ok: false, error: String(cause?.stack ?? cause), timedOut: /timed out|deadline/i.test(String(cause?.message ?? cause)) } }
}

const artifact = locateArtifactRoot(option('--artifact-root') ?? process.env.ORDESSA_ARTIFACT_ROOT)
const sharedDir = await firstExisting(artifact.sharedCandidates)
const electronPath = await firstExisting(artifact.electronCandidates)
const nativeUiStoragePath = await firstExisting(artifact.nativeUiStorageCandidates)
const tempRoot = await mkdtemp(path.join(os.tmpdir(), 'ordessa-f5-artifact-consumers-'))
let results
try {
  if (!sharedDir) {
    results = [
      { name: 'artifact-api-consumers', ok: false, error: `shared artifact directory not found under ${artifact.root}` },
      { name: 'artifact-file-ui-storage', ok: false, error: `shared artifact directory not found under ${artifact.root}` },
      { name: 'artifact-react-consumer', ok: false, error: `shared artifact directory not found under ${artifact.root}` },
    ]
  } else {
    const copiedShared = path.join(tempRoot, 'shared')
    await cp(sharedDir, copiedShared, { recursive: true })
    await writeFile(path.join(tempRoot, 'package.json'), JSON.stringify({ type: 'module' }))
    results = []
    results.push(await scene('artifact-api-consumers', () => runArtifactApiScene(copiedShared, tempRoot)))
    if (!nativeUiStoragePath) {
      results.push({ name: 'artifact-file-ui-storage', ok: false, error: `native UI storage artifact not found under ${artifact.root}` })
    } else {
      results.push(await scene('artifact-file-ui-storage', () => runArtifactFileUiStorageScene({
        sharedDir: copiedShared, nativeUiStoragePath, tempRoot,
      })))
    }
    if (!electronPath) {
      results.push({ name: 'artifact-react-consumer', ok: false, error: `Electron artifact not found under ${artifact.root}` })
    } else {
      results.push(await scene('artifact-react-consumer', () => runArtifactReactScene({ sharedDir, electronPath, tempRoot })))
    }
  }
} finally {
  await rm(tempRoot, { recursive: true, force: true })
}

for (const result of results) console.log(JSON.stringify(result))
if (results.some(result => !result.ok)) process.exitCode = 1
