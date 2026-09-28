// T018 (FR-009 "契约归属") — products/desktop guard: the ownership wall between
// the platform and the Agent domain cannot silently fall back after the domain
// carrier moved out of the platform umbrella (packages/desktop-platform/
// contracts/{agent,connections,agent-ui} → plugins/agent/contracts, carrier id
// 'ordessa.agent-contracts' unchanged). Against REAL sources and REAL builds:
//   1. platform-purity (structural): no Agent/Chat domain type/token/kind is
//      DECLARED anywhere under packages/desktop-platform/** (frozen name list);
//   2. no reverse re-export: no platform source imports, re-exports or requires
//      a plugins/** path, the '@extensions/ordessa.agent-*' channel, or a
//      relative specifier escaping the platform root (except the C4-carried
//      workbench-api channel the foundation carrier exists to re-export);
//   3. the moved package is really where the plan says, with persistent ids
//      (FR-011), and no stub directory was left behind in the umbrella;
//   4. in a real build each watched Agent token/kind is constructed exactly
//      once, in the DOMAIN carrier, and the PLATFORM carrier constructs no
//      domain literal at all (CN-08 machinery reused via token-scan.mjs);
//   5. FR-009's last clause domain-side: with the three Agent implementation
//      extensions removed from the enabled list the build still succeeds, the
//      implementation dirs are absent, and the built domain carrier still
//      imports as a usable Agent API — all without perturbing the real
//      products/desktop/dist or extensions.lock.json (digest before/after).
// Run: node --test products/desktop/tests/contract-ownership.test.mjs
import assert from 'node:assert/strict'
import { execFile } from 'node:child_process'
import { mkdtemp, readFile, readdir, rm, stat, writeFile } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import { pathToFileURL } from 'node:url'
import { register } from 'node:module'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'
import { promisify } from 'node:util'
import {
  KIND_WATCHLIST, scanDirsForKindConstructions, TOKEN_WATCHLIST,
  scanDirsForTokenConstructions,
} from '../../../packages/workbench/tests/token-scan.mjs'
import { acquireRealBuildLock } from '../../../tooling/real-build-lock.mjs'

const runAsync = promisify(execFile)
const repoRoot = path.resolve(import.meta.dirname, '..', '..', '..')
const productFile = path.join(repoRoot, 'products/desktop/extensions.json')
const buildAll = path.join(repoRoot, 'tooling/build-all.mjs')
const buildApp = path.join(repoRoot, 'apps/desktop/scripts/build.mjs')
const platformRoot = path.join(repoRoot, 'packages/desktop-platform')
const umbrellaRoot = path.join(platformRoot, 'contracts')
const domainCarrierRoot = path.join(repoRoot, 'plugins/agent/contracts')
const realExtensionsRoot = path.join(repoRoot, 'products/desktop/dist/extensions')
const lockFile = path.join(repoRoot, 'products/desktop/extensions.lock.json')

const DOMAIN_CARRIER_ID = 'ordessa.agent-contracts'
// The three Agent IMPLEMENTATION extensions; FR-009's last clause removes them
// while the domain carrier stays enabled.
const AGENT_IMPLEMENTATION_IDS = ['ordessa.agent-connections', 'ordessa.agent-sessions', 'ordessa.agent-conversation']

// Frozen Agent/Chat domain declaration names — the exported interface/type/
// const/function names of the real domain carrier sources
// plugins/agent/contracts/src/{agent,connections}.ts at T018 time. This list
// is FROZEN: growing the domain API means editing this guard deliberately, and
// a platform source DECLARING any of these (or constructing an 'ordessa.agent*'
// token/kind literal) is an FR-009 breach.
const FROZEN_DOMAIN_NAMES = [
  'AgentCapabilities', 'AgentClient', 'AgentClientConnectionKind', 'AgentConnectionInfo',
  'AgentConnectionWorkspace', 'AgentConnections', 'AgentConnectionsToken', 'AgentConnector',
  'AgentInteraction', 'AgentMessage', 'AgentOption', 'AgentReleaseState', 'AgentReleaseStatus',
  'AgentSessionInfo', 'AgentSessions', 'AgentSessionsToken', 'AgentSnapshot', 'AgentToolCall',
  'AgentWorkspaceInfo', 'AgentWorkspaceSnapshot', 'Availability', 'ConnectionStatus',
  'InteractionAnswer', 'RunStatus', 'hasAwaitingInteraction', 'hasOpenRun',
]

