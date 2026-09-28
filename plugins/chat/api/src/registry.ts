// Registration factory and the in-memory ChatContributionsService
// implementation. One runtime direction only: this module imports types from
// ./contract, and ./contract re-exports the runtime here.
//
// Rejection rules follow contracts.md §4/§5 and input-contracts §1: duplicate
// contribution ids, duplicate content kinds and duplicate source ids are
// refused instead of last-write-wins; ordering is (order, id) so it never
// depends on loading timing; a scope closing revokes exactly that scope's
// registrations. There is deliberately no module-level shared state — every
// createChatContributions() call is an independent instance (the upstream
// ToolLayout module Map is the counterexample this codebase must not copy).
import { DisposableDelegate, type IDisposable } from '@lumino/disposable'
import type { ResourceScope } from '@ordessa/extension-api'
import type {
  ChatComponentKey, ChatContributionContext, ChatContributionRegistration, ChatContributionView, ChatContributionsService,
  ChatInputEntry, ChatInputQuery, ChatInputSource, ChatInputSourceView, ChatProjection, ChatSlot, ObservableValues,
} from './contract'

/** Observable view whose `getSnapshot()` identity is stable until the next
 * invalidation — the contract React's useSyncExternalStore requires. A view
 * with no subscribers is idle: it stops receiving invalidations and, when an
 * `onIdle` hook is given, the owner may reclaim it (no unbounded view maps). */
class Values<T> implements ObservableValues<T> {
  private listeners = new Set<() => void>()
  private cached: readonly T[] | undefined
  constructor(private readonly compute: () => readonly T[], private readonly onIdle?: (view: Values<T>) => void) {}
  getSnapshot = (): readonly T[] => (this.cached ??= this.compute())
  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener)
    return () => {
      this.listeners.delete(listener)
      if (this.listeners.size === 0 && this.onIdle) this.onIdle(this)
    }
  }
  invalidate = () => {
    if (this.cached === undefined) return
    this.cached = undefined
    for (const listener of [...this.listeners]) listener()
  }
}

interface ContributionDescriptor<P = unknown> {
  readonly id: string
  readonly slot: ChatSlot
  readonly order: number
  readonly key: ChatComponentKey<P>
  readonly project?: ChatProjection<P>
  readonly contentKind?: string
  readonly decode?: (payload: unknown) => P | null
}

const descriptorKey = Symbol('ordessa.chat.contribution.descriptor')

/** The single factory of {@link ChatContributionRegistration}. The generic
 * keeps `key`, `project` and `decode` prop-paired; nothing here accepts an
 * owner string — ownership is the scope the registration is added under. */
export function chatContribution<P>(descriptor: {
  readonly id: string
  readonly slot: ChatSlot
  readonly order: number
  readonly key: ChatComponentKey<P>
  readonly project?: ChatProjection<P>
  /** `content.renderers` only: stable namespaced content kind, one-to-one with
   * the key; duplicate kinds are rejected, never priority-chained (contracts.md §5). */
  readonly contentKind?: string
  /** `content.renderers` only: pure decoder; a thrown error or `null` renders
   * the readable fallback, never executes the payload. */
  readonly decode?: (payload: unknown) => P | null
}): ChatContributionRegistration {
  if (typeof descriptor.id !== 'string' || descriptor.id.length === 0 || !descriptor.id.includes('.'))
    throw new RangeError(`Chat contribution id must be a non-empty namespaced id: ${String(descriptor.id)}`)
  if (!Number.isInteger(descriptor.order)) throw new RangeError('Chat contribution order must be an integer')
  if (!descriptor.key || typeof descriptor.key.id !== 'string') throw new TypeError('Chat contribution requires a component key')
  if (descriptor.slot === 'content.renderers') {
    if (!descriptor.contentKind) throw new TypeError('content.renderers contribution requires a contentKind')
    if (!descriptor.decode) throw new TypeError('content.renderers contribution requires a pure decode function')
  } else if (descriptor.contentKind !== undefined) {
    throw new TypeError(`Slot ${descriptor.slot} does not accept contentKind`)
  }
  // Keep the platform key and callbacks by identity, but sever caller-owned
  // descriptor fields before registration and later scope revocation use them.
  const snapshot = Object.freeze({ ...descriptor })
  return Object.freeze({ [descriptorKey]: snapshot }) as unknown as ChatContributionRegistration
}

