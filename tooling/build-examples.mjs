import { build } from 'esbuild'
import { mkdir, copyFile } from 'node:fs/promises'
import path from 'node:path'
const repoRoot = path.resolve(import.meta.dirname, '..')
const root = path.join(repoRoot, 'examples')
for (const [folder, id, entries] of [
  ['agent-ui-probe', 'example.agent-ui', { entry: 'entry.tsx' }],
  ['hello-extension', 'example.hello', { entry: 'entry.tsx' }],
  ['service-contract', 'example.contracts', { entry: 'entry.ts', contract: 'contract.ts' }],
  ['service-provider', 'example.provider', { entry: 'entry.ts' }],
  ['service-provider-alt', 'example.provider-alt', { entry: 'entry.ts' }],
  ['service-consumer', 'example.consumer', { entry: 'entry.tsx' }],
  ['ui-contracts', 'example.ui-contracts', { entry: 'entry.ts', contract: 'contract.ts' }],
  ['ui-provider', 'example.ui-provider', { entry: 'entry.tsx' }],
  ['ui-provider-alt', 'example.ui-provider-alt', { entry: 'entry.tsx' }],
  ['ui-consumer', 'example.ui-consumer', { entry: 'entry.tsx' }],
  ['ui-foundations-probe', 'example.ui-foundations', { entry: 'entry.tsx' }],
]) {
  const output = path.join(root, 'dist', id)
  await mkdir(output, { recursive: true })
  await build({
    entryPoints: Object.fromEntries(Object.entries(entries).map(([name, file]) => [name, path.join(root, folder, 'src', file)])),
    outdir: output, bundle: true, splitting: true, format: 'esm', platform: 'browser', jsx: 'automatic',
    external: ['react', 'react/*', 'react-dom', 'react-dom/*', '@ordessa/extension-api', '@extensions/*'],
  })
  await copyFile(path.join(root, folder, 'manifest.json'), path.join(output, 'manifest.json'))
  if (id === 'example.agent-ui') await copyFile(path.join(repoRoot, 'node_modules/@assistant-ui/react/LICENSE'), path.join(output, 'assistant-ui-LICENSE'))
}
console.log('Built standalone examples into examples/dist; host was not rebuilt.')
