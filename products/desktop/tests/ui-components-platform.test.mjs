// C7/C8 product guard (T035 / U14, U16, V05, V07, V08): what the assembled
// product and the built controlled bundles prove about the generic UI mechanism.
//   1. the platform carries no controlled-domain name at all — a new component
//      kind is extension + product-configuration work, never a platform branch;
//   2. in a real build the test-domain key exists exactly once (in its own
//      carrier) and neither provider nor consumer bundles a copy, and no bundle
//      ships its own React — the shared-chunk identity U14/V07 depends on;
//   3. the shipping product does not enable the UI service, while the API is
//      still importable from the built carrier without any implementation, and
//      the carrier exports no service factory at all (UI-01/UI-14, V08).
// Run: node --test products/desktop/tests/ui-components-platform.test.mjs
import assert from 'node:assert/strict'
import { execFile } from 'node:child_process'
import { readFile } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import { register } from 'node:module'
import { pathToFileURL } from 'node:url'
import path from 'node:path'
import test from 'node:test'
import { promisify } from 'node:util'
import { acquireRealBuildLock } from '../../../tooling/real-build-lock.mjs'

const repoRoot = path.resolve(import.meta.dirname, '..', '..', '..')
const releaseBuildLock = await acquireRealBuildLock(repoRoot)
try {
  await promisify(execFile)(process.execPath, [path.join(repoRoot, 'apps/desktop/scripts/build.mjs')],
    { cwd: repoRoot, stdio: 'inherit' })
} catch (error) {
  await releaseBuildLock()
  throw error
}
test.after(() => releaseBuildLock())

// Every name that belongs to the controlled test domain of the UI examples. None
// of them may appear in platform source: the platform selects and renders, it does
// not know what it is rendering (C8 ruling: the platform never enumerates business
// components).
const CONTROLLED_NAMES = ['example.widget', 'example.provider-a', 'example.provider-b', 'example.rogue',
  'ui-consumer', 'ui-provider', 'WidgetProps', 'WidgetKey', 'provider-a', 'provider-b']

async function sourceFiles(dir) {
  const { readdir } = await import('node:fs/promises')
  const found = []
  async function walk(folder) {
    for (const entry of await readdir(folder, { withFileTypes: true })) {
      if (entry.name === 'node_modules' || entry.name === 'dist' || entry.name === 'tests' || entry.name === 'test') continue
      const file = path.join(folder, entry.name)
      if (entry.isDirectory()) await walk(file)
      else if (/\.[cm]?[jt]sx?$/.test(entry.name)) found.push({ file, source: await readFile(file, 'utf8') })
    }
  }
  await walk(dir)
  return found
}

// --- 1. platform neutrality over real sources --------------------------------
test('no controlled UI fixture name appears anywhere in the platform source', async () => {
  const sources = await sourceFiles(path.join(repoRoot, 'packages/desktop-platform'))
  // Fail loudly rather than pass over an empty scan.
  assert.ok(sources.length >= 20, `only ${sources.length} platform sources scanned — fix this guard's roots, do not let it pass empty`)
  const violations = []
  for (const { file, source } of sources) {
    const name = path.relative(repoRoot, file)
    // Branching on a fixture name is what the ruling forbids; a comment that names
    // what must not be branched on (as several of these files do) is not a violation.
    for (const term of CONTROLLED_NAMES) {
      const quoted = `['"\`]${term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}['"\`]`
      const re = new RegExp(`(?:===|!==|==|!=|\\bcase\\b|\\.includes\\(|\\.startsWith\\(|\\.endsWith\\(|\\.has\\(|\\bfrom\\s*)\\s*\\(?\\s*${quoted}`)
      if (re.test(source)) violations.push(`${name} branches on controlled fixture '${term}'`)
    }
  }
  assert.deepEqual(violations, [], 'C8 V05/U16: the platform must select and render generically — every hit above is a business branch inside it')
})

// --- 2. real built bundles: one key, one React ------------------------------
const examplesDist = path.join(repoRoot, 'examples/dist')
const BUNDLES = {
  'example.ui-contracts/contract.js': 1,
  'example.ui-contracts/entry.js': 0,
  'example.ui-provider/entry.js': 0,
  'example.ui-provider-alt/entry.js': 0,
  'example.ui-consumer/entry.js': 0,
}

