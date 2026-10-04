/**
 * F5 UI persistence (R7/M14 `oe-f5/1`, T008-17) — the frozen UiStoreContract/
 * UiNamespace signatures.
 *
 * Only explicitly safe UI data belongs here (layout, expanded ids, filters).
 * Business text, credentials, full session configs and permission evidence
 * are NEVER stored through this interface. An absent host adapter yields a
 * session-only store whose emptiness is explicit — restart recovery is not
 * promised (F5 §6). Unknown schema versions are refused at write time and
 * never overwrite existing records. Conditional writes require an atomic
 * adapter primitive; this module never simulates cross-client CAS with a
 * read followed by a write.
 */
import type {
  UiNamespace,
  VersionedUiStoreContract,
} from '../../../contracts/foundation/src/open-environment/f5/types'
import { UiSchemaUnknownError } from '../../../contracts/foundation/src/open-environment/f5/errors'

export const UI_STORAGE_ABSENCE_REASON =
  'no host adapter is composed; safe-UI preferences live for this session only ' +
  'and restart recovery is not promised'

export interface RecordEnvelope {
  revision: string
  schemaVersion: number
  value: unknown
}

export type UiEnvelopeInput = Omit<RecordEnvelope, 'revision'>

export type CasResult =
  | { status: 'written'; revision: string }
  | { status: 'conflict' }

/**
 * Internal host seam. The adapter owns revision allocation and performs the
 * compare-and-swap atomically. `expectedRevision === undefined` means an
 * unconditional write, matching UiStoreContract's existing write options.
 */
export interface HostUiAdapter {
  read(nsKey: string, key: string): Promise<RecordEnvelope | undefined>
  /** True only when compareAndSwap atomically recognizes expectedRevision=null as absent. */
  readonly supportsAbsentCompareAndSwap?: true
  compareAndSwap?(
    nsKey: string,
    key: string,
    expectedRevision: string | null | undefined,
    envelope: UiEnvelopeInput,
  ): Promise<CasResult>
  /** Optional legacy method is never used to emulate conditional writes. */
  write?(nsKey: string, key: string, envelope: RecordEnvelope): Promise<void>
  remove(nsKey: string, key: string): Promise<void>
  /** Host adapters may migrate only when they can atomically transform data. */
  migrateNamespace?(
    fromNsKey: string,
    toNsKey: string,
    fromSchemaVersion: number,
    toSchemaVersion: number,
  ): Promise<boolean>
}

let sessionRevisionSeq = 0

function nextSessionRevision(): string {
  sessionRevisionSeq += 1
  return `session-${Date.now().toString(36)}-${sessionRevisionSeq.toString(36)}`
}

function nsKeyOf(ns: UiNamespace): string {
  if (ns.pluginNamespace === '' || /[/\\]/.test(ns.pluginNamespace)) {
    throw new UiSchemaUnknownError('namespace identity is not a stable key')
  }
  return `${ns.pluginNamespace}|${ns.workspace ?? '-'}|${ns.windowOrSharedPurpose}|${ns.schemaVersion}`
}

function storageKey(nsKey: string, key: string): string {
  return `${nsKey}|${key}`
}

/** Return the current opaque revision through the host adapter boundary. */
export async function readUiRevision(
  adapter: HostUiAdapter,
  ns: UiNamespace,
  key: string,
): Promise<string | undefined> {
  return (await adapter.read(nsKeyOf(ns), key))?.revision
}

/** Session-only store: honest absence, no persistence promises. */
export function sessionOnlyUiStore(): VersionedUiStoreContract & { readonly persistenceNote: string } {
  const store = buildUiStore(undefined)
  return { ...store, persistenceNote: store.persistenceNote ?? UI_STORAGE_ABSENCE_REASON }
}

/** Host-backed store behind the declared adapter seam. */
export function fileBackedUiStore(
  adapter: HostUiAdapter,
  options: { supportedSchemaVersions?: readonly number[] } = {},
): VersionedUiStoreContract {
  return buildUiStore(adapter, options.supportedSchemaVersions)
}