const unwrap = (registration: ChatContributionRegistration): ContributionDescriptor => {
  const record = registration as { readonly [descriptorKey]?: ContributionDescriptor }
  if (!record || !record[descriptorKey]) throw new TypeError('Not a chatContribution() record')
  return record[descriptorKey]
}

const byOrderThenId = <T extends { order: number; id: string }>(items: readonly T[]): T[] =>
  [...items].sort((a, b) => a.order - b.order || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0))

const UNDECLARED_GROUP_ORDER = Number.MAX_SAFE_INTEGER

/** Merged entry ordering: (group.order, group.id, entry.order, entry.id). An
 * entry whose group its source never declared sorts after declared groups and
 * stays addressable by its raw group id. */
export const mergeInputEntries = (source: ChatInputSource, entries: readonly ChatInputEntry[]): ChatInputEntry[] => {
  const groupOrder = new Map(source.groups.map(group => [group.id, group.order] as const))
  const groupIds = new Set(source.groups.map(group => group.id))
  const groupKeyOf = (entry: ChatInputEntry): { order: number; id: string } =>
    groupIds.has(entry.groupId) ? { order: groupOrder.get(entry.groupId)!, id: entry.groupId } : { order: UNDECLARED_GROUP_ORDER, id: entry.groupId }
  return [...entries].sort((a, b) => {
    const ga = groupKeyOf(a), gb = groupKeyOf(b)
    if (ga.order !== gb.order) return ga.order - gb.order
    if (ga.id !== gb.id) return ga.id < gb.id ? -1 : 1
    return a.order - b.order || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0)
  })
}

interface SourceRecord {
  readonly source: ChatInputSource
  entries: ChatInputEntry[]
  entriesKey: string | null
  queryVersion: number
  active: boolean
}

interface QueryRecord {
  readonly sourceRecord: SourceRecord
  entries: ChatInputEntry[]
  state: { status: 'ready' | 'loading' | 'error'; error?: string }
}

/** Only an identical location, surface and search may reuse prior entries.
 * In particular a pending session query must never display a draft action. */
function queryKey(request: ChatInputQuery): string {
  const location = request.location
  return JSON.stringify([
    location.kind, location.kind === 'draft' ? location.draftId : location.sessionId,
    location.connectionId, location.serverInstanceId, location.projectId,
    location.harnessId, location.contextRevision, request.surface, request.query,
  ])
}

/** Per-source status updates stay isolated: one source failing its query never
 * touches another source's entries. An aborted query is a UI cancellation, not
 * a business one: the previous entries stay and the source reports ready. */
function runQuery(viewRecord: QueryRecord, request: ChatInputQuery, notify: () => void): void {
  if (request.signal.aborted) return // already-cancelled query: previous entries and ready state stand
  const record = viewRecord.sourceRecord
  const version = ++record.queryVersion
  const key = queryKey(request)
  const onAbort = () => {
    if (!record.active) return
    viewRecord.state = { status: 'ready' }
    notify()
  }
  request.signal.addEventListener('abort', onAbort, { once: true })
  viewRecord.state = { status: 'loading' }
  notify()
  void (async () => {
    try {
      const entries = await record.source.query(request)
      if (request.signal.aborted || !record.active) return
      viewRecord.entries = mergeInputEntries(record.source, entries)
      viewRecord.state = { status: 'ready' }
      if (record.queryVersion === version) {
        record.entries = viewRecord.entries
        record.entriesKey = key
      }
    } catch (error) {
      if (request.signal.aborted || !record.active) return
      viewRecord.entries = []
      viewRecord.state = { status: 'error', error: error instanceof Error ? error.message : String(error) }
      if (record.queryVersion === version) {
        record.entries = []
        record.entriesKey = key
      }
    } finally {
      request.signal.removeEventListener('abort', onAbort)
    }
    notify()
  })()
}

const viewOfContribution = (descriptor: ContributionDescriptor): ChatContributionView => ({
  id: descriptor.id,
  slot: descriptor.slot,
  order: descriptor.order,
  keyId: descriptor.key.id,
  keyMajor: descriptor.key.major,
  ...(descriptor.contentKind !== undefined ? { contentKind: descriptor.contentKind } : {}),
  ...(descriptor.project
    ? { project: descriptor.project as unknown as (context: ChatContributionContext) => { readonly hidden: true } | { readonly hidden: false; readonly props: unknown } }
    : {}),
  ...(descriptor.decode ? { decode: descriptor.decode as unknown as (payload: unknown) => unknown | null } : {}),
})

