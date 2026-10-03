export interface Manifest { id: string; version: string; hostApi: string; entry: string; native?: string }
/**
 * `config` is this extension's slice of the product configuration, passed to the
 * entry factory verbatim. The host never inspects it, so an extension's options
 * stay product data instead of host branching (C7 assembly entry). Absent means
 * the product configured nothing, which is not the same as an empty option.
 */
export interface ExtensionDescriptor { manifest: Manifest; url: string; config?: unknown }
export interface Diagnostic { id: string; error: string }
export interface Catalog { extensions: ExtensionDescriptor[]; failures: Diagnostic[] }
export const ID = /^[a-z0-9]+(?:[.-][a-z0-9]+)*$/
export function safeRelative(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0 &&
    value.split('/').every(part => /^[a-zA-Z0-9_.-]+$/.test(part) && part !== '.' && part !== '..')
}
export function parseManifest(value: unknown): Manifest {
  if (!value || typeof value !== 'object') throw Error('Invalid manifest')
  const m = value as Record<string, unknown>
  if (typeof m.id !== 'string' || !ID.test(m.id) || m.id.length > 100) throw Error('Invalid extension id')
  if (typeof m.version !== 'string' || !/^\d+\.\d+\.\d+$/.test(m.version)) throw Error('Invalid version')
  if (m.hostApi !== '2') throw Error('Incompatible host API (expected 2)')
  if (!safeRelative(m.entry) || !m.entry.endsWith('.js')) throw Error('Invalid module entry')
  if (m.native !== undefined && (!safeRelative(m.native) || !m.native.endsWith('.js'))) throw Error('Invalid native entry')
  return { id: m.id, version: m.version, hostApi: m.hostApi, entry: m.entry,
    ...(m.native === undefined ? {} : { native: m.native }) }
}