function buildUiStore(
  adapter: HostUiAdapter | undefined,
  configuredSchemaVersions: readonly number[] = [1],
): VersionedUiStoreContract & { persistenceNote?: string } {
  const memory = new Map<string, RecordEnvelope>()
  const supportedSchemaVersions = new Set(configuredSchemaVersions)
  const hasAtomicWrite = adapter === undefined || typeof adapter.compareAndSwap === 'function'
  const hasAbsentCompareAndSwap = adapter === undefined
    || (adapter.supportsAbsentCompareAndSwap === true
      && typeof adapter.compareAndSwap === 'function')

  for (const version of supportedSchemaVersions) {
    if (!Number.isInteger(version) || version < 1) {
      throw new UiSchemaUnknownError(`schema version ${version} is unknown`)
    }
  }

  async function load(nsKey: string, key: string): Promise<RecordEnvelope | undefined> {
    return adapter ? adapter.read(nsKey, key) : memory.get(storageKey(nsKey, key))
  }

  async function save(
    nsKey: string,
    key: string,
    envelope: UiEnvelopeInput,
    expectedRevision: string | null | undefined,
  ): Promise<'written' | 'conflict'> {
    if (adapter) {
      if (!adapter.compareAndSwap) {
        throw new UiSchemaUnknownError('host adapter lacks atomic UI storage writes')
      }
      if (expectedRevision === null && adapter.supportsAbsentCompareAndSwap !== true) {
        throw new UiSchemaUnknownError('host adapter lacks atomic absent-only UI storage writes')
      }
      const result = await adapter.compareAndSwap(nsKey, key, expectedRevision, envelope)
      return result.status
    }

    const id = storageKey(nsKey, key)
    const existing = memory.get(id)
    if ((expectedRevision === null && existing !== undefined)
        || (typeof expectedRevision === 'string'
          && (existing === undefined || existing.revision !== expectedRevision))) {
      return 'conflict'
    }
    memory.set(id, {
      ...envelope,
      value: cloneSafeUiValue(envelope.value),
      revision: nextSessionRevision(),
    })
    return 'written'
  }

  function validateSchemaVersion(version: number): void {
    if (!Number.isInteger(version) || version < 1 || !supportedSchemaVersions.has(version)) {
      throw new UiSchemaUnknownError(`schema version ${version} is unknown`)
    }
  }

  return {
    capability: adapter === undefined ? 'session-only' : hasAtomicWrite ? 'available' : 'unavailable',
    versionedCapability: adapter === undefined
      ? 'session-only'
      : hasAbsentCompareAndSwap ? 'available' : 'unavailable',
    ...(adapter === undefined ? { persistenceNote: UI_STORAGE_ABSENCE_REASON } : {}),

    async read<T>(ns: UiNamespace, key: string): Promise<T | undefined> {
      const envelope = await load(nsKeyOf(ns), key)
      return envelope === undefined ? undefined : envelope.value as T
    },

    async readVersioned<T>(ns: UiNamespace, key: string): Promise<{
      value: T | undefined
      revision: string | null
    }> {
      validateSchemaVersion(ns.schemaVersion)
      const envelope = await load(nsKeyOf(ns), key)
      if (envelope === undefined) return { value: undefined, revision: null }
      if (typeof envelope.revision !== 'string' || envelope.revision.length === 0) {
        throw new UiSchemaUnknownError('stored UI revision is not a usable opaque version')
      }
      if (envelope.schemaVersion !== ns.schemaVersion) {
        throw new UiSchemaUnknownError('stored UI schema version does not match its namespace')
      }
      assertSafeUiValue(envelope.value)
      return {
        value: cloneSafeUiValue(envelope.value) as T,
        revision: envelope.revision,
      }
    },

    async write<T>(
      ns: UiNamespace,
      key: string,
      value: T,
      opts: { ifRevision?: string },
    ): Promise<'written' | 'conflict'> {
      validateSchemaVersion(ns.schemaVersion)
      assertSafeUiValue(value)
      const nsKey = nsKeyOf(ns)
      return save(nsKey, key, {
        schemaVersion: ns.schemaVersion,
        value,
      }, opts.ifRevision)
    },

    async writeVersioned<T>(
      ns: UiNamespace,
      key: string,
      value: T,
      expectedRevision: string | null,
    ): Promise<'written' | 'conflict'> {
      if (expectedRevision !== null && (typeof expectedRevision !== 'string' || expectedRevision.length === 0)) {
        throw new UiSchemaUnknownError('versioned UI writes require a captured revision or explicit null')
      }
      validateSchemaVersion(ns.schemaVersion)
      assertSafeUiValue(value)
      const nsKey = nsKeyOf(ns)
      return save(nsKey, key, {
        schemaVersion: ns.schemaVersion,
        value: cloneSafeUiValue(value),
      }, expectedRevision)
    },

    async remove(ns: UiNamespace, key: string): Promise<void> {
      const nsKey = nsKeyOf(ns)
      if (adapter) await adapter.remove(nsKey, key)
      else memory.delete(storageKey(nsKey, key))
    },

    async migrate(ns: UiNamespace, toSchemaVersion: number): Promise<'migrated' | 'refused'> {
      if (!Number.isInteger(toSchemaVersion) || toSchemaVersion <= ns.schemaVersion
          || !Number.isInteger(ns.schemaVersion) || ns.schemaVersion < 1
          || !supportedSchemaVersions.has(ns.schemaVersion)) {
        return 'refused'
      }

      const fromNsKey = nsKeyOf(ns)
      const targetNs = { ...ns, schemaVersion: toSchemaVersion }
      const toNsKey = nsKeyOf(targetNs)

      if (adapter) {
        // A read/write loop would lose atomicity and can advertise a migration
        // that only copied some records. Require one host-owned operation.
        if (!adapter.migrateNamespace
            || !await adapter.migrateNamespace(
              fromNsKey,
              toNsKey,
              ns.schemaVersion,
              toSchemaVersion,
            )) {
          return 'refused'
        }
        supportedSchemaVersions.add(toSchemaVersion)
        return 'migrated'
      }

      const fromPrefix = `${fromNsKey}|`
      const toPrefix = `${toNsKey}|`
      const source = [...memory.entries()].filter(([id]) => id.startsWith(fromPrefix))
      const targetKeys = new Set(source.map(([id]) => `${toPrefix}${id.slice(fromPrefix.length)}`))
      if ([...targetKeys].some(id => memory.has(id))) return 'refused'

      const migrated = source.map(([id, envelope]) => [
        `${toPrefix}${id.slice(fromPrefix.length)}`,
        {
          revision: nextSessionRevision(),
          schemaVersion: toSchemaVersion,
          value: envelope.value,
        },
      ] as const)
      for (const [id] of source) memory.delete(id)
      for (const [id, envelope] of migrated) memory.set(id, envelope)
      supportedSchemaVersions.add(toSchemaVersion)
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
  const visited = new WeakSet<object>()
  const walk = (node: unknown): void => {
    if (typeof node === 'function' || typeof node === 'symbol' || typeof node === 'bigint')
      throw new UiSchemaUnknownError('UI storage requires JSON-safe preference values')
    if (node === null || typeof node !== 'object') return
    if (visited.has(node)) throw new UiSchemaUnknownError('UI storage refuses cyclic or shared mutable values')
    visited.add(node)
    const prototype = Object.getPrototypeOf(node)
    if (!Array.isArray(node) && prototype !== Object.prototype && prototype !== null)
      throw new UiSchemaUnknownError('UI storage refuses unsupported preference objects')
    for (const key of Reflect.ownKeys(node)) {
      if (typeof key !== 'string') throw new UiSchemaUnknownError('UI storage refuses symbol keys')
      const descriptor = Object.getOwnPropertyDescriptor(node, key)!
      if (!('value' in descriptor)) throw new UiSchemaUnknownError('UI storage refuses accessors')
      if (forbidden.some(word => key.toLowerCase().includes(word)))
        throw new UiSchemaUnknownError(`UI storage refuses secret-shaped field ${key}`)
      walk(descriptor.value)
    }
    visited.delete(node)
  }
  walk(value)
}

/** Copy the validated JSON-safe value so callers never hold a storage alias. */
function cloneSafeUiValue<T>(value: T): T {
  if (value === null || typeof value !== 'object') return value
  if (Array.isArray(value)) {
    const copy: unknown[] = new Array(value.length)
    for (const key of Reflect.ownKeys(value)) {
      if (key === 'length') continue
      const descriptor = Object.getOwnPropertyDescriptor(value, key)!
      Object.defineProperty(copy, key, {
        value: cloneSafeUiValue(descriptor.value),
        enumerable: descriptor.enumerable,
        configurable: true,
        writable: true,
      })
    }
    return copy as T
  }
  const copy = Object.create(Object.getPrototypeOf(value)) as Record<string, unknown>
  for (const key of Reflect.ownKeys(value)) {
    const descriptor = Object.getOwnPropertyDescriptor(value, key)!
    Object.defineProperty(copy, key, {
      value: cloneSafeUiValue(descriptor.value),
      enumerable: descriptor.enumerable,
      configurable: true,
      writable: true,
    })
  }
  return copy as T
}
