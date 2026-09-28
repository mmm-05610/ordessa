// C8 UIB005/UIB006 gate: the generic foundations and the C7 loading mechanism,
// composed inside the real Workbench shell and measured by real Chromium layout at
// 360px and 768px (acceptance V03, V04, V05, V06). Temporary Electron, temporary
// userData, no real Server, no model; the platform pieces come from a variant real
// build so the shipping product output and its lock stay untouched.
// Run: npm run test:ui-foundations
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
const PLATFORM = ['ordessa.contracts', 'ordessa.commands', 'ordessa.workbench', 'ordessa.ui-components']
const EXAMPLES = ['example.ui-contracts', 'example.ui-provider', 'example.ui-foundations']

async function digest(dir) {
  const hash = createHash('sha256')
  const { readdir } = await import('node:fs/promises')
  async function walk(folder) {
    for (const entry of (await readdir(folder, { withFileTypes: true })).sort((a, b) => a.name.localeCompare(a.name))) {
      const target = path.join(folder, entry.name)
      if (entry.isDirectory()) await walk(target)
      else { hash.update(path.relative(dir, target)); hash.update(await readFile(target)) }
    }
  }
  await walk(dir)
  return hash.digest('hex')
}

const appBuild = path.join(root, 'apps/desktop/dist')
const hostBefore = await digest(appBuild)
const tmp = await mkdtemp(path.join(os.tmpdir(), 'ordessa-ui-foundations-'))
// The viewport evidence outlives the run: it is the record C8 asks for (viewport,
// theme, container), so it lands in the session evidence dir, not the temp tree
// this script deletes.
const shots = process.env.ORDESSA_UI_EVIDENCE_DIR ?? path.join(os.tmpdir(), 'ordessa-C-evidence', 'C8-shots')
try {
  await mkdir(shots, { recursive: true })
  const productFile = path.join(tmp, 'extensions-product.json')
  await writeFile(productFile, JSON.stringify({ enabled: PLATFORM }, null, 2) + '\n')
  const variantDist = path.join(tmp, 'product')
  await run(process.execPath, [path.join(root, 'tooling/build-all.mjs')], {
    cwd: root, env: { ...process.env, ORDESSA_PRODUCT_MANIFEST: productFile, ORDESSA_PRODUCT_OUTPUT_ROOT: variantDist },
  })

  const home = path.join(tmp, 'home')
  const extensions = path.join(home, 'extensions')
  await mkdir(extensions, { recursive: true })
  for (const id of PLATFORM) await cp(path.join(variantDist, 'extensions', id), path.join(extensions, id), { recursive: true })
  for (const id of EXAMPLES) await cp(path.join(root, 'examples/dist', id), path.join(extensions, id), { recursive: true })
  await writeFile(path.join(home, 'extensions.json'), JSON.stringify({
    enabled: [...PLATFORM, ...EXAMPLES],
    config: { 'ordessa.ui-components': [{ componentId: 'example.widget', major: 1, providerId: 'example.provider-a' }] },
  }))

  const result = await launchSmoke(home, { MODULAR_UI_FOUNDATIONS: '1', MODULAR_UI_SHOTS: shots })
  assert.equal(result.ready, true, JSON.stringify(result.errors))
  assert.deepEqual(result.errors, [], 'the fixture uses an optional binding, so nothing may report a failure')
  assert.equal(result.emptyHost, false)
  const { probe360: a, probe768: b } = result
  for (const [name, probe] of [['360', a], ['768', b]]) {
    assert.equal(probe.missing, undefined, `${name}px: fixture nodes missing: ${JSON.stringify(probe.missing)}`)
    // V03 — the long line scrolls inside the ScrollArea, and the page itself never grows sideways.
    assert.ok(['auto', 'scroll'].includes(probe.scrollOwnsOverflow), `${name}px: scroll owner was ${probe.scrollOwnsOverflow}`)
    assert.ok(probe.scrollInnerOverflow > 0, `${name}px: the wide line should overflow its own scroll area, not the page`)
    assert.ok(probe.pageOverflowX <= 0, `${name}px: horizontal page overflow of ${probe.pageOverflowX}px`)
    // The measurement is only meaningful if the window really is that narrow.
    assert.ok(Math.abs(probe.viewport.width - Number(name)) <= 8, `${name}px: innerWidth was ${probe.viewport.width}`)
    assert.equal(probe.panelHeaderShrink, '0', `${name}px: the panel header must not shrink away`)
    assert.equal(probe.panelBodyScrollable, 'auto', `${name}px: the panel body is the scroll owner`)
    // V04 — theme variables are inherited from the host, not redefined per control.
    assert.equal(probe.themeFollowsHost.afterSurface, 'rgb(18, 52, 86)', `${name}px: a host --ui-accent override must reach the foundation: ${JSON.stringify(probe.themeFollowsHost)}`)
    assert.notEqual(probe.themeFollowsHost.beforeSurface, probe.themeFollowsHost.afterSurface)
    // V04 — the foundations sheet must not touch foreign DOM, and must be the thing
    // that styles its own control (with it disabled the host's `.wb button` wins).
    const pollution = probe.pollution
    assert.equal(pollution.sheetFound, true, `${name}px: the foundations stylesheet was not found`)
    assert.deepEqual(pollution.foreignWithoutSheet, pollution.foreignBefore, `${name}px: a host button changed when the foundations sheet was disabled`)
    assert.deepEqual(pollution.foreignAfter, pollution.foreignBefore, `${name}px: the foundations sheet changed a foreign control`)
    assert.equal(pollution.uiWithoutSheet.padding, '5px 10px', `${name}px: expected the host .wb button padding once the foundations sheet is off`)
    assert.notEqual(pollution.uiWithSheet.padding, pollution.uiWithoutSheet.padding, `${name}px: the foundations rule is not carrying its own control`)
    assert.equal(pollution.uiWithSheet.padding, '6px 12px', `${name}px: the foundation must keep its own padding inside the Workbench shell`)
    // V05/V06 — the product-selected provider renders through the C7 outlet inside a Card.
    assert.equal(probe.loadedComponent, `ready:example.provider-a`, `${name}px: outlet availability was ${probe.loadedComponent}`)
    assert.equal(probe.loadedInsideCard, true, `${name}px: the loaded component must render inside the Card body`)
    // F04 — the value belongs to the consumer, the foundation only displays it.
    assert.equal(probe.draftValue, 'kept by the consumer')
  }
  assert.ok(a.rects.card.w < b.rects.card.w, `geometry must actually respond to the viewport: 360 ${a.rects.card.w} vs 768 ${b.rects.card.w}`)
  assert.ok(a.rects.card.w <= a.viewport.width && b.rects.card.w <= b.viewport.width,
    `the card must fit its own viewport: ${a.rects.card.w}/${a.viewport.width} and ${b.rects.card.w}/${b.viewport.width}`)
  // V04 — keyboard focus moves through real tab order, no trap introduced by the foundations.
  assert.equal(result.tabFromInput.before, 'INPUT:ui-input')
  assert.match(result.tabFromInput.after, /^BUTTON:/, `Tab must reach the next focusable control, got ${result.tabFromInput.after}`)
  assert.notEqual(result.tabFromInput.after, result.tabFromInput.before)
  // Screenshots are evidence, not assertions: record what was captured.
  const captured = (await import('node:fs/promises')).readdir(shots)
  assert.deepEqual((await captured).sort(), ['viewport-360.png', 'viewport-768.png'])

  assert.equal(await digest(appBuild), hostBefore, 'the host build must be byte-identical after the gate')
  console.log(JSON.stringify({
    hostDigest: hostBefore, hostUnchanged: true, screenshots: 'viewport-360.png / viewport-768.png in the evidence tree',
    geometry: { '360': a.rects, '768': b.rects }, pageOverflowX: { '360': a.pageOverflowX, '768': b.pageOverflowX },
    pollution: a.pollution, themeFollowsHost: a.themeFollowsHost, tabFromInput: result.tabFromInput,
  }, null, 2))
} finally {
  await rm(tmp, { recursive: true, force: true })
}
