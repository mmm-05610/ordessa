import { cp, mkdir, readdir, readFile, rm, writeFile } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import { execFile } from 'node:child_process'
import path from 'node:path'
import { promisify } from 'node:util'
import { outputRoot } from './build-extension.mjs'

const repoRoot = path.resolve(import.meta.dirname, '..')
const run = promisify(execFile)

// T029 (CN-08) variant-build override — default-preserving: unset, this script
// behaves exactly as before. ORDESSA_PRODUCT_MANIFEST points the enabled-list at
// an alternative product manifest; ORDESSA_PRODUCT_OUTPUT_ROOT (consumed by
// tooling/build-extension.mjs, so it propagates to the per-package child builds
// through the environment) relocates every artifact and skips the lock write,
// letting a guard build a variant product without ever touching
// products/desktop/dist or extensions.lock.json.
const productFile = process.env.ORDESSA_PRODUCT_MANIFEST
  ? path.resolve(process.env.ORDESSA_PRODUCT_MANIFEST)
  : path.join(repoRoot, 'products/desktop/extensions.json')
const variant = process.env.ORDESSA_PRODUCT_OUTPUT_ROOT !== undefined

const enabled = JSON.parse(await readFile(productFile, 'utf8')).enabled
if (!Array.isArray(enabled) || enabled.some(id => typeof id !== 'string' || !id) || new Set(enabled).size !== enabled.length)
  throw Error('Product enabled extensions must be a unique list of ids')

// Discovery only builds an index. A package is admitted by the product list, not its presence.
const packages = new Map()
async function scan(dir) {
  // The root of a discovery scan may itself be an extension package (packages/workbench);
  // index it before descending so no root layout assumption is baked in here.
  try {
    const { ordessa } = JSON.parse(await readFile(path.join(dir, 'package.json'), 'utf8'))
    if (ordessa?.id) {
      if (packages.has(ordessa.id)) throw Error(`Duplicate extension package ${ordessa.id}`)
      packages.set(ordessa.id, dir)
    }
  } catch (error) {
    if (error?.code !== 'ENOENT') throw error
  }
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    if (!entry.isDirectory() || entry.name === 'dist' || entry.name === 'node_modules') continue
    await scan(path.join(dir, entry.name))
  }
}
for (const root of ['packages/desktop-platform/contracts', 'packages/desktop-platform/connections', 'packages/desktop-platform/ui-components', 'packages/workbench', 'plugins']) await scan(path.join(repoRoot, root))

// esbuild externalizes @extensions/* imports. Require every referenced contract in the admitted
// set, including type-only imports, so a local bundle cannot conceal a missing product dependency.
async function sourceDependencies(dir) {
  const found = new Set()
  async function walk(folder) {
    for (const entry of await readdir(folder, { withFileTypes: true })) {
      const file = path.join(folder, entry.name)
      if (entry.isDirectory()) await walk(file)
      else if (/\.[cm]?[jt]sx?$/.test(entry.name)) {
        for (const match of (await readFile(file, 'utf8')).matchAll(/@extensions\/([a-z0-9.-]+)\//g)) found.add(match[1])
      }
    }
  }
  await walk(path.join(dir, 'src'))
  return found
}
for (const id of enabled) {
  const dir = packages.get(id)
  if (!dir) throw Error(`Enabled extension ${id} has no package`)
  for (const dependency of await sourceDependencies(dir)) {
    if (!enabled.includes(dependency)) throw Error(`Enabled extension ${id} requires disabled ${dependency}`)
  }
}

const extensionsRoot = path.join(outputRoot, 'extensions')
await rm(extensionsRoot, { recursive: true, force: true })
await mkdir(extensionsRoot, { recursive: true })

// Every package always builds through its own real build.mjs; the variant root
// reaches it through the inherited ORDESSA_PRODUCT_OUTPUT_ROOT.
for (const id of enabled) {
  await run(process.execPath, [path.join(packages.get(id), 'build.mjs')], { cwd: repoRoot, stdio: 'inherit' })
}
await cp(productFile, path.join(outputRoot, 'extensions.json'))

const actual = (await readdir(extensionsRoot, { withFileTypes: true })).filter(entry => entry.isDirectory()).map(entry => entry.name).sort()
if (JSON.stringify(actual) !== JSON.stringify([...enabled].sort())) throw Error('Built extension set differs from product enabled list')

if (!variant) {
  const files = {}
  async function digest(dir) {
    for (const entry of (await readdir(dir, { withFileTypes: true })).sort((a, b) => a.name.localeCompare(b.name))) {
      if (entry.isDirectory()) { await digest(path.join(dir, entry.name)); continue }
      const file = path.join(dir, entry.name)
      files[path.relative(outputRoot, file).split(path.sep).join('/')] = createHash('sha256').update(await readFile(file)).digest('hex')
    }
  }
  await digest(extensionsRoot)
  const lock = { enabled, files }
  await writeFile(path.join(repoRoot, 'products/desktop/extensions.lock.json'), JSON.stringify(lock, null, 2) + '\n')
  console.log(`Built ${enabled.length} enabled extensions into products/desktop/dist`)
} else {
  console.log(`Built ${enabled.length} extensions of ${productFile} into ${outputRoot} (variant mode: real product output and lock untouched)`)
}
