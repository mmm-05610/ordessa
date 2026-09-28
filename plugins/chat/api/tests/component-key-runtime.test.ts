import { afterEach, expect, it } from 'vitest'
import { build } from 'esbuild'
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { fileURLToPath, pathToFileURL } from 'node:url'
import path from 'node:path'

const here = path.dirname(fileURLToPath(import.meta.url))
const repo = path.resolve(here, '../../../..')
const roots: string[] = []
afterEach(async () => {
  for (const root of roots.splice(0)) await rm(root, { recursive: true, force: true })
})

it('constructs Chat keys through the shared C7 API used by the foundation carrier', async () => {
  const root = await mkdtemp(path.join(tmpdir(), 'ordessa-chat-key-runtime-'))
  roots.push(root)
  await writeFile(path.join(root, 'package.json'), '{"type":"module"}')
  const shared = path.join(repo, 'apps/desktop/renderer/shared')
  await build({
    entryPoints: { api: path.join(shared, 'api.ts'),
      'ui-components-api': path.join(shared, 'ui-components-api.ts') },
    outdir: root, bundle: true, splitting: true, platform: 'browser', format: 'esm',
  })
  const external = ['@ordessa/extension-api', '@ordessa/ui-components/api']
  for (const [name, source] of [
    ['foundation', path.join(repo, 'packages/desktop-platform/contracts/foundation/src/contract.ts')],
    ['chat', path.join(here, '../src/contract.ts')],
  ] as const) {
    const file = path.join(root, `${name}.js`)
    await build({ entryPoints: [source], outfile: file, bundle: true,
      platform: 'browser', format: 'esm', external })
    const output = await readFile(file, 'utf8')
    if (name === 'chat') expect(/from ["']@ordessa\/ui-components\/api["']/.test(output)).toBe(true)
    await writeFile(file, output
      .replaceAll('"@ordessa/extension-api"', '"./api.js"')
      .replaceAll('"@ordessa/ui-components/api"', '"./ui-components-api.js"'))
  }
  const [platform, foundation, chat] = await Promise.all([
    import(pathToFileURL(path.join(root, 'ui-components-api.js')).href),
    import(pathToFileURL(path.join(root, 'foundation.js')).href),
    import(pathToFileURL(path.join(root, 'chat.js')).href),
  ])
  expect(foundation.UiComponentsToken).toBe(platform.UiComponentsToken)
  expect(platform.registration(chat.ChatMessageBodyKey, 'controlled', () => null).key)
    .toBe(chat.ChatMessageBodyKey)
  expect(chat.defineChatComponentKey('ordessa.chat.custom', 1)).toEqual(
    platform.defineUiComponent('ordessa.chat.custom', 1))
})
