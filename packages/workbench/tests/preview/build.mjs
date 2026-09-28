// Bundles the preview fixture (entry.tsx) into dist/preview.js with the repo's
// own esbuild. All specifiers resolve at build time; the artifact makes zero
// external runtime requests.
import path from 'node:path'
import { build } from 'esbuild'

const here = import.meta.dirname
const repoRoot = path.resolve(here, '../../../..')

// Mirrors tooling/vitest-extensions.mjs contractAliases() plus the
// @ordessa/extension-api workspace package export (both are TS sources).
const alias = {
  '@extensions/ordessa.contracts/contract.js': path.join(repoRoot, 'packages/desktop-platform/contracts/foundation/src/contract.ts'),
  '@ordessa/extension-api': path.join(repoRoot, 'packages/desktop-platform/extension-api/src/index.ts'),
}

await build({
  entryPoints: [path.join(here, 'entry.tsx')],
  outfile: path.join(here, 'dist/preview.js'),
  bundle: true,
  format: 'iife',
  platform: 'browser',
  target: 'chrome120',
  jsx: 'automatic',
  alias,
  loader: { '.ts': 'ts', '.tsx': 'tsx' },
  // react/react-dom resolve from the root node_modules through normal Node
  // walk-up; pin the environment so their dev branches are selectable in a browser.
  define: { 'process.env.NODE_ENV': '"development"' },
  sourcemap: true,
  logLevel: 'info',
})
