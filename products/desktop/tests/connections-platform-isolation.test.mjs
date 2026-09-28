// T029 (CN-08 second clause + CN-01 structural half) — products/desktop guard:
// an IMPLEMENTED BUT
// NOT ENABLED platform must still admit import of its public API, verified
// against REAL builds, not fixtures. A variant product build is run through
// tooling/build-all.mjs with the default enabled list minus
// 'ordessa.connections' via the default-preserving env overrides
// (ORDESSA_PRODUCT_MANIFEST / ORDESSA_PRODUCT_OUTPUT_ROOT); the real product
// output and lock must never be touched by it. Assertions:
//   1. the variant build exits 0 — build-all's admission checks (unique
//      enabled ids, package presence, every @extensions/<id>/ reference of an
//      enabled package is itself enabled) and the built-set-equals-enabled
//      check all still pass without the Connections implementation;
//   2. the variant dist really has no ordessa.connections/ directory, while
//      the shared carrier ordessa.contracts/contract.js is built there and,
//      dynamically imported in node, still exports a usable Connections API
//      (ConnectionsToken literal, working per-construction kind factory);
//   3. the variant dist still constructs every watched token and kind
//      exactly once inside its owner bundle — disabling the implementation
//      does not duplicate or drop the shared contract;
//   4. the REAL built platform bundle reaches no business extension at all —
//      CN-01's structural half, paired with a source-side guard in
//      packages/desktop-platform/connections/tests/platform-isolation.test.ts;
//   5. the output-root override perturbs nothing: a FULL-enabled variant build
//      must reproduce the real dist byte-for-byte (variant and real builds now
//      run the same pipeline, so this holds only if no absolute artifact path
//      leaks into the bundles), and the real dist + extensions.lock.json are
//      byte-identical after every run.
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
  scanDirsForTokenConstructions, WATCHED_KIND_LITERALS, WATCHED_TOKEN_LITERALS,
} from '../../../packages/workbench/tests/token-scan.mjs'
import { acquireRealBuildLock } from '../../../tooling/real-build-lock.mjs'

const runAsync = promisify(execFile)
const repoRoot = path.resolve(import.meta.dirname, '..', '..', '..')
const productFile = path.join(repoRoot, 'products/desktop/extensions.json')
const buildAll = path.join(repoRoot, 'tooling/build-all.mjs')
const buildApp = path.join(repoRoot, 'apps/desktop/scripts/build.mjs')
const realExtensionsRoot = path.join(repoRoot, 'products/desktop/dist/extensions')
const lockFile = path.join(repoRoot, 'products/desktop/extensions.lock.json')

const CONNECTIONS_ID = 'ordessa.connections'

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

// Fresh real build (shared output, locked against the sibling product guard),
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

const tmp = await mkdtemp(path.join(os.tmpdir(), 'ordessa-cn08-'))
test.after(async () => { await rm(tmp, { recursive: true, force: true }) })

test('variant build without ordessa.connections succeeds and keeps the platform API importable', async () => {
  const enabled = JSON.parse(await readFile(productFile, 'utf8')).enabled
  assert.ok(enabled.includes(CONNECTIONS_ID), `the product no longer admits '${CONNECTIONS_ID}' — this guard would test nothing; move it with the manifest`)
  const variantEnabled = enabled.filter(id => id !== CONNECTIONS_ID)
  assert.ok(variantEnabled.length >= 9 && variantEnabled.length === enabled.length - 1)
  const manifest = path.join(tmp, 'extensions-without-connections.json')
  await writeFile(manifest, JSON.stringify({ enabled: variantEnabled }, null, 2) + '\n')
  const outRoot = path.join(tmp, 'out-without')

  const result = await runVariantBuild({ manifest, outputRoot: outRoot })
  // exit 0 proves build-all's admission, @extensions/* dependency and
  // built-set-equals-enabled checks all pass with the implementation removed.
  assert.equal(result.code, 0, `variant build failed:\n${result.stdout}`)

  const extensionsRoot = path.join(outRoot, 'extensions')
  const built = (await readdir(extensionsRoot, { withFileTypes: true })).filter(entry => entry.isDirectory()).map(entry => entry.name).sort()
  assert.ok(!built.includes(CONNECTIONS_ID), `variant dist must not contain ${CONNECTIONS_ID}/: ${built.join(', ')}`)
  assert.deepEqual(built, [...variantEnabled].sort(), 'built set must equal the variant enabled list')
  assert.deepEqual(JSON.parse(await readFile(path.join(outRoot, 'extensions.json'), 'utf8')).enabled, variantEnabled)

  // The shared carrier is still built in the variant product and exports a
  // usable Connections API even though the implementation extension is gone.
  const carrierFile = path.join(extensionsRoot, 'ordessa.contracts', 'contract.js')
  assert.ok((await stat(carrierFile)).isFile(), 'variant dist lacks the ordessa.contracts carrier')
  const carrier = await import(pathToFileURL(carrierFile).href)
  assert.equal(carrier.ConnectionsToken.name, 'ordessa.connections.v1', 'ConnectionsToken must carry the watched literal')
  assert.equal(typeof carrier.createConnectionKind, 'function', 'createConnectionKind must be importable from the variant build')
  const kind = carrier.createConnectionKind('variant-check')
  assert.equal(kind.displayName, 'variant-check')
  assert.ok(Object.isFrozen(kind), 'kinds are frozen value objects')
  assert.notEqual(carrier.createConnectionKind('same'), carrier.createConnectionKind('same'), 'kind identity is per-construction')

  // The un-enabled implementation must not perturb the shared contract: every
  // watched token and kind is still constructed exactly once, in its owner.
  for (const [watchlist, scan, literals] of [
    [TOKEN_WATCHLIST, scanDirsForTokenConstructions, WATCHED_TOKEN_LITERALS],
    [KIND_WATCHLIST, scanDirsForKindConstructions, WATCHED_KIND_LITERALS],
  ]) {
    const kind_ = watchlist === KIND_WATCHLIST ? 'kind' : 'token'
    // The UI API Token is owned by the app's import-map shared entry, while
    // the older carrier Tokens remain in extension bundles.
    const hits = await scan([extensionsRoot, sharedRoot], literals)
    for (const { literal, ownerBundle } of watchlist) {
      const sites = hits[literal]
      const total = sites.reduce((n, s) => n + s.count, 0)
      assert.ok(total >= 1, `${kind_} '${literal}' missing from the variant build; the scan would pass vacuously`)
      assert.equal(total, 1, `${kind_} '${literal}' must be constructed exactly once in the variant build, found ${total}: ${JSON.stringify(sites)}`)
      const actualOwner = sites[0].file.startsWith(extensionsRoot + path.sep)
        ? path.relative(extensionsRoot, sites[0].file).split(path.sep)[0]
        : `shared/${path.relative(sharedRoot, sites[0].file).split(path.sep).join('/')}`
      assert.equal(actualOwner, ownerBundle, `${kind_} '${literal}' leaked outside owner '${ownerBundle}' in the variant build`)
    }
  }
})

