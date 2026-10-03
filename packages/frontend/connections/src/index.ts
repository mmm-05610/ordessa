// T027 — @ordessa/connections platform implementation (contract C6 §3/§5).
// Protocol-neutral: registration, kind-identity opens, per-scope handles,
// cancellation, late-resolve cleanup and close settlement. Imports stay behind
// the dependency wall: only @ordessa/extension-api types and relative paths.
import type { IDisposable, ResourceScope } from '@ordessa/extension-api'
import type {
  CloseFailureRecord,
  CloseOutcome,
  ConnectionEndpoint,
  ConnectionHandle,
  ConnectionInstanceSnapshot,
  ConnectionKind,
  ConnectionOpenOptions,
  ConnectionState,
  Connections,
  ConnectionsSettlementReport,
  ConnectionsSnapshot,
  Connector,
  LateOpenClosure,
  RegisteredConnectorSnapshot,
  ScopedConnectorRegistration,
} from '../api/connections'

/** One connector bound to its registrant scope; unmounting the scope removes it (§5.2). */
interface Registration {
  readonly connector: Connector<unknown>
  readonly owner: ResourceScope
  readonly live: Set<InstanceRecord>
  removed: boolean
}

/** Platform record for one open attempt / one connection instance. Never pooled. */
interface InstanceRecord {
  readonly instanceId: string
  readonly connectorId: string
  readonly registration: Registration
  readonly listeners: Set<() => void>
  state: ConnectionState
  error?: string
  endpoint?: ConnectionEndpoint<unknown>
  pendingClose?: Promise<CloseOutcome>
  /** True once the open became undeliverable (caller/registrant unmount, abort, connector failure). */
  invalidated: boolean
  invalidReason?: string
  controller: AbortController
  /** Rejects the in-flight open promise when the open is invalidated (§5.2/§5.3). */
  failOpen: (error: Error) => void
}

/** One-line neutral error summary for snapshots/reports; never payloads or credentials. */
function summarize(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error)
  return message.replace(/\s+/g, ' ').trim().slice(0, 500) || 'Unknown error'
}

/** Binds an idempotent disposal action to a caller/registrant-owned scope. */
function addDisposer(scope: ResourceScope, action: () => void): IDisposable {
  let disposed = false
  return scope.add({
    get isDisposed() { return disposed },
    dispose() { if (disposed) return; disposed = true; action() },
  })
}

/**
 * Fixed capability entry (contract §3). The service lifetime is the extension
 * scope: disposing it removes every registration and releases live instances;
 * the platform itself never owns backend executions (§5.2).
 */
