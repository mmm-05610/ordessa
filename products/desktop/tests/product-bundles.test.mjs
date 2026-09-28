// T020 product-level guard (products/desktop): the assembled product build
// really carries every admitted extension and the shared contract bundles
// that own the single DI Token copies. The per-token uniqueness and the
// rogue duplicate counterexample are verified by
// packages/workbench/tests/token-single-instance.test.mjs (shared, not
// re-counted here); this file proves the PRODUCT ADMISSION side:
//   - every id in products/desktop/extensions.json resolves to a built bundle
//     with an entry.js and a manifest.json (an admitted-but-unbuilt product
//     piece must not pass vacuously), and
//   - each token owner bundle from the watch list is itself an admitted,
//     contract-carrier bundle in dist — the module the installed product
//     serves to `@extensions/<id>/contract.js`.
// Run: node --test products/desktop/tests/ (root aggregation arrives with T021).
import assert from 'node:assert/strict'
import { execFile } from 'node:child_process'
import { access, mkdtemp, readFile, rm } from 'node:fs/promises'
import path from 'node:path'
import os from 'node:os'
import { pathToFileURL } from 'node:url'
import test from 'node:test'
import { promisify } from 'node:util'
import { build } from 'esbuild'
import { TOKEN_WATCHLIST } from '../../../packages/workbench/tests/token-scan.mjs'
import { acquireRealBuildLock } from '../../../tooling/real-build-lock.mjs'

const run = promisify(execFile)
const repoRoot = path.resolve(import.meta.dirname, '..', '..', '..')
const productFile = path.join(repoRoot, 'products/desktop/extensions.json')
const extensionsRoot = path.join(repoRoot, 'products/desktop/dist/extensions')
const rendererRoot = path.join(repoRoot, 'apps/desktop/dist/renderer')

// Fresh real build so the assertions below can never pass against a stale
// dist. `node --test` runs directory files as parallel processes, so the
// shared real product output is guarded by a cross-process lock — other
// guards across the repo rebuild it too (see tooling/real-build-lock.mjs).
const releaseBuildLock = await acquireRealBuildLock(repoRoot)
try {
  await run(process.execPath, [path.join(repoRoot, 'apps/desktop/scripts/build.mjs')], { cwd: repoRoot, stdio: 'inherit' })
} catch (error) {
  await releaseBuildLock()
  throw error
}
test.after(() => releaseBuildLock())

const exists = async (file) => access(file).then(() => true, () => false)

test('every admitted product extension is really built with entry and manifest', async () => {
  const enabled = JSON.parse(await readFile(productFile, 'utf8')).enabled
  assert.ok(Array.isArray(enabled) && enabled.length >= 9, `product admits ${enabled.length} extensions; expected the full desktop set — an emptied manifest would make this pass vacuously`)
  for (const id of enabled) {
    assert.ok(await exists(path.join(extensionsRoot, id, 'entry.js')), `admitted extension ${id} has no built entry.js in ${extensionsRoot}`)
    assert.ok(await exists(path.join(extensionsRoot, id, 'manifest.json')), `admitted extension ${id} has no manifest.json in dist`)
  }
})

test('each DI token owner bundle is an admitted contract carrier in the product build', async () => {
  const enabled = JSON.parse(await readFile(productFile, 'utf8')).enabled
  for (const { literal, ownerBundle } of TOKEN_WATCHLIST) {
    if (ownerBundle.startsWith('shared/')) continue // verified through the real host route below
    assert.ok(enabled.includes(ownerBundle), `token '${literal}' is owned by '${ownerBundle}' but the product does not admit it`)
    assert.ok(await exists(path.join(extensionsRoot, ownerBundle, 'contract.js')), `owner bundle '${ownerBundle}' of token '${literal}' has no contract.js carrier`)
  }
})

test('each shared DI token owner is served by the real import map and app artifact', async () => {
  const sharedOwners = TOKEN_WATCHLIST.filter(({ ownerBundle }) => ownerBundle.startsWith('shared/'))
  assert.ok(sharedOwners.length > 0, 'shared-owner admission would pass vacuously')
  const temp = await mkdtemp(path.join(os.tmpdir(), 'ordessa-product-import-map-'))
  try {
    const moduleFile = path.join(temp, 'extension-protocol.mjs')
    await build({
      entryPoints: [path.join(repoRoot, 'packages/desktop-platform/extension-host/src/main/extension-protocol.ts')],
      outfile: moduleFile, bundle: true, platform: 'node', format: 'esm',
    })
    const { protocolHandler } = await import(pathToFileURL(moduleFile).href)
    const handler = protocolHandler(rendererRoot, { installed: new Map() })
    const htmlResponse = await handler({ url: 'ordessa://desktop/', method: 'GET' })
    assert.equal(htmlResponse.status, 200)
    const html = await htmlResponse.text()
    const mapText = html.match(/<script[^>]*type="importmap"[^>]*>(.*?)<\/script>/)?.[1]
    assert.ok(mapText, 'real host HTML must publish an import map')
    const imports = JSON.parse(mapText).imports
    for (const { literal, ownerBundle } of sharedOwners) {
      // Shared API admission is explicit, just as extension admission is.
      const specifier = literal === 'ordessa.ui-components.v1' ? '@ordessa/ui-components/api' : undefined
      assert.ok(specifier, `unrecognized shared Token owner '${literal}' needs an import-map admission rule`)
      const route = '/' + ownerBundle
      assert.equal(imports[specifier], route, `shared Token '${literal}' is not mapped to its owner`)
      assert.equal(Object.values(imports).filter(value => value === route).length, 1,
        `shared Token '${literal}' has ambiguous import-map routes`)
      const built = await readFile(path.join(rendererRoot, ownerBundle))
      const response = await handler({ url: 'ordessa://desktop' + route, method: 'GET' })
      assert.equal(response.status, 200, `shared owner '${ownerBundle}' is not served`)
      assert.deepEqual(Buffer.from(await response.arrayBuffer()), built,
        `served shared owner '${ownerBundle}' differs from the real app artifact`)
      const absent = protocolHandler(temp, { installed: new Map() })
      assert.equal((await absent({ url: 'ordessa://desktop' + route, method: 'GET' })).status, 404,
        `missing shared owner '${ownerBundle}' must fail closed`)
    }
  } finally {
    await rm(temp, { recursive: true, force: true })
  }
})
