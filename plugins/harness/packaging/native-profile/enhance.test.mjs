import test from 'node:test'
import assert from 'node:assert/strict'
import { enhanceSource } from './enhance.mjs'
import { readFile, mkdtemp, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))
import { build as codex } from '../builders/build-codex-runtime-artifact.mjs'
import { build as claude } from '../builders/build-claude-runtime-artifact.mjs'

test('enhancement refuses upstream content drift and unknown brands', () => {
  for (const brand of ['codex', 'claude-code', 'unknown'])
    assert.throws(() => enhanceSource('export default {}', brand), /source digest mismatch/)
})
test('builder enhancement flags are explicit and cannot upgrade a legacy Claude alias', () => {
  assert.throws(() => codex({ profileBridge: 'true' }), /profileBridge must be boolean/)
  assert.throws(() => claude({ profileBridge: true, variant: 'legacy-alias' }), /canonical Claude/)
})

// The enhanced artifact is a rewritten upstream bundle; it reaches these
// modules only through the generated import line. A renamed or missing export
// would otherwise surface as a runtime failure inside a published artifact.
test('every symbol the enhanced artifact imports is really exported by the staged module', async t => {
  const enhanceSourceText = await readFile(new URL('./enhance.mjs', import.meta.url), 'utf8')
  // Staged file name -> the module this repository actually owns, exactly as
  // enhanceStaging copies it.
  const staged = new Map()
  for (const match of enhanceSourceText.matchAll(/'(ordessa-[a-z-]+\.mjs)': readFileSync\(path\.join\(HERE, ([^)]*)\)/gu)) {
    const parts = [...match[2].matchAll(/'([^']*)'/gu)].map(part => part[1])
    assert.ok(parts.length > 0, `${match[1]} is staged from an unreadable path`)
    staged.set(match[1], path.resolve(HERE, ...parts))
  }
  const imported = new Map()
  for (const match of enhanceSourceText.matchAll(/import \{([^}]*)\} from '\.\/(ordessa-[a-z-]+\.mjs)'/gu)) {
    if (!imported.has(match[2])) imported.set(match[2], new Set())
    for (const name of match[1].split(',').map(name => name.trim()).filter(Boolean)) imported.get(match[2]).add(name)
  }
  // enhanceStaging rewrites some specifiers while staging; model that too.
  const files = enhanceSourceText.slice(enhanceSourceText.indexOf('const files = {'))
  const rewrites = [...files.matchAll(/\.replace\("'([^']*)'", "'([^']*)'"\)/gu)].map(match => [match[1], match[2]])
  assert.ok(rewrites.length > 0)
  // Load the staged graph the way the published artifact sees it: every relative
  // specifier names another staged file, so a missing one is a hard failure.
  const staging = await mkdtemp(path.join(tmpdir(), 'ordessa-staged-graph-'))
  t.after(() => rm(staging, { recursive: true, force: true }))
  for (const [name, local] of staged) {
    let source = await readFile(local, 'utf8')
    for (const [before, after] of rewrites) source = source.split(before).join(after)
    await writeFile(path.join(staging, name), source)
  }
  const load = async name => {
    assert.ok(staged.has(name), `${name} is imported but never staged`)
    return import(pathToFileURL(path.join(staging, name)).href)
  }
  assert.ok(imported.size > 0)
  for (const [stagedName, names] of imported) {
    const namespace = await load(stagedName)
    for (const name of names) {
      assert.ok(name in namespace, `${stagedName} does not export ${name}`)
      assert.notEqual(namespace[name], undefined, `${stagedName} exports ${name} as undefined`)
    }
  }
  // The Native Profile patch depends on these, not only on a matching import.
  const process = await load('ordessa-codex-process.mjs')
  for (const name of ['assertResumedThread', 'stopNativeProcess', 'spawnNativeCodex',
    'resolveNativeCodexBinary', 'assertNativeCodexSpecifier', 'captureCodexHistory',
    'orchestrateCodexReplacement', 'rebindCodexConnection'])
    assert.equal(typeof process[name], 'function', `codex-process.mjs must export ${name}`)
})

// A18: ACP shutdown must release the whole owned native group. The only
// remaining single-pid kill in the Codex branch would be upstream's, so the
// patch must consume it and leave no `.process.kill()` behind.
test('the enhanced ACP shutdown releases the owned native group, never one pid', async () => {
  const enhanceSourceText = await readFile(new URL('./enhance.mjs', import.meta.url), 'utf8')
  // Upstream's single-pid kill survives only as the anchor being consumed, and
  // the replacement written after it must own the whole group.
  assert.equal(enhanceSourceText.split('codexConnection.process.kill()').length - 1, 1)
  assert.ok(enhanceSourceText.split('codexConnection.process.kill()')[0].includes('  process.stdin.on("close", () => {'))
  assert.equal(enhanceSourceText.includes('codexConnection.process.stdin.end();'), true)
  assert.ok(enhanceSourceText.includes('void stopNativeCodexConnection(codexConnection).catch(() => {});'))
  // The group-aware stop and the identity proof are module scope, so the ACP
  // handler and the replacement owner can both reach them.
  assert.ok(enhanceSourceText.includes('\nfunction stopNativeCodexConnection(connection) {'))
  assert.ok(enhanceSourceText.includes('\nasync function assertNativeCodexChild(connection) {'))
  assert.ok(enhanceSourceText.includes('assertNativeProcess(identity.pid, child.ordessaNativeCodex);'))
  // The launcher is never launched: both upstream spawn sites are consumed as
  // anchors and both replacements go through the verified native binary.
  const spawnSites = [...enhanceSourceText.matchAll(/codex = ([^\n]+);/gu)].map(match => match[1])
  const launched = spawnSites.filter(site => site.startsWith('spawnNativeCodex({'))
  const consumed = spawnSites.filter(site => !site.startsWith('spawnNativeCodex({'))
  assert.equal(launched.length, 2)
  assert.equal(consumed.length, 2)
  assert.ok(consumed.some(site => site.includes('spawn(process.execPath, [bundledCodexPath')))
  assert.ok(consumed.some(site => site.includes('shell: true')))
  for (const site of launched) assert.ok(site.includes('nativeBinary:'), site)
})