// Specifier channels the platform is allowed (and expected) to use toward the
// shared contract carriers and platform-owned API packages: '@extensions/
// ordessa.contracts/' is the platform carrier channel, '@ordessa/extension-api'
// the host API, '@ordessa/connections' the C6 platform API, '@ordessa/workbench'
// the C4 API package. Anything else reaching a domain package is a violation;
// the relative-path twin of the workbench channel is whitelisted per-suffix in
// the escape check below.
const ALLOWED_CHANNELS = ['@ordessa/extension-api', '@ordessa/connections', '@ordessa/workbench', '@extensions/ordessa.contracts/']
// The documented platform-root escape the foundation carrier re-exports (C4):
// '../../../../workbench/api/workbench' from contracts/foundation/src.
const WORKBENCH_API_ROOT = path.join(repoRoot, 'packages/workbench/api')

/** Every *.ts/*.tsx source under packages/desktop-platform/**, excluding
 * installed/built output and tests/ directories (a wall test must be allowed
 * to NAME what it forbids). */
async function platformSources() {
  const found = []
  async function walk(dir) {
    for (const entry of await readdir(dir, { withFileTypes: true })) {
      if (entry.name === 'node_modules' || entry.name === 'dist' || entry.name === 'tests' || entry.name === 'test') continue
      const file = path.join(dir, entry.name)
      if (entry.isDirectory()) await walk(file)
      else if (/\.[cm]?tsx?$/.test(entry.name)) found.push({ file, source: await readFile(file, 'utf8') })
    }
  }
  await walk(platformRoot)
  return found
}

const sources = await platformSources()
// Fail loudly at load if the roots changed: both source scans would otherwise
// pass vacuously over an empty file list.
assert.ok(sources.length >= 15, `only ${sources.length} platform sources scanned — packages/desktop-platform layout changed; fix this guard's roots, do not let it pass empty`)

