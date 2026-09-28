// C7/T035 + C8 gate: the UI component mechanism assembled in a real product,
// in a temporary Electron instance with an EMPTY Workbench — only the platform
// carrier, the generic UI service and controlled provider/consumer extensions
// (acceptance U14-U16 / V05, V08; no Agent, no Chat, no Server, no model).
//
// The platform pieces come from a variant real build (ORDESSA_PRODUCT_MANIFEST +
// ORDESSA_PRODUCT_OUTPUT_ROOT), so this script never writes the shipping product
// output or its lock; the controlled extensions come from examples/dist, built by
// `npm run build:examples`, which the root aggregate runs before this gate.
import assert from 'node:assert/strict'
import { execFile } from 'node:child_process'
import { cp, mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { promisify } from 'node:util'
import { launchSmoke } from './launch-smoke.mjs'

const run = promisify(execFile)
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..')
const PLATFORM = ['ordessa.contracts', 'ordessa.ui-components']
const EXAMPLES = ['example.ui-contracts', 'example.ui-provider', 'example.ui-consumer']
const WIDGET = [{ componentId: 'example.widget', major: 1, providerId: 'example.provider-a' }]

async function digest(dir) {
  const hash = createHash('sha256')
  async function walk(folder) {
    for (const file of (await readdirSorted(folder))) {
      const target = path.join(folder, file.name)
      if (file.isDirectory()) await walk(target)
      else { hash.update(path.relative(dir, target)); hash.update(await readFile(target)) }
    }
  }
  await walk(dir)
  return hash.digest('hex')
}
async function readdirSorted(folder) {
  const { readdir } = await import('node:fs/promises')
  return (await readdir(folder, { withFileTypes: true })).sort((a, b) => a.name.localeCompare(b.name))
}

const appBuild = path.join(root, 'apps/desktop/dist')
const hostBefore = await digest(appBuild)
const tmp = await mkdtemp(path.join(os.tmpdir(), 'ordessa-ui-service-'))
const reports = []
try {
  // One variant real build carries every platform piece this gate needs. Only
  // build-discoverable packages go into that manifest — the controlled example
  // bundles come from examples/dist and are approved by the runtime manifest below.
  const productFile = path.join(tmp, 'extensions-product.json')
  await writeFile(productFile, JSON.stringify({ enabled: PLATFORM }, null, 2) + '\n')
  const variantDist = path.join(tmp, 'product')
  await run(process.execPath, [path.join(root, 'tooling/build-all.mjs')], {
    cwd: root,
    env: { ...process.env, ORDESSA_PRODUCT_MANIFEST: productFile, ORDESSA_PRODUCT_OUTPUT_ROOT: variantDist },
  })

  const home = path.join(tmp, 'home')
  const extensions = path.join(home, 'extensions')
  await mkdir(extensions, { recursive: true })
  for (const id of PLATFORM) await cp(path.join(variantDist, 'extensions', id), path.join(extensions, id), { recursive: true })
  for (const id of EXAMPLES) await cp(path.join(root, 'examples/dist', id), path.join(extensions, id), { recursive: true })
  await cp(path.join(root, 'examples/dist', 'example.ui-provider-alt'), path.join(extensions, 'example.ui-provider-alt'), { recursive: true })

  async function launch(name, { enabled, config }, verify) {
    await writeFile(path.join(home, 'extensions.json'), JSON.stringify({ enabled, ...(config ? { config } : {}) }))
    const result = await launchSmoke(home)
    assert.equal(result.ready, true, `${name}: the shell must come up no matter what an extension did`)
    assert.equal(result.nodeAbsent, true)
    reports.push({ name, ...result })
    verify(result)
    return result
  }
  const healthy = ['ordessa.contracts', 'ordessa.ui-components', 'example.ui-contracts', 'example.ui-provider', 'example.ui-consumer']

  // U14/U15: service enabled, selection made, empty Workbench.
  const selected = await launch('selected provider renders', { enabled: healthy, config: { 'ordessa.ui-components': WIDGET } }, result => {
    assert.equal(result.emptyHost, false, 'the consumer root view should be mounted')
    assert.match(result.rootText, /ready:example\.provider-a/)
    assert.match(result.rootText, /provider-a from-consumer/)
    assert.deepEqual(result.errors, [])
    // U15's window/keyboard half: focus must be a real element inside the document,
    // not lost on a detached node after the shell settled.
    assert.match(result.activeElement, /^(BODY|HTML|BUTTON|INPUT|SECTION):/, JSON.stringify(result.activeElement))
    assert.notEqual(result.activeElement, 'none')
    assert.match(result.activeElementAfterTab, /^BUTTON:/, `Tab must land on a focusable control, got ${result.activeElementAfterTab}`)
  })
  const consumerDigest = await digest(path.join(extensions, 'example.ui-consumer'))

  // U02/V05/SC-2: provider B is a product-configuration change; the consumer bundle is untouched.
  await launch('other provider selected without touching the consumer', {
    enabled: [...healthy.filter(id => id !== 'example.ui-provider'), 'example.ui-provider-alt'],
    config: { 'ordessa.ui-components': [{ componentId: 'example.widget', major: 1, providerId: 'example.provider-b' }] },
  }, result => {
    assert.match(result.rootText, /ready:example\.provider-b/)
    assert.match(result.rootText, /provider-b from-consumer/)
    assert.doesNotMatch(result.rootText, /provider-a/)
    assert.deepEqual(result.errors, [])
  })
  assert.equal(await digest(path.join(extensions, 'example.ui-consumer')), consumerDigest,
    'swapping the selected provider must not require a consumer rebuild')

  // V08/UI-11: the service is enabled but the product selected nothing — absence is reported, not invented.
  await launch('nothing selected reports the missing required component', { enabled: healthy }, result => {
    assert.match(result.rootText, /missing:unselected/)
    assert.ok(result.errors.some(text => text.includes('required ui component unavailable: example.widget major 1 (not selected)')),
      `expected a required-binding diagnostic, got ${JSON.stringify(result.errors)}`)
  })

  // U14: with the service not enabled at all, nothing is silently added on its behalf;
  // the unsatisfied consumer fails alone and the shell keeps working.
  await launch('service absent is fail-closed, not backfilled', { enabled: healthy.filter(id => id !== 'ordessa.ui-components') }, result => {
    assert.equal(result.emptyHost, true, 'no root view may mount without the service it requires')
    assert.ok(result.errors.some(text => text.includes('example.ui-consumer')), JSON.stringify(result.errors))
    // The unsatisfied dependency is named, never silently substituted by a default provider.
    assert.ok(result.errors.some(text => text.includes('ordessa.ui-components')), JSON.stringify(result.errors))
    assert.doesNotMatch(result.rootText, /ready:/, 'nothing may report itself served without the service')
  })

  // U04 real-build counterexample: a second key object for (example.widget, 1), built as its
  // own extension, is rejected by identity - and the healthy consumer keeps rendering.
  const rogue = path.join(extensions, 'rogue-key')
  await mkdir(rogue, { recursive: true })
  await writeFile(path.join(rogue, 'manifest.json'), JSON.stringify({ id: 'example.rogue', version: '0.1.0', hostApi: '2', entry: 'entry.js' }))
  await writeFile(path.join(rogue, 'entry.js'), [
    "import { UiComponentsToken, defineUiComponent, registration } from '@extensions/ordessa.contracts/contract.js'",
    "export default function createPlugin() { return { id: 'example.rogue', autoStart: true, requires: [UiComponentsToken],",
    "  activate(host, ui) { ui.forScope(host.resources).registerBatch([registration(defineUiComponent('example.widget', 1), 'example.rogue', () => null)]) } } }",
  ].join('\n'))
  await launch('a copied key instance is rejected at registration', { enabled: [...healthy, 'example.rogue'], config: { 'ordessa.ui-components': WIDGET } }, result => {
    const conflicts = result.errors.filter(text => text.includes('UI_KEY_IDENTITY_CONFLICT'))
    assert.equal(conflicts.length, 1, `exactly the second key instance must be rejected: ${JSON.stringify(result.errors)}`)
    assert.match(result.rootText, /ready:example\.provider-a|ready:example\.rogue/,
      'one of the two claimants is still served, so the healthy path is not collateral damage')
    assert.doesNotMatch(result.rootText, /provider-b/)
  })
  await rm(rogue, { recursive: true, force: true })

  assert.equal(selected.rootText.includes('provider-a'), true)
  assert.equal(await digest(appBuild), hostBefore, 'the host build must be byte-identical after the whole gate')
  console.log(JSON.stringify({ hostDigest: hostBefore, hostUnchanged: true, cases: reports }, null, 2))
} finally {
  await rm(tmp, { recursive: true, force: true })
}
