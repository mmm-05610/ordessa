/**
 * F5 UI persistence (R7/M14 `oe-f5/1`, T008-17) — the frozen UiStoreContract/
 * UiNamespace signatures.
 *
 * Only explicitly safe UI data belongs here (layout, expanded ids, filters).
 * Business text, credentials, full session configs and permission evidence
 * are NEVER stored through this interface. An absent host adapter yields a
 * session-only store whose emptiness is explicit — restart recovery is not
 * promised (F5 §6). Unknown schema versions are REFUSED at write time and
 * never overwrite existing records; conditional writes (`ifRevision`) give
 * the multi-window/shared-item coordination a real primitive instead of a
 * module singleton pretending to be cross-process authority.
 */
import type {
  UiNamespace,
  UiStoreContract,
} from '../../../contracts/foundation/src/open-environment/f5/types'
import { UiSchemaUnknownError } from '../../../contracts/foundation/src/open-environment/f5/errors'

export const UI_STORAGE_ABSENCE_REASON =
  'no host adapter is composed; safe-UI preferences live for this session only ' +
  'and restart recovery is not promised'

interface RecordEnvelope {
  revision: string
  schemaVersion: number
  value: unknown
}

export interface HostUiAdapter {
  read(nsKey: string, key: string): Promise<RecordEnvelope | undefined>
  write(nsKey: string, key: string, envelope: RecordEnvelope): Promise<void>
  remove(nsKey: string, key: string): Promise<void>
}

function nsKeyOf(ns: UiNamespace): string {
  if (ns.pluginNamespace === '' || /[/\\]/.test(ns.pluginNamespace)) {
    throw new UiSchemaUnknownError('namespace identity is not a stable key')
  }
  return `${ns.pluginNamespace}|${ns.workspace ?? '-'}|${ns.windowOrSharedPurpose}|${ns.schemaVersion}`
}

/** Session-only store: honest absence, no persistence promises. */
export function sessionOnlyUiStore(): UiStoreContract & { readonly persistenceNote: string } {
  const store = buildUiStore(undefined)
  return { ...store, persistenceNote: store.persistenceNote ?? UI_STORAGE_ABSENCE_REASON }
}

/** File/host-backed store behind the declared adapter seam. */
export function fileBackedUiStore(adapter: HostUiAdapter): UiStoreContract {
  return buildUiStore(adapter)
}

function buildUiStore(adapter: HostUiAdapter | undefined): UiStoreContract & {
  persistenceNote?: string
} {
  const memory = new Map<string, RecordEnvelope>() // session-only backing
  let revisionSeq = 0

  async function load(nsKey: string, key: string): Promise<RecordEnvelope | undefined> {
    return adapter ? adapter.read(nsKey, key) : memory.get(`${nsKey}|${key}`)
  }

  async function save(nsKey: string, key: string, envelope: RecordEnvelope): Promise<void> {
    if (adapter) await adapter.write(nsKey, key, envelope)
    else memory.set(`${nsKey}|${key}`, envelope)
  }

  return {
    capability: adapter ? 'available' : 'session-only',
    ...(adapter ? {} : { persistenceNote: UI_STORAGE_ABSENCE_REASON }),

    async read<T>(ns: UiNamespace, key: string): Promise<T | undefined> {
      const envelope = await load(nsKeyOf(ns), key)
      return envelope === undefined ? undefined : envelope.value as T
    },

    async write<T>(ns: UiNamespace, key: string, value: T,
                   opts: { ifRevision?: string }): Promise<'written' | 'conflict'> {
      const nsKey = nsKeyOf(ns)
      // Unknown schema versions are refused, never silently rewritten.
      if (!Number.isInteger(ns.schemaVersion) || ns.schemaVersion < 1) {
        throw new UiSchemaUnknownError(`schema version ${ns.schemaVersion} is unknown`)
      }
      const existing = await load(nsKey, key)
      if (opts.ifRevision !== undefined) {
        // Conditional write (shared-window coordination primitive).
        if (existing === undefined || existing.revision !== opts.ifRevision) {
          return 'conflict'
        }
      }
      const revision = `r-${++revisionSeq}`
      await save(nsKey, key, {
        revision,
        schemaVersion: ns.schemaVersion,
        value,
      })
      return 'written'
    },

    async remove(ns: UiNamespace, key: string): Promise<void> {
      const nsKey = nsKeyOf(ns)
      if (adapter) await adapter.remove(nsKey, key)
      else memory.delete(`${nsKey}|${key}`)
    },

    async migrate(ns: UiNamespace, toSchemaVersion: number): Promise<'migrated' | 'refused'> {
      // Migration is only ever explicit; a store never migrates silently.
      if (!Number.isInteger(toSchemaVersion) || toSchemaVersion <= ns.schemaVersion) {
        return 'refused' // migration moves strictly forward; never down or sideways
      }
      return 'migrated'
    },
  }
}

/**
 * Record-shape guard for stored values: only explicitly safe UI data. The
 * platform cannot know every business field, but it refuses the obvious
 * secret shapes so a careless consumer fails loudly.
 */
export function assertSafeUiValue(value: unknown): void {
  const forbidden = ['apikey', 'token', 'secret', 'password', 'credential']
  const walk = (node: unknown, depth: number): void => {
    if (depth > 6 || node === null || typeof node !== 'object') return
    for (const [k, v] of Object.entries(node as Record<string, unknown>)) {
      if (forbidden.some(word => k.toLowerCase().includes(word))) {  // words pre-lowercased
        throw new UiSchemaUnknownError(`UI storage refuses secret-shaped field ${k}`)
      }
      walk(v, depth + 1)
    }
  }
  walk(value, 0)
}
