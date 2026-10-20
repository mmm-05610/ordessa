import { afterEach, expect, it } from 'vitest'
import { mkdtemp, mkdir, readFile, rm, symlink, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { randomUUID } from 'node:crypto'
import { discover, protocolHandler } from '@ordessa/extension-host/main'
import { loadExtensions } from '@ordessa/extension-loader'
import { runtime } from '@ordessa/extension-host'

const ID = 'provenance.extension'
const manifest = { id: ID, version: '1.0.0', hostApi: '2', entry: 'entry.js' }
const roots: string[] = []
const activationKeys: string[] = []
const runtimes: ReturnType<typeof runtime>[] = []
const globals = globalThis as unknown as Record<string, unknown>

afterEach(async () => {
  try {
    for (const app of runtimes.splice(0).reverse()) {
      if (app.getSnapshot().some(state => state.id === ID && state.phase === 'active')) {
        await app.deactivate(ID)
      }
    }
  } finally {
    for (const key of activationKeys.splice(0)) delete globals[key]
    await Promise.all(roots.splice(0).map(root => rm(root, { recursive: true, force: true })))
  }
})

async function fixture(enabled: string[] = [ID]) {
  const root = await mkdtemp(path.join(tmpdir(), 'ordessa-loader-provenance-'))
  roots.push(root)
  const dataRoot = path.join(root, 'user-data')
  const extensionRoot = path.join(dataRoot, 'extensions', ID)
  const rendererRoot = path.join(root, 'renderer')
  await mkdir(extensionRoot, { recursive: true })
  await mkdir(rendererRoot, { recursive: true })
  await writeFile(path.join(extensionRoot, 'manifest.json'), JSON.stringify(manifest))
  await writeFile(path.join(dataRoot, 'extensions.json'), JSON.stringify({ enabled }))
  const activationKey = '__ordessa_provenance_' + randomUUID().replaceAll('-', '')
  activationKeys.push(activationKey)
  globals[activationKey] = 'not-activated'
  const source = `export default api => api.scoped({ id: ${JSON.stringify(ID)}, autoStart: true, activate() { globalThis[${JSON.stringify(activationKey)}] = 'activated' } })`
  await writeFile(path.join(extensionRoot, manifest.entry), source)
  return { root, dataRoot, extensionRoot, rendererRoot, source, activationKey }
}

function extensionUrl(id = ID, entry = manifest.entry) {
  return `ordessa://desktop/extensions/${id}/${entry}`
}

it('loads and activates only the exact enabled source served by the host protocol', async () => {
  const f = await fixture()
  const discovery = await discover(f.dataRoot)
  expect(discovery.catalog.extensions).toHaveLength(1)
  expect(discovery.catalog.failures).toEqual([])
  const descriptor = discovery.catalog.extensions[0]
  expect(descriptor.manifest).toEqual(manifest)
  expect(descriptor.url).toBe(extensionUrl())
  expect(discovery.installed.get(ID)?.root).toBe(f.extensionRoot)

  const protocol = protocolHandler(f.rendererRoot, discovery)
  expect((await protocol({ url: 'ordessa://other/extensions/provenance.extension/entry.js', method: 'GET' })).status).toBe(403)
  expect((await protocol({ url: extensionUrl(ID, '%2e%2e%2foutside.js'), method: 'GET' })).status).toBe(404)

  const outside = path.join(f.root, 'outside.js')
  await writeFile(outside, 'outside-source-must-never-be-served')
  await symlink(outside, path.join(f.extensionRoot, 'linked.js'))
  const escaped = await protocol({ url: extensionUrl(ID, 'linked.js'), method: 'GET' })
  expect(escaped.status).toBe(404)
  expect(await readFile(outside, 'utf8')).toBe('outside-source-must-never-be-served')

  const imports: string[] = []
  const loaded = await loadExtensions(discovery.catalog, async url => {
    imports.push(url)
    const response = await protocol({ url, method: 'GET' })
    expect(response.status).toBe(200)
    expect(response.headers.get('content-type')).toBe('text/javascript')
    const served = Buffer.from(await response.arrayBuffer())
    expect(served.toString('utf8')).toBe(f.source)
    const dataUrl = 'data:text/javascript;base64,' + served.toString('base64')
    return import(dataUrl)
  })
  expect(imports).toEqual([descriptor.url])
  expect(loaded.failures).toEqual([])
  expect(loaded.plugins.map(plugin => plugin.id)).toEqual([ID])

  const app = runtime(loaded.plugins)
  runtimes.push(app)
  await app.start()
  expect(globals[f.activationKey]).toBe('activated')
  expect(app.getSnapshot()).toContainEqual({ id: ID, phase: 'active' })
})

it('keeps disabled and unknown IDs out of the Catalog, protocol response, and loader imports', async () => {
  const f = await fixture([])
  const disabled = await discover(f.dataRoot)
  expect(disabled.catalog.extensions).toEqual([])
  expect(disabled.installed.size).toBe(0)
  const disabledProtocol = protocolHandler(f.rendererRoot, disabled)
  expect((await disabledProtocol({ url: extensionUrl(), method: 'GET' })).status).toBe(403)

  let disabledImports = 0
  const disabledLoad = await loadExtensions(disabled.catalog, async () => {
    disabledImports += 1
    return { default: () => ({ id: ID, activate() {} }) }
  })
  expect(disabledLoad.plugins).toEqual([])
  expect(disabledImports).toBe(0)

  await writeFile(path.join(f.dataRoot, 'extensions.json'), JSON.stringify({ enabled: ['unknown.extension'] }))
  const unknown = await discover(f.dataRoot)
  expect(unknown.catalog.extensions).toEqual([])
  expect(unknown.installed.size).toBe(0)
  expect(unknown.catalog.failures).toContainEqual({
    id: 'unknown.extension', error: 'Enabled extension not found or invalid',
  })
  const unknownProtocol = protocolHandler(f.rendererRoot, unknown)
  expect((await unknownProtocol({ url: extensionUrl('unknown.extension'), method: 'GET' })).status).toBe(403)

  let unknownImports = 0
  const unknownLoad = await loadExtensions(unknown.catalog, async () => {
    unknownImports += 1
    return { default: () => ({ id: 'unknown.extension', activate() {} }) }
  })
  expect(unknownLoad.plugins).toEqual([])
  expect(unknownImports).toBe(0)
})