export function createChatContributions(): ChatContributionsService {
  const contributions = new Map<string, { readonly descriptor: ContributionDescriptor; readonly scope: ResourceScope }>()
  const sources = new Map<string, { readonly record: SourceRecord; readonly scope: ResourceScope }>()
  const slotViews = new Map<ChatSlot, Values<ChatContributionView>>()
  const queryViews = new Set<Values<ChatInputSourceView>>()

  const publishContributions = () => { for (const view of slotViews.values()) view.invalidate() }
  const publishSources = () => { for (const view of queryViews) view.invalidate() }

  return {
    forScope(scope: ResourceScope) {
      if (scope.isDisposed) throw new Error('Chat contribution scope is closed')
      return {
        addContribution(registration: ChatContributionRegistration): IDisposable {
          const descriptor = unwrap(registration)
          if (contributions.has(descriptor.id)) throw new Error(`Duplicate chat contribution: ${descriptor.id}`)
          if (descriptor.slot === 'content.renderers' && descriptor.contentKind) {
            for (const existing of contributions.values())
              if (existing.descriptor.slot === 'content.renderers' && existing.descriptor.contentKind === descriptor.contentKind)
                throw new Error(`Duplicate chat content kind: ${descriptor.contentKind}`)
          }
          contributions.set(descriptor.id, { descriptor, scope })
          publishContributions()
          return registerScoped(scope, () => {
            if (contributions.get(descriptor.id)?.descriptor === descriptor) {
              contributions.delete(descriptor.id)
              publishContributions()
            }
          })
        },
        addInputSource(source: ChatInputSource): IDisposable {
          if (sources.has(source.id)) throw new Error(`Duplicate chat input source: ${source.id}`)
          const sourceId = source.id
          const sourceQuery = source.query
          const sourceSnapshot: ChatInputSource = Object.freeze({
            id: source.id,
            title: source.title,
            groups: Object.freeze(source.groups.map(group => Object.freeze({ ...group }))),
            // A class source may use #private state. Keep its original receiver,
            // while a later replacement of source.query cannot change the method.
            query: (request: ChatInputQuery) => sourceQuery.call(source, request),
          })
          const record: SourceRecord = { source: sourceSnapshot, entries: [], entriesKey: null,
            queryVersion: 0, active: true }
          sources.set(sourceId, { record, scope })
          publishSources()
          return registerScoped(scope, () => {
            if (sources.get(sourceId)?.record === record) {
              record.active = false
              sources.delete(sourceId)
              publishSources()
            }
          })
        },
      }
    },
    contributionsBySlot(slot: ChatSlot): ObservableValues<ChatContributionView> {
      let view = slotViews.get(slot)
      if (!view) {
        view = new Values(() => byOrderThenId([...contributions.values()]
          .map(({ descriptor }) => descriptor)
          .filter(descriptor => descriptor.slot === slot)
          .map(viewOfContribution)))
        slotViews.set(slot, view)
      }
      return view
    },
    queryInputSources(request: ChatInputQuery): ObservableValues<ChatInputSourceView> {
      // Sources registered at query time define this view; a source added
      // later appears in the next query (the panel re-queries on open).
      const key = queryKey(request)
      const registered: QueryRecord[] = [...sources.values()].map(({ record }) => ({
        sourceRecord: record, entries: record.entriesKey === key ? [...record.entries] : [],
        state: { status: 'ready' },
      }))
      const view = new Values<ChatInputSourceView>(() => registered.filter(item => item.sourceRecord.active).map(item => ({
        source: item.sourceRecord.source, state: { ...item.state }, entries: [...item.entries],
      })), idle => { queryViews.delete(idle) })
      queryViews.add(view)
      for (const item of registered) runQuery(item, request, () => view.invalidate())
      return view
    },
  }
}

function registerScoped(scope: ResourceScope, revoke: () => void): IDisposable {
  const disposable = new DisposableDelegate(revoke)
  scope.add(disposable) // a closed scope disposes the item (and throws) here — nothing is registered half-way
  return disposable
}