export function createConnections(lifetime: ResourceScope): Connections {
  const registrations = new Map<string, Registration>()
  const records = new Map<string, InstanceRecord>()
  const listeners = new Set<() => void>()
  const pendingSettlements = new Set<Promise<void>>()
  const lateOpenClosures: LateOpenClosure[] = []
  const closeFailures: CloseFailureRecord[] = []
  let instanceSeq = 0
  let serviceClosed = false

  function publish(record?: InstanceRecord): void {
    for (const listener of [...listeners]) listener()
    if (record) for (const listener of [...record.listeners]) listener()
  }

  function track(cleanup: Promise<unknown>): void {
    let entry: Promise<void>
    entry = Promise.resolve(cleanup).then(() => { pendingSettlements.delete(entry) })
    pendingSettlements.add(entry)
  }

  function snapshotOf(record: InstanceRecord): ConnectionInstanceSnapshot {
    const snapshot: { instanceId: string; connectorId: string; state: ConnectionState; error?: string } = {
      instanceId: record.instanceId, connectorId: record.connectorId, state: record.state,
    }
    if (record.error !== undefined) snapshot.error = record.error
    return Object.freeze(snapshot)
  }

  // -------------------------------------------------------------------------
  // §5.4/§5.5 — close ownership: coalescing, honest failure, no auto retry.
  // -------------------------------------------------------------------------

  /**
   * `fromScopeCleanup` marks releases started by a synchronous scope dispose or
   * registrant unmount: their failures land in the settlement report because no
   * caller is waiting for them (§5.5). An explicit handle.close is reported to
   * its awaiter directly and never auto-retried.
   */
  function beginClose(record: InstanceRecord, fromScopeCleanup: boolean): Promise<CloseOutcome> {
    if (record.state === 'closed') return Promise.resolve({ status: 'closed' })
    if (record.pendingClose) return record.pendingClose
    if (record.state === 'close_failed') {
      // Never an automatic loop: cleanup paths join the previous failure;
      // only an explicit close() starts another closeLocal (§5.4).
      if (fromScopeCleanup) return Promise.resolve({ status: 'close_failed', error: record.error ?? 'Local release failed' })
    }
    if (!record.endpoint) return Promise.resolve({ status: 'close_failed', error: `No connection endpoint for ${record.connectorId}` })
    record.state = 'closing'
    record.error = undefined
    publish(record)
    const outcome: Promise<CloseOutcome> = (async (): Promise<CloseOutcome> => {
      try {
        await record.endpoint!.closeLocal()
        record.state = 'closed'
        record.pendingClose = undefined
        records.delete(record.instanceId)
        record.registration.live.delete(record)
        publish(record)
        return { status: 'closed' }
      } catch (error) {
        record.state = 'close_failed'
        record.error = summarize(error)
        record.pendingClose = undefined
        // The record stays visible for host diagnosis (§5.6) but leaves the
        // registration's live set so scope teardown never re-calls closeLocal.
        record.registration.live.delete(record)
        // §5.5 records every failed local release, whoever started it: an
        // explicit close reports to its awaiter AND remains in the cumulative
        // report, because a rejected closeLocal is never swallowed.
        closeFailures.push({ connectorId: record.connectorId, instanceId: record.instanceId, error: record.error })
        publish(record)
        return { status: 'close_failed', error: record.error }
      }
    })()
    record.pendingClose = outcome
    track(outcome)
    return outcome
  }

  // -------------------------------------------------------------------------
  // §5.2/§5.3 — invalidation of not-yet-delivered opens and late cleanup.
  // -------------------------------------------------------------------------

  function invalidateOpening(record: InstanceRecord, reason: string): void {
    if (record.invalidated || record.state !== 'opening') return
    record.invalidated = true
    record.invalidReason = reason
    try { record.controller.abort() } catch { /* signal already aborted */ }
    record.registration.live.delete(record)
    records.delete(record.instanceId)
    record.failOpen(new Error(reason))
    publish(record)
  }

  /** A late/aborted open that still resolved: release exactly once, never surface (§5.3). */
  async function closeLateEndpoint(record: InstanceRecord, endpoint: ConnectionEndpoint<unknown>): Promise<void> {
    try {
      await endpoint.closeLocal()
      lateOpenClosures.push({ connectorId: record.connectorId, instanceId: record.instanceId, closed: true })
    } catch (error) {
      lateOpenClosures.push({ connectorId: record.connectorId, instanceId: record.instanceId, closed: false, error: summarize(error) })
    }
  }

  function releaseOnCallerScopeGone(record: InstanceRecord): void {
    if (record.state === 'opening') invalidateOpening(record, `Caller scope closed during open of connector ${record.connectorId}`)
    else if (record.state === 'connected' || record.state === 'closing') {
      // §5.2: the platform-owned signal is aborted by the caller scope closing,
      // whether or not the open had landed.
      record.controller.abort()
      void beginClose(record, true)
    }
    // closed / close_failed: nothing more a scope teardown may start (§5.4).
  }

  function releaseOnRegistrantGone(record: InstanceRecord): void {
    if (record.state === 'opening') invalidateOpening(record, `Registrant scope for connector ${record.connectorId} unmounted during open`)
    else if (record.state === 'connected' || record.state === 'closing') {
      record.controller.abort()
      void beginClose(record, true)
    }
  }

  // -------------------------------------------------------------------------
  // §3 surface.
  // -------------------------------------------------------------------------

  function removeRegistration(registration: Registration): void {
    if (registration.removed) return
    registration.removed = true
    if (registrations.get(registration.connector.id) === registration) registrations.delete(registration.connector.id)
    for (const record of [...registration.live]) releaseOnRegistrantGone(record)
    publish()
  }

  function forScope(owner: ResourceScope): ScopedConnectorRegistration {
    return {
      add<T>(connector: Connector<T>): IDisposable {
        if (serviceClosed) throw new Error('Connections service is closed')
        if (owner.isDisposed) throw new Error(`Owner scope is closed; cannot register connector ${connector.id}`)
        if (registrations.has(connector.id)) throw new Error(`Duplicate connector id: ${connector.id}`)
        const registration: Registration = { connector: connector as Connector<unknown>, owner, live: new Set(), removed: false }
        registrations.set(connector.id, registration)
        const link = addDisposer(owner, () => removeRegistration(registration))
        publish()
        return link
      },
    }
  }

  async function open<T>(
    scope: ResourceScope,
    id: string,
    kind: ConnectionKind<T>,
    options?: ConnectionOpenOptions,
  ): Promise<ConnectionHandle<T>> {
    // ALL gates before connector.open is ever reached (CN-02, §5.1).
    if (serviceClosed) throw new Error('Connections service is closed')
    if (scope.isDisposed) throw new Error(`Caller scope is closed; cannot open connector ${id}`)
    const registration = registrations.get(id)
    if (!registration || registration.removed) throw new Error(`No connector registered for id: ${id}`)
    if (registration.owner.isDisposed) {
      removeRegistration(registration)
      throw new Error(`Registrant scope for connector ${id} is closed`)
    }
    // Identity is the registered kind object compared with ===, never names (§3).
    if ((registration.connector.kind as unknown) !== (kind as unknown)) {
      throw new Error(`Connection kind mismatch for connector ${id}`)
    }
    if (options?.signal?.aborted) throw new Error(`Open of connector ${id} was aborted before it started`)

    const record: InstanceRecord = {
      instanceId: `${id}#${(instanceSeq += 1)}`,
      connectorId: id,
      registration,
      listeners: new Set(),
      state: 'opening',
      invalidated: false,
      controller: new AbortController(),
      failOpen: () => { /* replaced by the guard below */ },
    }
    const guard = new Promise<never>((_, reject) => { record.failOpen = reject })
    addDisposer(scope, () => releaseOnCallerScopeGone(record))
    records.set(record.instanceId, record)
    registration.live.add(record)
    publish(record)

    // Platform-owned signal: aborts on caller abort, caller scope close or registrant unmount.
    const external = options?.signal
    const onExternalAbort = () => invalidateOpening(record, `Open of connector ${id} aborted by caller signal`)
    if (external) external.addEventListener('abort', onExternalAbort, { once: true })

    const opened = registration.connector.open(record.controller.signal)
    let endpoint: ConnectionEndpoint<unknown>
    try {
      endpoint = await Promise.race([opened, guard])
    } catch (error) {
      if (external) external.removeEventListener('abort', onExternalAbort)
      if (!record.invalidated) {
        // The connector itself failed: there is no endpoint to release.
        record.invalidated = true
        record.invalidReason = error instanceof Error ? error.message : String(error)
        try { record.controller.abort() } catch { /* already aborted */ }
        record.registration.live.delete(record)
        records.delete(record.instanceId)
        publish(record)
      }
      // A resolve that arrives after cancellation must still be cleaned up once (§5.3).
      track(opened.then(
        late => closeLateEndpoint(record, late),
        () => { /* connector rejection already delivered above */ },
      ))
      throw error instanceof Error ? error : new Error(String(error))
    }
    if (external) external.removeEventListener('abort', onExternalAbort)
    if (record.invalidated) {
      // Invalidation and the connector resolve raced in the same turn: the late
      // endpoint never enters the usable view and is closed exactly once (§5.3).
      track(closeLateEndpoint(record, endpoint))
      throw new Error(record.invalidReason ?? `Open of connector ${id} was invalidated before delivery`)
    }
    record.endpoint = endpoint
    record.state = 'connected'
    publish(record)

    const handle: ConnectionHandle<T> = {
      instanceId: record.instanceId,
      connectorId: record.connectorId,
      value: endpoint.value as T,
      getSnapshot: () => snapshotOf(record),
      subscribe: listener => { record.listeners.add(listener); return () => { record.listeners.delete(listener) } },
      close: () => beginClose(record, false),
    }
    return handle
  }

  function getSnapshot(): ConnectionsSnapshot {
    const connectors: readonly RegisteredConnectorSnapshot[] = Object.freeze(
      [...registrations.values()].map(registration => Object.freeze({
        id: registration.connector.id,
        title: registration.connector.title,
        kindName: registration.connector.kind.displayName,
      })),
    )
    const instances: readonly ConnectionInstanceSnapshot[] = Object.freeze([...records.values()].map(snapshotOf))
    return Object.freeze({ connectors, instances })
  }

  function subscribe(listener: () => void): () => void {
    listeners.add(listener)
    return () => { listeners.delete(listener) }
  }

  async function whenSettled(): Promise<ConnectionsSettlementReport> {
    while (pendingSettlements.size > 0) await Promise.all([...pendingSettlements])
    return Object.freeze({
      lateOpenClosures: Object.freeze(lateOpenClosures.map(entry => Object.freeze({ ...entry }))),
      closeFailures: Object.freeze(closeFailures.map(entry => Object.freeze({ ...entry }))),
    })
  }

  addDisposer(lifetime, () => {
    serviceClosed = true
    for (const registration of [...registrations.values()]) removeRegistration(registration)
    for (const record of [...records.values()]) {
      if (record.state === 'opening') invalidateOpening(record, 'Connections service closed during open')
    }
    publish()
  })

  return { forScope, open, getSnapshot, subscribe, whenSettled }
}
