import { afterEach, expect, it } from 'vitest'
import { mkdtemp, mkdir, readFile, rm, symlink, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { protocolHandler } from '../src/main/extension-protocol'
import type { Discovery } from '../src/main/extensions'

const roots: string[] = []
afterEach(async () => { await Promise.all(roots.splice(0).map(root => rm(root, { recursive: true, force: true }))) })

async function fixture() {
  const root = await mkdtemp(path.join(tmpdir(), 'ordessa-host-protocol-'))
  roots.push(root)
  const renderer = path.join(root, 'renderer')
  const extension = path.join(root, 'extension')
  await mkdir(path.join(renderer, 'shared'), { recursive: true })
  await mkdir(extension)
  const discovery = { catalog: { extensions: [], failures: [] },
    installed: new Map([['sample.extension', { root: extension, manifest: {} }]]) } as unknown as Discovery
  return { root, renderer, extension, handler: protocolHandler(renderer, discovery) }
}

it('publishes exactly one ui-components API import to the renderer shared URL', async () => {
  const { handler } = await fixture()
  const response = await handler({ url: 'ordessa://desktop/index.html', method: 'GET' })
  expect(response.status).toBe(200)
  const html = await response.text()
  const maps = [...html.matchAll(/<script\b[^>]*type="importmap"[^>]*>([^<]*)<\/script>/g)]
  expect(maps).toHaveLength(1)
  expect(maps[0][1].match(/"@ordessa\/ui-components\/api"\s*:/g)).toHaveLength(1)
  const imports = (JSON.parse(maps[0][1]) as { imports: Record<string, string> }).imports
  expect(imports['@ordessa/ui-components/api']).toBe('/shared/ui-components-api.js')
  expect(Object.keys(imports).filter(key => key === '@ordessa/ui-components/api')).toHaveLength(1)
  expect(Object.values(imports).filter(value => value === '/shared/ui-components-api.js')).toHaveLength(1)
})

it('serves mapped shared bytes only from confined renderer root', async () => {
  const { root, renderer, extension, handler } = await fixture()
  await mkdir(path.join(extension, 'shared'))
  await writeFile(path.join(renderer, 'shared/ui-components-api.js'), 'renderer-token')
  await writeFile(path.join(extension, 'shared/ui-components-api.js'), 'extension-token')
  const shared = await handler({ url: 'ordessa://desktop/shared/ui-components-api.js', method: 'GET' })
  expect(shared.status).toBe(200)
  expect(shared.headers.get('content-type')).toBe('text/javascript')
  expect(await shared.text()).toBe('renderer-token')
  const extensionResult = await handler({ url: 'ordessa://desktop/extensions/sample.extension/shared/ui-components-api.js', method: 'GET' })
  expect(extensionResult.status).toBe(200)
  expect(await extensionResult.text()).toBe('extension-token')

  await rm(path.join(renderer, 'shared/ui-components-api.js'))
  const outside = path.join(root, 'outside.js')
  await writeFile(outside, 'outside-token')
  await symlink(outside, path.join(renderer, 'shared/ui-components-api.js'))
  const escaped = await handler({ url: 'ordessa://desktop/shared/ui-components-api.js', method: 'GET' })
  expect(escaped.status).toBe(404)
  expect(await readFile(outside, 'utf8')).toBe('outside-token')
  expect((await handler({ url: 'ordessa://desktop/shared/ui-components-api.js', method: 'POST' })).status).toBe(403)
})
