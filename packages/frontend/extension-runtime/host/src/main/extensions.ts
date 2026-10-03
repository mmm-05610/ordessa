import { readFile, readdir, realpath, stat } from 'node:fs/promises'
import type { Dirent } from 'node:fs'
import path from 'node:path'
import { ID, parseManifest, safeRelative, type Catalog, type Manifest } from '@ordessa/extension-loader/manifest'

export interface Installed { manifest: Manifest; root: string }
export interface Discovery { catalog: Catalog; installed: Map<string, Installed> }
export async function confinedFile(root: string, relative: string): Promise<string> {
  if (!safeRelative(relative)) throw Error('Invalid relative path')
  const base = await realpath(root)
  const file = await realpath(path.join(base, relative))
  const rel = path.relative(base, file)
  if (!rel || rel.startsWith('..' + path.sep) || rel === '..' || path.isAbsolute(rel)) throw Error('Path escapes extension')
  if (!(await stat(file)).isFile()) throw Error('Expected regular file')
  return file
}
export async function discover(dataRoot: string, bundledRoot?: string): Promise<Discovery> {
  const catalog: Catalog = { extensions: [], failures: [] }, installed = new Map<string, Installed>()
  let enabled: string[] = []
  let productConfig: Record<string, unknown> = {}
  try {
    let source: string
    try { source = await readFile(path.join(dataRoot, 'extensions.json'), 'utf8') }
    catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'ENOENT' || !bundledRoot) throw error
      source = await readFile(path.join(bundledRoot, 'extensions.json'), 'utf8')
    }
    const config = JSON.parse(source)
    if (!Array.isArray(config.enabled) || !config.enabled.every((id: unknown) => typeof id === 'string' && ID.test(id)) ||
        new Set(config.enabled).size !== config.enabled.length) throw Error('enabled must be a unique id list')
    enabled = config.enabled
    // Optional per-extension configuration, opaque to the host and forwarded to the entry factory.
    if (config.config !== undefined) {
      if (typeof config.config !== 'object' || config.config === null || Array.isArray(config.config)) throw Error('config must be an object keyed by extension id')
      for (const key of Object.keys(config.config as Record<string, unknown>)) if (!ID.test(key)) throw Error('config key is not a valid extension id')
      productConfig = config.config as Record<string, unknown>
    }
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ENOENT') catalog.failures.push({ id: 'configuration', error: String(error) })
    return { catalog, installed } // Missing or malformed approval is fail-closed.
  }
  const candidates = new Map<string, Installed[]>()
  for (const origin of [...new Set([dataRoot, ...(bundledRoot ? [bundledRoot] : [])])]) {
    const extensionRoot = path.join(origin, 'extensions')
    let directories: Dirent[]
    try { directories = await readdir(extensionRoot, { withFileTypes: true }) }
    catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'ENOENT') catalog.failures.push({ id: 'discovery', error: String(error) })
      directories = []
    }
    for (const directory of directories.sort((a, b) => a.name.localeCompare(b.name))) {
      if (!directory.isDirectory()) continue // Reject directory symlinks.
      try {
        const root = path.join(extensionRoot, directory.name)
        const manifest = parseManifest(JSON.parse(await readFile(await confinedFile(root, 'manifest.json'), 'utf8')))
        const values = candidates.get(manifest.id) ?? []
        values.push({ root: await realpath(root), manifest })
        candidates.set(manifest.id, values)
      } catch (error) { catalog.failures.push({ id: directory.name, error: String(error) }) }
    }
  }
  for (const id of enabled) {
    const matches = candidates.get(id) ?? []
    if (matches.length !== 1) {
      catalog.failures.push({ id, error: matches.length ? 'Duplicate extension id' : 'Enabled extension not found or invalid' })
      continue
    }
    const extension = matches[0]
    try {
      await confinedFile(extension.root, extension.manifest.entry)
      if (extension.manifest.native) await confinedFile(extension.root, extension.manifest.native)
      installed.set(id, extension)
      catalog.extensions.push({
        manifest: extension.manifest,
        url: 'ordessa://desktop/extensions/' + id + '/' + extension.manifest.entry,
        ...(Object.hasOwn(productConfig, id) ? { config: productConfig[id] } : {}),
      })
    } catch (error) { catalog.failures.push({ id, error: String(error) }) }
  }
  return { catalog, installed }
}
