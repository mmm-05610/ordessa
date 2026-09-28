import { build } from 'esbuild'
import { mkdir } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
await import('../../../tooling/build-all.mjs')
await mkdir(path.join(root, 'dist/renderer/shared'), { recursive: true })
// All shared entrypoints are one splitting build, so React and API have one identity.
await build({
  entryPoints: Object.fromEntries(['react', 'jsx-runtime', 'react-dom', 'react-dom-client', 'api', 'ui-components-api'].map(name => [name, path.join(root, 'renderer/shared/' + name + '.ts')])),
  outdir: path.join(root, 'dist/renderer/shared'), bundle: true, splitting: true,
  platform: 'browser', format: 'esm', target: 'chrome132',
  define: { 'process.env.NODE_ENV': '"production"' },
})
await build({
  entryPoints: [path.join(root, 'renderer/main.tsx')], outfile: path.join(root, 'dist/renderer/main.js'),
  bundle: true, platform: 'browser', format: 'esm', target: 'chrome132', jsx: 'automatic',
  external: ['react', 'react/*', 'react-dom', 'react-dom/*', '@ordessa/extension-api'],
  loader: { '.css': 'css' },
})
for (const name of ['main', 'preload']) await build({
  entryPoints: [path.join(root, 'electron/' + name + '.ts')],
  outfile: path.join(root, 'dist', name === 'main' ? 'electron-main.cjs' : 'preload.cjs'),
  bundle: true, platform: 'node', format: 'cjs', target: 'node22', external: ['electron'],
})