test('the controlled key is constructed exactly once in the real build and React stays shared', async () => {
  assert.ok(existsSync(path.join(examplesDist, 'example.ui-contracts/contract.js')),
    'npm run build:examples must run before this guard (the root aggregate does that) — a missing artifact is not a pass')
  let total = 0
  for (const [relative, expected] of Object.entries(BUNDLES)) {
    const built = await readFile(path.join(examplesDist, relative), 'utf8')
    const constructions = (built.match(/defineUiComponent\(\s*['"`]example\.widget/g) ?? []).length
    assert.equal(constructions, expected, `${relative} must construct ${expected} copies of the test-domain key, found ${constructions}`)
    total += constructions
    // Each bundle must reach React through the shared chunk, never carry its own copy:
    // a duplicated React is what makes hooks and element identity diverge across bundles.
    assert.ok(!/__SECRET_INTERNALS|ReactCurrentOwner|createElementType/.test(built),
      `${relative} bundles a private copy of React instead of using the shared module channel`)
  }
  assert.equal(total, 1, 'provider and consumer must share one key instance (U14): exactly the carrier may construct it')
  const consumer = await readFile(path.join(examplesDist, 'example.ui-consumer/entry.js'), 'utf8')
  assert.match(consumer, /from ["']react/, 'the consumer should import React externally')
})

// --- 3. API without implementation; product keeps the service opt-in ---------
const carrierDir = path.join(repoRoot, 'products/desktop/dist/extensions/ordessa.contracts')
test('the shipping product does not enable the UI service, yet its API imports without any implementation', async () => {
  const product = JSON.parse(await readFile(path.join(repoRoot, 'products/desktop/extensions.json'), 'utf8'))
  assert.ok(!product.enabled.includes('ordessa.ui-components'),
    'the default product must not gain the UI service behind the user’s back (V08)')
  assert.equal(product.config, undefined, 'the default product configures no provider (V08)')
  assert.ok(existsSync(path.join(carrierDir, 'contract.js')), 'the real product carrier must be built (run npm run build:foundations)')

  // Node has no browser import map: resolve the carrier's public channels to
  // the actual app shared entries, preserving one Token identity.
  const sharedRoot = path.join(repoRoot, 'apps/desktop/dist/renderer/shared')
  for (const name of ['api.js', 'ui-components-api.js']) {
    assert.ok(existsSync(path.join(sharedRoot, name)), `missing app shared entry ${name}; build apps/desktop first`)
  }
  register('data:text/javascript,' + encodeURIComponent(`
export async function resolve(specifier, context, next) {
  if (specifier === '@ordessa/extension-api') return { url: ${JSON.stringify(pathToFileURL(path.join(sharedRoot, 'api.js')).href)}, shortCircuit: true }
  if (specifier === '@ordessa/ui-components/api') return { url: ${JSON.stringify(pathToFileURL(path.join(sharedRoot, 'ui-components-api.js')).href)}, shortCircuit: true }
  return next(specifier, context)
}`))
  const carrier = await import(pathToFileURL(path.join(carrierDir, 'contract.js')).href)
  const sharedUi = await import(pathToFileURL(path.join(sharedRoot, 'ui-components-api.js')).href)
  assert.equal(carrier.UiComponentsToken, sharedUi.UiComponentsToken,
    'carrier and import-map shared entry must export the identical Token')
  assert.equal(carrier.UiComponentsToken?.name, 'ordessa.ui-components.v1', 'the Token must ride the platform carrier')
  assert.equal(typeof carrier.defineUiComponent, 'function', 'the key factory must be importable')
  assert.equal(typeof carrier.registration, 'function', 'the registration factory must be importable')
  assert.equal(typeof carrier.UiComponentsError, 'function', 'the generic error type must be importable')
  // The implementation is NOT in the carrier: importing the API must not activate
  // or bundle a service (contract §1: no implementation side effect).
  for (const absent of ['createUiComponentsService', 'createUiComponentsPlugin', 'ComponentOutlet']) {
    assert.equal(carrier[absent], undefined, `carrier must not expose the implementation entry '${absent}'`)
  }
  // And the API really works with no implementation present: a key + a selection-free
  // read path are pure data.
  const key = carrier.defineUiComponent('example.inert', 1)
  assert.deepEqual({ id: key.id, major: key.major }, { id: 'example.inert', major: 1 })
  assert.throws(() => carrier.defineUiComponent('example.inert', 0), RangeError)
})
