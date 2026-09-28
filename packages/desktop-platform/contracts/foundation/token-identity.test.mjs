import assert from 'node:assert/strict'
import { build } from 'esbuild'
import { createRequire } from 'node:module'
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { test } from 'node:test'

const repoRoot = path.resolve(import.meta.dirname, '../../../..')

test('built foundation carrier reuses the shared UI components Token artifact', async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), 'ordessa-c7-token-'))
  const previousOutput = process.env.ORDESSA_PRODUCT_OUTPUT_ROOT
  try {
    process.env.ORDESSA_PRODUCT_OUTPUT_ROOT = path.join(root, 'output')
    const { buildExtension } = await import('../../../../tooling/build-extension.mjs')
    await buildExtension(import.meta.dirname, { entries: { entry: 'src/entry.ts', contract: 'src/contract.ts' } })

    // Build the shared API separately, as the desktop build does. The second
    // build emulates the browser import map when loading the already-built
    // carrier. If the carrier bundled another Token, identity is false.
    const shared = path.join(root, 'shared.mjs')
    await build({ entryPoints: [path.join(repoRoot, 'packages/desktop-platform/ui-components/api/ui-components.ts')],
      outfile: shared, bundle: true, platform: 'browser', format: 'esm',
      external: ['@ordessa/extension-api'] })
    const probe = path.join(root, 'probe.mjs')
    await writeFile(probe,
      'import { UiComponentsToken as carrier } from "./output/extensions/ordessa.contracts/contract.js";\n' +
      'import { UiComponentsToken as shared } from "./shared.mjs";\n' +
      'export const same = carrier === shared;\n')
    const executable = path.join(root, 'probe-built.cjs')
    await build({ entryPoints: [probe], outfile: executable, bundle: true,
      platform: 'node', format: 'cjs', plugins: [{ name: 'browser-shared-import-map', setup(build) {
        build.onResolve({ filter: /^@ordessa\/ui-components\/api$/ }, () => ({ path: shared }))
        build.onResolve({ filter: /^@ordessa\/extension-api$/ }, () => ({
          path: path.join(repoRoot, 'packages/desktop-platform/extension-api/src/index.ts'),
        }))
      } }] })
    assert.equal(createRequire(import.meta.url)(executable).same, true)
  } finally {
    if (previousOutput === undefined) delete process.env.ORDESSA_PRODUCT_OUTPUT_ROOT
    else process.env.ORDESSA_PRODUCT_OUTPUT_ROOT = previousOutput
    await rm(root, { recursive: true, force: true })
  }
})
