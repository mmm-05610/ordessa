import assert from 'node:assert/strict'
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { test } from 'node:test'

test('a browser extension imports the one shared UI components API', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'ordessa-shared-api-'))
  const priorOutput = process.env.ORDESSA_PRODUCT_OUTPUT_ROOT
  try {
    const extension = path.join(root, 'extension')
    await mkdir(extension)
    await writeFile(path.join(extension, 'package.json'), JSON.stringify({
      name: 'controlled-shared-api-consumer', ordessa: { id: 'controlled.shared-api' },
    }))
    await writeFile(path.join(extension, 'manifest.json'), '{}')
    await writeFile(path.join(extension, 'entry.js'),
      "import { UiComponentsToken, defineUiComponent } from '@ordessa/ui-components/api'\n" +
      "export const token = UiComponentsToken\n" +
      "export const key = defineUiComponent('controlled.shared', 1)\n")
    process.env.ORDESSA_PRODUCT_OUTPUT_ROOT = path.join(root, 'output')
    const { buildExtension } = await import('./build-extension.mjs')
    await buildExtension(extension, { entries: { entry: 'entry.js' } })
    const bundle = await readFile(path.join(root, 'output/extensions/controlled.shared-api/entry.js'), 'utf8')
    assert.match(bundle, /from ["']@ordessa\/ui-components\/api["']/)
    assert.doesNotMatch(bundle, /ordessa\.ui-components\.v1/)
  } finally {
    if (priorOutput === undefined) delete process.env.ORDESSA_PRODUCT_OUTPUT_ROOT
    else process.env.ORDESSA_PRODUCT_OUTPUT_ROOT = priorOutput
    await rm(root, { recursive: true, force: true })
  }
})
