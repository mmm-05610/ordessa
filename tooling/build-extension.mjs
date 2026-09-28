import { build } from 'esbuild'
import { mkdir, copyFile, readFile } from 'node:fs/promises'
import path from 'node:path'
const repoRoot = path.resolve(import.meta.dirname, '..')
// ORDESSA_PRODUCT_OUTPUT_ROOT is a default-preserving override used by guards that
// build a VARIANT product (e.g. with one extension disabled) into a temp tree; unset,
// every artifact lands in the real product output. It lives here, on the single writer
// of extension artifacts, so a variant build still runs each package's real build.mjs
// rather than re-implementing this function somewhere else and drifting.
export const outputRoot = process.env.ORDESSA_PRODUCT_OUTPUT_ROOT
  ? path.resolve(process.env.ORDESSA_PRODUCT_OUTPUT_ROOT)
  : path.join(repoRoot, 'products/desktop/dist')

/** Builds one extension package from its declared ordessa segment; artifacts land at <outputRoot>/extensions/<id>. */
export async function buildExtension(dir, { entries, licenses = [] }) {
  const { ordessa } = JSON.parse(await readFile(path.join(dir, 'package.json'), 'utf8'))
  const target = path.join(outputRoot, 'extensions', ordessa.id)
  await mkdir(target, { recursive: true })
  await build({
    entryPoints: Object.fromEntries(Object.entries(entries).map(([name, file]) => [name, path.join(dir, file)])),
    outdir: target, bundle: true, splitting: true, format: 'esm', platform: 'browser', jsx: 'automatic',
    external: ['react', 'react/*', 'react-dom', 'react-dom/*', '@ordessa/extension-api',
      '@ordessa/ui-components/api', '@extensions/*'],
  })
  // Native entries run in Electron main; declared externals resolve from root node_modules.
  if (ordessa.native) await build({
    entryPoints: [path.join(dir, ordessa.native)], outfile: path.join(target, 'native.js'),
    bundle: true, platform: 'node', format: 'esm', target: 'node22', external: ordessa.nativeExternals ?? [],
  })
  await copyFile(path.join(dir, 'manifest.json'), path.join(target, 'manifest.json'))
  for (const [from, as] of licenses) await copyFile(path.join(repoRoot, 'node_modules', from), path.join(target, as))
}
