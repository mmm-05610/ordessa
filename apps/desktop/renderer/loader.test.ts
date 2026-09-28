import { afterEach, describe, expect, it } from 'vitest'
import { mkdtemp, mkdir, writeFile, symlink, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { discover, confinedFile } from '@ordessa/extension-host/main'
import { protocolHandler } from '@ordessa/extension-host/main'
import { parseManifest } from '@ordessa/extension-loader/manifest'
import { loadExtensions } from '@ordessa/extension-loader'
import { scoped, Token } from '@ordessa/extension-api'
import { runtime } from '@ordessa/extension-host'
const dirs: string[] = []
const manifest = { id: 'test.one', version: '0.1.0', hostApi: '2', entry: 'entry.js' }
it('bounds a stalled factory, preserves healthy modules, and ignores late results', async () => {
  let finish!: (value: unknown) => void
  const pending = new Promise(resolve => { finish = resolve })
  const result = await loadExtensions({ failures: [], extensions: [
    { manifest, url: 'slow' },
    { manifest: { ...manifest, id: 'test.healthy' }, url: 'healthy' },
  ] }, async url => ({ default: () => url === 'slow' ? pending : { id: 'test.healthy', activate() {} } }), 10)
  expect(result.plugins.map(p => p.id)).toEqual(['test.healthy'])
  expect(result.failures[0].error).toContain('timed out')
  finish({ id: 'test.one', activate() {} })
  await new Promise(resolve => setTimeout(resolve, 0))
  expect(result.plugins.map(p => p.id)).toEqual(['test.healthy'])
})
async function fixture() {
  const root = await mkdtemp(path.join(tmpdir(), 'ordessa-loader-test-')); dirs.push(root)
  await mkdir(path.join(root, 'extensions', 'one'), { recursive: true })
  await writeFile(path.join(root, 'extensions', 'one', 'manifest.json'), JSON.stringify(manifest))
  await writeFile(path.join(root, 'extensions', 'one', 'entry.js'), 'export default () => ({})')
  return root
}
async function enable(root: string, enabled = ['test.one']) { await writeFile(path.join(root, 'extensions.json'), JSON.stringify({ enabled })) }
afterEach(async () => { for (const dir of dirs.splice(0)) await rm(dir, { recursive: true, force: true }) })
describe('extension discovery and confinement', () => {
  it('uses bundled defaults only when user approval is absent; malformed or empty override never falls back', async () => {
    const bundled = await fixture(), user = await fixture()
    await enable(bundled)
    // Avoid an identity collision with the bundled fixture.
    await rm(path.join(user, 'extensions/one'), { recursive: true })
    expect((await discover(user, bundled)).installed.has('test.one')).toBe(true)
    await enable(user, [])
    expect((await discover(user, bundled)).installed.size).toBe(0)
    await writeFile(path.join(user, 'extensions.json'), 'invalid')
    expect((await discover(user, bundled)).installed.size).toBe(0)
  })
  it('does not enable discovered code without explicit approval', async () => {
    const root = await fixture()
    expect((await discover(root)).catalog.extensions).toEqual([])
    await enable(root, [])
    expect((await discover(root)).installed.size).toBe(0)
    await enable(root)
    expect((await discover(root)).catalog.extensions).toHaveLength(1)
  })
  it('fails closed for malformed approval', async () => {
    const root = await fixture()
    await writeFile(path.join(root, 'extensions.json'), '{"enabled":"all"}')
    const result = await discover(root)
    expect(result.installed.size).toBe(0)
    expect(result.catalog.failures[0].id).toBe('configuration')
  })
  it.each(['../entry.js', '/tmp/entry.js', 'file:///tmp/a.js', 'dist\\a.js', 'dist/%2e%2e/a.js'])('rejects invalid entry %s', entry => {
    expect(() => parseManifest({ ...manifest, entry })).toThrow()
  })
  it('requires an enabled native entry to exist inside its extension', async () => {
    expect(() => parseManifest({ ...manifest, native: '../escape.js' })).toThrow('Invalid native entry')
    const root = await fixture(); await enable(root)
    const extension = path.join(root, 'extensions', 'one')
    await writeFile(path.join(extension, 'manifest.json'), JSON.stringify({ ...manifest, native: 'native.js' }))
    const result = await discover(root)
    expect(result.installed.size).toBe(0)
    expect(result.catalog.failures.some(f => f.id === manifest.id)).toBe(true)
    await writeFile(path.join(extension, 'native.js'), 'export default () => ({})')
    expect((await discover(root)).installed.size).toBe(1)
  })
  it('rejects incompatible versions', () => {
    expect(() => parseManifest({ ...manifest, hostApi: '1' })).toThrow('Incompatible')
  })
  it('rejects duplicate identities without a directory-order winner', async () => {
    const root = await fixture(); await enable(root)
    await mkdir(path.join(root, 'extensions', 'two'))
    await writeFile(path.join(root, 'extensions', 'two', 'manifest.json'), JSON.stringify(manifest))
    const result = await discover(root)
    expect(result.installed.size).toBe(0)
    expect(result.catalog.failures.some(f => f.error === 'Duplicate extension id')).toBe(true)
  })
  it('rejects file symlinks escaping the installed package', async () => {
    const root = await fixture()
    await writeFile(path.join(root, 'outside.js'), 'outside')
    await symlink(path.join(root, 'outside.js'), path.join(root, 'extensions', 'one', 'escape.js'))
    await expect(confinedFile(path.join(root, 'extensions', 'one'), 'escape.js')).rejects.toThrow('escapes')
  })
  it('does not discover a symlinked package directory', async () => {
    const root = await fixture(); await enable(root)
    await symlink(path.join(root, 'extensions', 'one'), path.join(root, 'extensions', 'alias'))
    expect((await discover(root)).catalog.extensions).toHaveLength(1)
  })
  it('protocol rejects disabled packages, foreign hosts and unsupported files', async () => {
    const root = await fixture()
    const denied = protocolHandler(root, await discover(root))
    expect((await denied({ url: 'ordessa://desktop/extensions/test.one/entry.js', method: 'GET' })).status).toBe(403)
    await enable(root)
    const handler = protocolHandler(root, await discover(root))
    expect((await handler({ url: 'ordessa://other/main.js', method: 'GET' })).status).toBe(403)
    expect((await handler({ url: 'ordessa://desktop/extensions/test.one/entry.js', method: 'POST' })).status).toBe(403)
    expect((await handler({ url: 'ordessa://desktop/extensions/test.one/%2e%2e%2foutside.js', method: 'GET' })).status).toBe(404)
    expect((await handler({ url: 'ordessa://desktop/extensions/test.one/entry.js', method: 'GET' })).status).toBe(200)
    expect((await handler({ url: 'ordessa://desktop/extensions/test.one/private.txt', method: 'GET' })).status).toBe(415)
  })
})
describe('module validation', () => {
  const descriptor = { manifest, url: 'ordessa://desktop/extensions/test.one/entry.js' }
  it('isolates rejected imports and factory identity failures', async () => {
    const bad = { manifest: { ...manifest, id: 'test.bad' }, url: 'bad' }
    const result = await loadExtensions({ extensions: [bad, descriptor], failures: [] }, async url => {
      if (url === 'bad') throw Error('invalid code')
      return { default: () => scoped({ id: 'test.one', activate() {} }) }
    })
    expect(result.plugins).toHaveLength(1); expect(result.failures).toHaveLength(1)
    const mismatch = await loadExtensions({ extensions: [descriptor], failures: [] }, async () => ({ default: () => ({ id: 'wrong', activate() {} }) }))
    expect(mismatch.plugins).toEqual([])
    expect(mismatch.failures).toHaveLength(1)
  })
  it('rejects all duplicate providers but keeps unrelated plugins', async () => {
    const token = new Token<number>('test')
    const result = await loadExtensions({ extensions: ['test.a', 'test.b', 'test.ok'].map(id => ({ manifest: { ...manifest, id }, url: id })), failures: [] },
      async id => ({ default: () => scoped({ id, ...(id === 'test.ok' ? {} : { provides: token }), activate: () => 1 }) }))
    expect(result.plugins.map(p => p.id)).toEqual(['test.ok'])
    expect(result.failures).toHaveLength(2)
  })
  it('missing service does not prevent an unrelated loaded plugin starting', async () => {
    let healthy = false
    const app = runtime([
      scoped({ id: 'bad', autoStart: true, requires: [new Token('absent')], activate() {} }),
      scoped({ id: 'healthy', autoStart: true, activate() { healthy = true } }),
    ])
    await app.start()
    expect(healthy).toBe(true); expect(app.failures.map(f => f.id)).toEqual(['bad'])
  })
  it('a dependency cycle is diagnosed without aborting unrelated startup', async () => {
    const a = new Token<number>('a'), b = new Token<number>('b')
    let healthy = false
    const app = runtime([
      scoped({ id: 'a', autoStart: true, provides: a, requires: [b], activate: () => 1 }),
      scoped({ id: 'b', autoStart: true, provides: b, requires: [a], activate: () => 2 }),
      scoped({ id: 'healthy', autoStart: true, activate() { healthy = true } }),
    ])
    await app.start()
    expect(healthy).toBe(true)
    expect(app.failures.length).toBeGreaterThan(0)
    expect(app.failures.some(f => f.id === 'healthy')).toBe(false)
  })
})

// C7 assembly接线: the host forwards the product's per-extension configuration to
// the entry factory without interpreting it, and refuses a malformed map.
describe('product configuration pass-through', () => {
  it('forwards only the configuration of the enabled extension and omits an unset one', async () => {
    const root = await fixture()
    await mkdir(path.join(root, 'extensions', 'two'), { recursive: true })
    await writeFile(path.join(root, 'extensions', 'two', 'manifest.json'), JSON.stringify({ ...manifest, id: 'test.two' }))
    await writeFile(path.join(root, 'extensions', 'two', 'entry.js'), 'export default () => ({})')
    const selection = [{ componentId: 'example.card', major: 1, providerId: 'provider-a' }]
    await writeFile(path.join(root, 'extensions.json'), JSON.stringify({
      enabled: ['test.one', 'test.two'], config: { 'test.one': selection },
    }))
    const catalog = (await discover(root)).catalog
    const one = catalog.extensions.find(entry => entry.manifest.id === 'test.one')
    const two = catalog.extensions.find(entry => entry.manifest.id === 'test.two')
    expect(one?.config).toEqual(selection)
    expect(two === undefined || 'config' in two).toBe(false)
  })
  it('fails closed when the configuration map is not an object keyed by valid ids', async () => {
    for (const bad of [['list'], 'scalar', { 'BAD ID': {} }, 7]) {
      const root = await fixture()
      await enable(root)
      await writeFile(path.join(root, 'extensions.json'), JSON.stringify({ enabled: ['test.one'], config: bad }))
      const result = await discover(root)
      expect(result.installed.size).toBe(0)
      expect(result.catalog.failures.some(failure => failure.id === 'configuration')).toBe(true)
    }
  })
  it('passes the configuration into the entry factory, and undefined when the product set none', async () => {
    const seen: [string, unknown][] = []
    const result = await loadExtensions({ failures: [], extensions: [
      { manifest, url: 'with-config', config: ['selection'] },
      { manifest: { ...manifest, id: 'test.two' }, url: 'no-config' },
    ] }, async url => ({ default: (_api: unknown, config: unknown) => {
      seen.push([url, config])
      return { id: url === 'with-config' ? 'test.one' : 'test.two', activate() {} }
    } }))
    expect(result.plugins.map(plugin => plugin.id)).toEqual(['test.one', 'test.two'])
    expect(seen).toEqual([['with-config', ['selection']], ['no-config', undefined]])
  })
})
