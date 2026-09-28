import { afterEach, expect, it } from 'vitest'
import { build } from 'esbuild'
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { fileURLToPath, pathToFileURL } from 'node:url'
import path from 'node:path'

const shared = path.dirname(fileURLToPath(import.meta.url))
const app = path.resolve(shared, '../..')
const roots: string[] = []
afterEach(async () => {
  for (const root of roots.splice(0)) await rm(root, { recursive: true, force: true })
})

it('publishes the UI Components API as an import-map entry sharing the extension Token', async () => {
  const buildScript = await readFile(path.join(app, 'scripts/build.mjs'), 'utf8')
  expect(buildScript).toContain("'ui-components-api'")

  const root = await mkdtemp(path.join(tmpdir(), 'ordessa-shared-ui-api-'))
  roots.push(root)
  await writeFile(path.join(root, 'package.json'), '{"type":"module"}')
  const result = await build({
    entryPoints: {
      api: path.join(shared, 'api.ts'),
      'ui-components-api': path.join(shared, 'ui-components-api.ts'),
    },
    outdir: root, bundle: true, splitting: true, platform: 'browser',
    format: 'esm', target: 'chrome132', metafile: true,
  })
  const uiEntry = path.join(root, 'ui-components-api.js')
  const output = Object.entries(result.metafile.outputs).find(([file]) => path.resolve(file) === uiEntry)
  expect(path.resolve(output?.[1].entryPoint ?? '')).toBe(path.join(shared, 'ui-components-api.ts'))
  const [{ Token }, { UiComponentsToken, defineUiComponent }] = await Promise.all([
    import(pathToFileURL(path.join(root, 'api.js')).href),
    import(pathToFileURL(uiEntry).href),
  ])
  expect(UiComponentsToken).toBeInstanceOf(Token)
  expect(defineUiComponent('example.card', 1)).toEqual({ id: 'example.card', major: 1 })

  // The platform carrier is a separate extension build. Resolve its bare
  // imports as the browser import map would, then compare object identity.
  const carrier = path.resolve(app, '../../packages/desktop-platform/contracts/foundation/src/contract.ts')
  const carrierFile = path.join(root, 'contract.js')
  await build({
    entryPoints: [carrier], outfile: carrierFile, bundle: true,
    platform: 'browser', format: 'esm', target: 'chrome132',
    external: ['@ordessa/extension-api', '@ordessa/ui-components/api'],
  })
  const carrierSource = (await readFile(carrierFile, 'utf8'))
    .replaceAll('"@ordessa/extension-api"', '"./api.js"')
    .replaceAll('"@ordessa/ui-components/api"', '"./ui-components-api.js"')
  await writeFile(carrierFile, carrierSource)
  const carrierModule = await import(pathToFileURL(carrierFile).href)
  expect(carrierModule.UiComponentsToken).toBe(UiComponentsToken)
})
