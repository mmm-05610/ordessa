import * as api from '@ordessa/extension-api'
import type { Catalog, Diagnostic } from './manifest'
export type { Catalog, Diagnostic, ExtensionDescriptor, Manifest } from './manifest'
type Module = { default?: unknown }
export async function loadExtensions(catalog: Catalog, importModule: (url: string) => Promise<Module> = url => import(/* @vite-ignore */ url), timeoutMs = 5000) {
  const plugins: api.Plugin<any>[] = []
  const failures: Diagnostic[] = [...catalog.failures]
  const results = await Promise.all(catalog.extensions.map(async extension => {
    const id = extension.manifest.id
    try {
      const plugin = await bounded(async () => {
        const module = await importModule(extension.url)
        if (typeof module.default !== 'function') throw Error('Entry must export a default plugin factory')
        // The second argument is this extension's opaque product configuration
        // (absent when the product configured nothing); the host does not read it.
        const plugin = await module.default(api, extension.config)
        if (!plugin || plugin.id !== id || typeof plugin.activate !== 'function') throw Error('Plugin identity or activate is invalid')
        return plugin
      }, timeoutMs)
      return plugin
    } catch (error) { failures.push({ id, error: String(error) }) }
  }))
  plugins.push(...results.filter((p): p is api.Plugin<any> => p !== undefined))
  // Refuse all conflicting providers, rather than let directory order choose a winner.
  const ids = new Map<string, number>(), providers = new Map<object, number>()
  for (const p of plugins) {
    ids.set(p.id, (ids.get(p.id) ?? 0) + 1)
    if (p.provides) providers.set(p.provides, (providers.get(p.provides) ?? 0) + 1)
  }
  return {
    failures,
    plugins: plugins.filter(p => {
      if (ids.get(p.id)! > 1 || (p.provides && providers.get(p.provides)! > 1)) {
        failures.push({ id: p.id, error: 'Duplicate plugin or service provider' })
        return false
      }
      return true
    }),
  }
}

function bounded<T>(operation: () => Promise<T>, timeoutMs: number): Promise<T> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(Error('Module/factory loading timed out; late result ignored')), timeoutMs)
    Promise.resolve().then(operation).then(resolve, reject).finally(() => clearTimeout(timer))
  })
}