// --- test 1: platform source purity (FR-009 / CN-01 structural) -------------
test('no Agent/Chat domain type or token is declared under packages/desktop-platform', async () => {
  const declarations = FROZEN_DOMAIN_NAMES.map(name => [name, new RegExp(`export\\s+(?:declare\\s+)?(?:abstract\\s+)?(?:interface|type|const|enum|class|function)\\s+${name}\\b`)])
  const violations = []
  for (const { file, source } of sources) {
    const name = path.relative(repoRoot, file)
    const lines = source.split('\n')
    for (let i = 0; i < lines.length; i++) {
      for (const [domainName, re] of declarations) {
        if (re.test(lines[i])) violations.push(`${name}:${i + 1} declares domain name '${domainName}': ${lines[i].trim()}`)
      }
      // A domain token/kind literal constructed anywhere in the platform is a
      // breach even under a different binding name.
      if (/(?:new\s+Token\b|createConnectionKind\b)(?:<[^()]*>)?\s*\(\s*(['"])ordessa\.agent/.test(lines[i])) {
        violations.push(`${name}:${i + 1} constructs a domain ('ordessa.agent*') token/kind literal: ${lines[i].trim()}`)
      }
    }
  }
  assert.deepEqual(violations, [], 'FR-009: public contracts belong to their owner — Agent-domain declarations leaked back into the platform (every breach listed above)')
})

// --- test 2: no reverse re-export (source side) -----------------------------
test('no platform source imports or re-exports a domain carrier path', async () => {
  // import/export ...from '…', require('…'), dynamic import('…') — including
  // bare `export * from`, which is how a reverse re-export would appear.
  const specifierRe = /(?:\bfrom|\brequire\s*\(|\bimport\s*\()\s*(['"])((?:[^'\\\n])*)\1/g
  const insidePlatform = resolved => resolved === platformRoot || resolved.startsWith(platformRoot + path.sep)
  const violations = []
  for (const { file, source } of sources) {
    const name = path.relative(repoRoot, file)
    for (const [, , specifier] of source.matchAll(specifierRe)) {
      if (ALLOWED_CHANNELS.some(channel => specifier === channel || specifier.startsWith(channel))) continue
      if (/(?:^|\/)plugins\//.test(specifier)) {
        violations.push(`${name} references '${specifier}' — escapes into a plugins/** package`)
      } else if (specifier.startsWith('@extensions/ordessa.agent')) {
        violations.push(`${name} references '${specifier}' — reverse re-export of the domain carrier channel`)
      } else if (specifier.startsWith('.')) {
        const resolved = path.resolve(path.dirname(file), specifier)
        // The foundation carrier's C4 re-export of the platform-owned workbench
        // API is the single whitelisted escape; every other relative path must
        // stay inside packages/desktop-platform/.
        if (!insidePlatform(resolved) && !resolved.startsWith(WORKBENCH_API_ROOT + path.sep)) {
          violations.push(`${name} references '${specifier}' which resolves outside packages/desktop-platform/ (${path.relative(repoRoot, resolved)})`)
        }
      }
    }
  }
  assert.deepEqual(violations, [], 'FR-009: the platform must not reverse re-export a domain API (every breach listed above)')
})

// --- test 3: domain ownership is where the plan says it is ------------------
test('the domain carrier lives in plugins/agent/contracts with its persistent ids', async () => {
  assert.ok(existsSync(path.join(domainCarrierRoot, 'src/contract.ts')), 'plugins/agent/contracts/src/contract.ts (the moved carrier) must exist')
  const umbrella = (await readdir(umbrellaRoot, { withFileTypes: true })).filter(e => e.isDirectory()).map(e => e.name).sort()
  for (const gone of ['agent', 'connections', 'agent-ui']) {
    assert.ok(!umbrella.includes(gone), `packages/desktop-platform/contracts/${gone} was migrated away — it must not come back as a stub`)
  }
  assert.deepEqual(umbrella, ['commands', 'foundation'], 'the platform umbrella must hold exactly the platform carriers commands/ + foundation/')
  const manifest = JSON.parse(await readFile(path.join(domainCarrierRoot, 'manifest.json'), 'utf8'))
  assert.equal(manifest.id, DOMAIN_CARRIER_ID, 'the carrier extension id must survive the move (FR-011 persistent ids)')
  const pkg = JSON.parse(await readFile(path.join(domainCarrierRoot, 'package.json'), 'utf8'))
  assert.equal(pkg.name, '@ordessa/agent-contracts', 'the moved package name must be @ordessa/agent-contracts')
  assert.equal(pkg.ordessa?.id, DOMAIN_CARRIER_ID, 'package ordessa.id must still be the carrier extension id')
})

// --- real-build machinery (variant mechanics mirrored from the CN-08 guard) --

/** sha256 per file across a tree, keyed by path relative to dir. */
async function digestTree(dir) {
  const { createHash } = await import('node:crypto')
  const files = {}
  async function walk(sub) {
    for (const entry of await readdir(sub, { withFileTypes: true })) {
      const file = path.join(sub, entry.name)
      if (entry.isDirectory()) await walk(file)
      else files[path.relative(dir, file).split(path.sep).join('/')] = createHash('sha256').update(await readFile(file)).digest('hex')
    }
  }
  await walk(dir)
  return files
}

// Fresh real build (shared output, locked against the sibling product guards),
// then snapshot real dist + lock so the "variant builds clobber nothing"
// assertion at the end has a reference from the same source state.
const releaseBuildLock = await acquireRealBuildLock(repoRoot)
let snapshot
try {
  await runAsync(process.execPath, [buildApp], { cwd: repoRoot, stdio: 'inherit' })
  snapshot = { lock: await readFile(lockFile, 'utf8'), dist: await digestTree(realExtensionsRoot) }
} catch (error) {
  await releaseBuildLock()
  throw error
}
test.after(() => releaseBuildLock())

// Node has no browser import map. Resolve the two host API channels to the
// actual app shared entries and extension channels to sibling bundles.
const sharedRoot = path.join(repoRoot, 'apps/desktop/dist/renderer/shared')
for (const name of ['api.js', 'ui-components-api.js']) {
  assert.ok(existsSync(path.join(sharedRoot, name)), `missing app shared entry ${name}; build apps/desktop first`)
}
{
  register('data:text/javascript,' + encodeURIComponent(`
export async function resolve(specifier, context, next) {
  if (specifier === '@ordessa/extension-api') return { url: ${JSON.stringify(pathToFileURL(path.join(sharedRoot, 'api.js')).href)}, shortCircuit: true }
  if (specifier === '@ordessa/ui-components/api') return { url: ${JSON.stringify(pathToFileURL(path.join(sharedRoot, 'ui-components-api.js')).href)}, shortCircuit: true }
  if (specifier.startsWith('@extensions/') && context.parentURL?.startsWith('file:')) {
    const base = new URL(context.parentURL).href.replace(/\\/extensions\\/[^?#]*$/, '/extensions/')
    return { url: base + specifier.slice('@extensions/'.length), shortCircuit: true }
  }
  return next(specifier, context)
}`))
}

async function runVariantBuild({ manifest, outputRoot }) {
  try {
    const { stdout } = await runAsync(process.execPath, [buildAll], {
      cwd: repoRoot,
      env: { ...process.env, ...(manifest ? { ORDESSA_PRODUCT_MANIFEST: manifest } : {}), ORDESSA_PRODUCT_OUTPUT_ROOT: outputRoot },
    })
    return { code: 0, stdout }
  } catch (error) {
    return { code: error.code ?? 1, stdout: `${error.stdout ?? ''}${error.stderr ?? ''}` }
  }
}

const tmp = await mkdtemp(path.join(os.tmpdir(), 'ordessa-t018-'))
test.after(async () => { await rm(tmp, { recursive: true, force: true }) })

// --- test 4: real build, single instance, correct owner ---------------------
test('the real build constructs every domain token/kind exactly once, in the domain carrier only', async () => {
  const outRoot = path.join(tmp, 'out-full')
  const result = await runVariantBuild({ manifest: undefined, outputRoot: outRoot })
  assert.equal(result.code, 0, `full variant build failed:\n${result.stdout}`)
  const extensionsRoot = path.join(outRoot, 'extensions')

  // The domain-owned literals come from the shared CN-08 watchlists themselves,
  // so this guard cannot drift away from them (T029's ownerBundle model).
  const domainTokens = TOKEN_WATCHLIST.filter(e => e.ownerBundle === DOMAIN_CARRIER_ID)
  const domainKinds = KIND_WATCHLIST.filter(e => e.ownerBundle === DOMAIN_CARRIER_ID)
  assert.ok(domainTokens.length >= 2 && domainKinds.length >= 1, 'the watchlist admits no domain-owned literal — this check would pass vacuously')

  for (const [entries, scan, kind] of [
    [domainTokens, scanDirsForTokenConstructions, 'token'],
    [domainKinds, scanDirsForKindConstructions, 'kind'],
  ]) {
    const hits = await scan([extensionsRoot], entries.map(e => e.literal))
    for (const { literal, ownerBundle } of entries) {
      const sites = hits[literal]
      const total = sites.reduce((n, s) => n + s.count, 0)
      assert.ok(total >= 1, `domain ${kind} '${literal}' missing from the real build; the scan would pass vacuously`)
      assert.equal(total, 1, `domain ${kind} '${literal}' must be constructed exactly once in the build, found ${total}: ${JSON.stringify(sites)}`)
      assert.equal(path.relative(extensionsRoot, sites[0].file).split(path.sep)[0], ownerBundle, `domain ${kind} '${literal}' leaked outside owner '${ownerBundle}'`)
    }
  }

  // The PLATFORM carrier must construct no domain literal at all — the built
  // twin of the source-side purity/no-reverse-re-export scans above.
  const platformCarrierDir = path.join(extensionsRoot, 'ordessa.contracts')
  const domainLiterals = [...domainTokens.map(e => e.literal), ...domainKinds.map(e => e.literal)]
  const [tokenHits, kindHits] = await Promise.all([
    scanDirsForTokenConstructions([platformCarrierDir], domainLiterals),
    scanDirsForKindConstructions([platformCarrierDir], domainLiterals),
  ])
  const constructed = Object.entries({ ...tokenHits, ...kindHits }).filter(([, sites]) => sites.length > 0).map(([literal]) => literal)
  assert.deepEqual(constructed, [], 'extensions/ordessa.contracts carrier constructs domain literals — the platform bundled a copy of the domain contract')
})

// --- test 5: implemented-but-not-enabled, domain side ------------------------
test('without the Agent implementations the built domain carrier still exports a usable API', async () => {
  const enabled = JSON.parse(await readFile(productFile, 'utf8')).enabled
  assert.ok(AGENT_IMPLEMENTATION_IDS.every(id => enabled.includes(id)), `the product no longer admits ${AGENT_IMPLEMENTATION_IDS.join(', ')} — this guard would test nothing; move it with the manifest`)
  assert.ok(enabled.includes(DOMAIN_CARRIER_ID), 'the domain carrier itself must stay enabled for this guard to build it')
  const variantEnabled = enabled.filter(id => !AGENT_IMPLEMENTATION_IDS.includes(id))
  const manifest = path.join(tmp, 'extensions-without-agent-implementations.json')
  await writeFile(manifest, JSON.stringify({ enabled: variantEnabled }, null, 2) + '\n')
  const outRoot = path.join(tmp, 'out-without-agent-implementations')

  const result = await runVariantBuild({ manifest, outputRoot: outRoot })
  // exit 0 proves build-all's admission and @extensions/* dependency checks all
  // pass with the implementations removed while the carrier stays enabled —
  // a contract that needs no implementation to build.
  assert.equal(result.code, 0, `variant build without the Agent implementations failed:\n${result.stdout}`)

  const extensionsRoot = path.join(outRoot, 'extensions')
  const built = (await readdir(extensionsRoot, { withFileTypes: true })).filter(e => e.isDirectory()).map(e => e.name).sort()
  assert.deepEqual(built, [...variantEnabled].sort(), 'built set must equal the variant enabled list')
  for (const id of AGENT_IMPLEMENTATION_IDS) {
    assert.ok(!existsSync(path.join(extensionsRoot, id)), `variant dist must not contain the un-enabled ${id}/ directory: ${built.join(', ')}`)
  }

  // The un-enabled implementations must not perturb the shared domain API: it
  // is built, importable from node, and usable.
  const carrierFile = path.join(extensionsRoot, DOMAIN_CARRIER_ID, 'contract.js')
  assert.ok((await stat(carrierFile)).isFile(), 'variant dist lacks the ordessa.agent-contracts carrier')
  const carrier = await import(pathToFileURL(carrierFile).href)
  assert.equal(carrier.AgentConnectionsToken?.name, 'ordessa.agent.connections.v1', 'AgentConnectionsToken must carry the watched literal')
  assert.equal(carrier.AgentSessionsToken?.name, 'ordessa.agent.sessions.v1', 'AgentSessionsToken must carry the watched literal')
  assert.equal(typeof carrier.AgentClientConnectionKind, 'object', 'AgentClientConnectionKind must be a kind object')
  assert.equal(carrier.AgentClientConnectionKind?.displayName, 'ordessa.agent-client', 'the domain kind must carry its display literal')
  assert.ok(Object.isFrozen(carrier.AgentClientConnectionKind), 'kinds are frozen value objects')
  assert.equal(typeof carrier.hasOpenRun, 'function', 'hasOpenRun must be importable from the variant build')
  assert.equal(typeof carrier.hasAwaitingInteraction, 'function', 'hasAwaitingInteraction must be importable from the variant build')
  assert.ok(carrier.hasOpenRun([{ runs: { r1: { status: 'running' } }, interactions: [] }]), 'hasOpenRun must keep its semantics after the move')
  assert.ok(!carrier.hasOpenRun([{ runs: {}, interactions: [] }]), 'hasOpenRun must not report a run where there is none')

  // And the variant builds (both of them) perturbed the REAL product output
  // not at all.
  assert.equal(await readFile(lockFile, 'utf8'), snapshot.lock, 'extensions.lock.json changed around the variant builds')
  assert.deepEqual(await digestTree(realExtensionsRoot), snapshot.dist, 'products/desktop/dist changed around the variant builds')
})