test('the built platform bundle reaches no business extension', async () => {
  // CN-01's structural half against the REAL product build: importing/enabling
  // Connections must never drag an Agent or Workbench extension into the
  // platform's own bundle graph, and the platform bundle must not name any
  // business extension id. The source-side twin of this check (token/kind
  // literals, relative escapes) lives in
  // packages/desktop-platform/connections/tests/platform-isolation.test.ts.
  const business = JSON.parse(await readFile(productFile, 'utf8')).enabled
    .filter(id => id !== 'ordessa.contracts' && id !== CONNECTIONS_ID)
  assert.ok(business.length >= 7, `the product admits only ${business.length} business extensions — this check would be near-vacuous`)

  const bundleDir = path.join(realExtensionsRoot, CONNECTIONS_ID)
  const bundles = []
  async function walk(dir) {
    for (const entry of await readdir(dir, { withFileTypes: true })) {
      const file = path.join(dir, entry.name)
      if (entry.isDirectory()) await walk(file)
      else if (/\.js$/.test(entry.name)) bundles.push({ file, source: await readFile(file, 'utf8') })
    }
  }
  await walk(bundleDir)
  assert.ok(bundles.length >= 1, `no built JS under ${bundleDir} — build the product first; this guard would pass vacuously`)

  for (const { file, source } of bundles) {
    const name = path.relative(realExtensionsRoot, file)
    for (const imported of [...source.matchAll(/@extensions\/([a-z0-9.-]+)\//g)].map(m => m[1])) {
      assert.ok(imported === 'ordessa.contracts' || imported === CONNECTIONS_ID,
        `${name} imports the business carrier '@extensions/${imported}/' — the platform must depend on the shared contract carrier only`)
    }
    for (const id of business) {
      assert.ok(!source.includes(id), `${name} references business extension id '${id}'`)
    }
  }
})

test('redirecting the output root perturbs the product build not at all', async () => {
  const outRoot = path.join(tmp, 'out-full')
  const result = await runVariantBuild({ manifest: undefined, outputRoot: outRoot })
  assert.equal(result.code, 0, `full-set variant build failed:\n${result.stdout}`)
  const variant = await digestTree(path.join(outRoot, 'extensions'))
  const real = snapshot.dist
  assert.ok(Object.keys(real).length >= 27, `real dist snapshot looks empty (${Object.keys(real).length} files) — the comparison below would pass vacuously`)
  assert.deepEqual(Object.keys(variant).sort(), Object.keys(real).sort(), 'variant build file set differs from the real build')
  for (const file of Object.keys(real)) {
    assert.equal(variant[file], real[file], `the variant build diverged from the real build pipeline at ${file} — the output-root override must not perturb artifacts`)
  }
})

test('variant builds never touched the real product dist or lock', async () => {
  assert.equal(await readFile(lockFile, 'utf8'), snapshot.lock, 'extensions.lock.json changed around the variant builds')
  assert.deepEqual(await digestTree(realExtensionsRoot), snapshot.dist, 'products/desktop/dist changed around the variant builds')
  const locked = JSON.parse(snapshot.lock).files
  const actual = Object.fromEntries(Object.entries(snapshot.dist).map(([name, hash]) => [`extensions/${name}`, hash]))
  assert.deepEqual(locked, actual, 'product lock hashes must match every real built extension byte')
})
