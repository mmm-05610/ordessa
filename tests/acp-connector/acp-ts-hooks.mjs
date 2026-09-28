// Scoped Node customization hooks: in vitest's jsdom (vite "client") environment a computed
// `import(fileUrl)` is rewritten to the vite dev-server URL (http://localhost:…/…entry.ts) and
// then handed to the native loader. These hooks map ONLY such requests back to the real files —
// (1) http URLs whose path ends in .ts under the product tree → the same file on disk,
// (2) extensionless relative imports inside the connector/contract chain → .ts,
// (3) the same `@extensions/...` contract aliases the product's vite configs use, and
// (4) .ts sources of that chain transpiled with esbuild. Everything else passes through
// untouched. The seam still executes the production module against the production contracts;
// nothing is re-implemented or stubbed.
import { readFile } from 'node:fs/promises'
import { existsSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath, pathToFileURL, URL } from 'node:url'
import { transformSync } from 'esbuild'
import { contractAliases } from '../../tooling/vitest-extensions.mjs'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
const SRC_DIR = path.join(ROOT, 'plugins/connectors/acp/src/')
// The one contract-alias map the product's vitest configs also use, so this loader can never
// resolve `@extensions/<id>/contract.js` to a different module than the product does.
const ALIASES = new Map(Object.entries(contractAliases()))
// The TypeScript roots the native loader may meet inside the connector chain (production sources only).
// `packages/desktop-platform/connections/` is reached because the contracts foundation carrier re-exports
// the Connections platform API (single shared Token/kind copy), so the platform sources are part of that
// chain from now on; without it the loader hands a raw .ts file to Node and the rig dies on syntax.
// `packages/workbench/api/` is reached the same way: the contracts Agent connection API builds its
// connection kind through the platform carrier's single shared `createConnectionKind`, so the chain
// now crosses into the Workbench public API that foundation re-exports.
// `plugins/agent/contracts/` is the domain carrier reached the same way: its `connections.ts` builds
// the Agent connection kind through the platform carrier's single shared `createConnectionKind`.
const TS_DIRS = [SRC_DIR, path.join(ROOT, 'packages/desktop-platform/contracts/'), path.join(ROOT, 'packages/desktop-platform/connections/'), path.join(ROOT, 'packages/desktop-platform/extension-api/'), // the C7 api rides the foundation carrier, so the rig has to transpile it too
path.join(ROOT, 'packages/desktop-platform/ui-components/'), path.join(ROOT, 'packages/workbench/api/'), path.join(ROOT, 'plugins/agent/contracts/')]
const tsTree = file => TS_DIRS.some(dir => file.startsWith(dir))

export async function resolve(specifier, context, nextResolve) {
  if (/^https?:/.test(specifier)) {
    const pathname = new URL(specifier).pathname.replace(/^\/@fs(?=\/)/, '')
    const file = fileURLToPath(`file://${pathname}`)
    if (file.endsWith('.ts') && existsSync(file)) return { url: pathToFileURL(file).href, shortCircuit: true }
    return nextResolve(specifier, context)
  }
  if (specifier.endsWith('.ts') && path.isAbsolute(specifier))
    return { url: pathToFileURL(specifier).href, shortCircuit: true }
  const alias = ALIASES.get(specifier)
  if (alias) return { url: pathToFileURL(alias).href, shortCircuit: true }
  const parentFile = context.parentURL?.startsWith('file:') ? fileURLToPath(context.parentURL) : undefined
  if (specifier.startsWith('.') && parentFile && tsTree(parentFile)) {
    const base = fileURLToPath(new URL(specifier, context.parentURL))
    if (!existsSync(base) && existsSync(`${base}.ts`))
      return { url: pathToFileURL(`${base}.ts`).href, shortCircuit: true }
  }
  return nextResolve(specifier, context)
}

export async function load(url, context, nextLoad) {
  if (url.startsWith('file:') && url.endsWith('.ts') && tsTree(fileURLToPath(url)))
    return { format: 'module', shortCircuit: true, source: transformSync(await readFile(fileURLToPath(url), 'utf8'), { loader: 'ts', format: 'esm' }).code }
  return nextLoad(url, context)
}
