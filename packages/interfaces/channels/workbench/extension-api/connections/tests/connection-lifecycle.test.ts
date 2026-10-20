// T009-02 — connection lifecycle pins: stable handle identity / instance
// generations, the settlement-report shape, and the honest local close
// vocabulary.
//
// DRIFT NOTE (order brief vs shipped types): the order text mentions a close
// record value `released` (and the counterexample wording `remote-stopped`).
// The public API in `api/connections.ts` has NO such member: `CloseOutcome` is
// exactly `{status:'closed'} | {status:'close_failed'; error}`, and
// `closeLocal` releases LOCAL ownership only (C6 §3/§5) — a local release must
// never be reported as a remote/backend outcome. This file pins the real enum
// values and the report shape instead of inventing `released` to satisfy the
// brief. (`released` is a lease state in docs/implementation/specifications/010-platform-core/data-model.md,
// not a connection close result.)
//
// Controlled in-memory fakes only: no Electron, no real transport, no Agent /
// Workbench / ACP / Server involvement.

import { describe, expect, it } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import {
  createConnectionKind,
  type CloseOutcome,
  type ConnectionEndpoint,
  type ConnectionKind,
  type Connections,
  type Connector,
} from '@ordessa/connections/api'
import { createConnections } from '../src/index'

interface FakeValue { label: string }

class FakeEndpoint implements ConnectionEndpoint<FakeValue> {
  readonly value: FakeValue
  closeLocalCalls = 0
  /** Swappable so tests can gate or reject the local release. */
  closeLocalResult: Promise<void> = Promise.resolve()

  constructor(label: string) { this.value = { label } }

  closeLocal(): Promise<void> {
    this.closeLocalCalls += 1
    return this.closeLocalResult
  }
}

class FakeConnector implements Connector<FakeValue> {
  readonly endpoints: FakeEndpoint[] = []
  openBehavior?: (signal: AbortSignal) => Promise<ConnectionEndpoint<FakeValue>>

  constructor(readonly id: string, readonly title: string, readonly kind: ConnectionKind<FakeValue>) {}

  open(signal: AbortSignal): Promise<ConnectionEndpoint<FakeValue>> {
    return this.openBehavior ? this.openBehavior(signal) : Promise.resolve(this.makeEndpoint())
  }

  makeEndpoint(): FakeEndpoint {
    const endpoint = new FakeEndpoint(`${this.id}#${this.endpoints.length}`)
    this.endpoints.push(endpoint)
    return endpoint
  }
}

function deferred<T = void>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

/** Let every queued microtask/timer continuation run. */
const flush = () => new Promise<void>(resolve => setTimeout(resolve, 0))

function newConnections(): { lifetime: OwnedResources; connections: Connections } {
  const lifetime = new OwnedResources()
  return { lifetime, connections: createConnections(lifetime) }
}

// ---------------------------------------------------------------------------
// §3/§5.1 — handle identity is stable; each open is its own generation.
// ---------------------------------------------------------------------------

describe('T009-02 §3/§5.1 — handle identity and instance generations', () => {
  it('one handle keeps its instanceId/connectorId/value across snapshots and state changes', async () => {
    const { lifetime, connections } = newConnections()
    const owner = new OwnedResources()
    const caller = new OwnedResources()
    const kind = createConnectionKind<FakeValue>('fake.widget')
    const connector = new FakeConnector('fake.identity', 'Identity', kind)
    connections.forScope(owner).add(connector)

    const handle = await connections.open(caller, 'fake.identity', kind)
    const value = handle.value
    const snapshot = handle.getSnapshot()
    // The neutral snapshot exposes identity and state only — no payload/token.
    expect(Object.keys(snapshot).sort()).toEqual(['connectorId', 'instanceId', 'state'])
    expect(Object.isFrozen(snapshot)).toBe(true)
    expect(handle.instanceId).toBe(snapshot.instanceId)
    expect(handle.connectorId).toBe('fake.identity')

    // A state transition must not re-identify the handle or swap its value.
    const gate = deferred()
    connector.endpoints[0]!.closeLocalResult = gate.promise
    const closing = handle.close()
    await flush()
    expect(handle.getSnapshot().state).toBe('closing')
    expect(handle.instanceId).toBe(snapshot.instanceId)
    expect(handle.connectorId).toBe('fake.identity')
    expect(handle.value).toBe(value)
    gate.resolve()
    await closing
    expect(handle.getSnapshot().state).toBe('closed')
    expect(handle.instanceId).toBe(snapshot.instanceId)
    expect(handle.value).toBe(value)

    caller.dispose()
    owner.dispose()
    lifetime.dispose()
  })

  it('every open is a distinct generation: ids are unique, never pooled or reused', async () => {
    // Counterexample sensitivity: a service that pools by connector id, or
    // reuses an instance counter after close, collapses these ids.
    const { lifetime, connections } = newConnections()
    const owner = new OwnedResources()
    const caller = new OwnedResources()
    const kind = createConnectionKind<FakeValue>('fake.widget')
    const connector = new FakeConnector('fake.generations', 'Generations', kind)
    connections.forScope(owner).add(connector)

    const handles = []
    for (let index = 0; index < 3; index += 1) {
      handles.push(await connections.open(caller, 'fake.generations', kind))
    }
    expect(new Set(handles.map(handle => handle.instanceId)).size).toBe(3)
    expect(new Set(handles.map(handle => handle.value)).size).toBe(3)
    for (const handle of handles) expect(handle.connectorId).toBe('fake.generations')

    // Closing one generation must not touch the identity or state of the rest.
    expect(await handles[0]!.close()).toEqual({ status: 'closed' })
    expect(handles[1]!.getSnapshot()).toMatchObject({ instanceId: handles[1]!.instanceId, state: 'connected' })
    expect(handles[2]!.getSnapshot()).toMatchObject({ instanceId: handles[2]!.instanceId, state: 'connected' })
    expect(connector.endpoints[1]!.closeLocalCalls).toBe(0)
    expect(connector.endpoints[2]!.closeLocalCalls).toBe(0)

    caller.dispose()
    owner.dispose()
    lifetime.dispose()
  })
})

// ---------------------------------------------------------------------------
// §5.5 — the settlement report is a neutral, cumulative, exact shape.
// ---------------------------------------------------------------------------

describe('T009-02 §5.5 — settlement report shape', () => {
  it('resolves immediately on a fresh service with exactly the two neutral arrays', async () => {
    const { lifetime, connections } = newConnections()
    const report = await connections.whenSettled()
    expect(Object.keys(report).sort()).toEqual(['closeFailures', 'lateOpenClosures'])
    expect(report).not.toHaveProperty('pendingReleases')
    expect(report).toEqual({ lateOpenClosures: [], closeFailures: [] })
    expect(Object.isFrozen(report)).toBe(true)
    expect(Object.isFrozen(report.lateOpenClosures)).toBe(true)
    expect(Object.isFrozen(report.closeFailures)).toBe(true)
    lifetime.dispose()
  })

  it('a clean local release adds nothing to either cumulative list', async () => {
    const { lifetime, connections } = newConnections()
    const owner = new OwnedResources()
    const caller = new OwnedResources()
    const kind = createConnectionKind<FakeValue>('fake.widget')
    const connector = new FakeConnector('fake.clean', 'Clean', kind)
    connections.forScope(owner).add(connector)

    const handle = await connections.open(caller, 'fake.clean', kind)
    expect(await handle.close()).toEqual({ status: 'closed' })
    const report = await connections.whenSettled()
    expect(report.lateOpenClosures).toEqual([])
    expect(report.closeFailures).toEqual([])

    caller.dispose()
    owner.dispose()
    lifetime.dispose()
  })

  it('a failed late-open release is recorded as {closed:false,error} and never rethrown into dispose', async () => {
    const { lifetime, connections } = newConnections()
    const owner = new OwnedResources()
    const caller = new OwnedResources()
    const kind = createConnectionKind<FakeValue>('fake.widget')
    const connector = new FakeConnector('fake.late-fail', 'Late fail', kind)
    connections.forScope(owner).add(connector)

    const gate = deferred<ConnectionEndpoint<FakeValue>>()
    connector.openBehavior = () => gate.promise
    let outcome = 'pending'
    connections.open(caller, 'fake.late-fail', kind)
      .then(() => { outcome = 'resolved' }, () => { outcome = 'rejected' })
    await flush()

    caller.dispose()
    const endpoint = connector.makeEndpoint()
    endpoint.closeLocalResult = Promise.reject(new Error('late release failed'))
    gate.resolve(endpoint)
    await flush()
    await flush()

    // whenSettled() must await the recorded failure without swallowing it and
    // without an unhandled rejection escaping the scope dispose.
    const report = await connections.whenSettled()
    expect(outcome).toBe('rejected')
    expect(endpoint.closeLocalCalls).toBe(1)
    expect(report.lateOpenClosures).toHaveLength(1)
    const record = report.lateOpenClosures[0]!
    expect(record).toEqual({
      connectorId: 'fake.late-fail',
      instanceId: expect.any(String),
      closed: false,
      error: expect.stringContaining('late release failed'),
    })
    expect(Object.keys(record).sort()).toEqual(['closed', 'connectorId', 'error', 'instanceId'])
    expect(report.closeFailures).toEqual([])

    owner.dispose()
    lifetime.dispose()
  })
})

// ---------------------------------------------------------------------------
// §5.4 — CloseOutcome is the local vocabulary; failures are honest.
// ---------------------------------------------------------------------------

describe('T009-02 §3/§5.4 — CloseOutcome never dresses up a remote verdict', () => {
  it("produces exactly {status:'closed'} or {status:'close_failed',error} — never 'released'/'remote-stopped'", async () => {
    const { lifetime, connections } = newConnections()
    const owner = new OwnedResources()
    const caller = new OwnedResources()
    const kind = createConnectionKind<FakeValue>('fake.widget')
    const connector = new FakeConnector('fake.vocab', 'Vocab', kind)
    connections.forScope(owner).add(connector)

    const handle = await connections.open(caller, 'fake.vocab', kind)
    const success = await handle.close()
    expect(success).toEqual({ status: 'closed' })
    expect(Object.keys(success)).toEqual(['status'])

    const failing = await connections.open(caller, 'fake.vocab', kind)
    connector.endpoints[1]!.closeLocalResult = Promise.reject(new Error('local release refused'))
    const failed = await failing.close()
    expect(failed).toEqual({ status: 'close_failed', error: expect.stringContaining('local release refused') })
    expect(Object.keys(failed).sort()).toEqual(['error', 'status'])

    // Enumerate the real values one by one; there is no third member.
    const observed: Array<CloseOutcome['status']> = [success.status, failed.status]
    expect(observed).toEqual(['closed', 'close_failed'])
    for (const outcome of [success, failed]) {
      expect(['closed', 'close_failed']).toContain(outcome.status)
      expect(outcome.status).not.toBe('released')
      expect(outcome.status).not.toBe('remote-stopped')
      expect(JSON.stringify(outcome)).not.toMatch(/remote|stopped|released/)
    }

    // The failure is recorded as a LOCAL release failure with the exact shape.
    const report = await connections.whenSettled()
    expect(report.closeFailures).toHaveLength(1)
    expect(report.closeFailures[0]).toEqual({
      connectorId: 'fake.vocab',
      instanceId: failing.instanceId,
      error: expect.stringContaining('local release refused'),
    })
    expect(Object.keys(report.closeFailures[0]!).sort()).toEqual(['connectorId', 'error', 'instanceId'])

    caller.dispose()
    owner.dispose()
    lifetime.dispose()
  })
})

// ---------------------------------------------------------------------------
// §5.2/§5.3 — late open after scope close; release path is idempotent.
// ---------------------------------------------------------------------------

describe('T009-02 §5.2/§5.3 — late open release is exactly once and idempotent', () => {
  it('a resolve after caller scope close is released once; repeated teardown/settlement cannot double-release', async () => {
    // Counterexample sensitivity: repeating a scope's dispose, or re-reading
    // whenSettled(), must not release the late endpoint a second time nor add a
    // duplicate settlement entry.
    const { lifetime, connections } = newConnections()
    const owner = new OwnedResources()
    const caller = new OwnedResources()
    const kind = createConnectionKind<FakeValue>('fake.widget')
    const connector = new FakeConnector('fake.late-idem', 'Late idem', kind)
    connections.forScope(owner).add(connector)

    const gate = deferred<ConnectionEndpoint<FakeValue>>()
    connector.openBehavior = () => gate.promise
    let outcome = 'pending'
    connections.open(caller, 'fake.late-idem', kind)
      .then(() => { outcome = 'resolved' }, () => { outcome = 'rejected' })
    await flush()

    caller.dispose()
    caller.dispose() // repeated dispose must not enqueue a second release
    const endpoint = connector.makeEndpoint()
    gate.resolve(endpoint)
    await flush()
    await flush()

    expect(outcome).toBe('rejected')
    expect(endpoint.closeLocalCalls).toBe(1)

    const first = await connections.whenSettled()
    owner.dispose()
    owner.dispose()
    lifetime.dispose()
    lifetime.dispose()
    const second = await connections.whenSettled()

    expect(endpoint.closeLocalCalls).toBe(1)
    expect(first.lateOpenClosures).toEqual([
      { connectorId: 'fake.late-idem', instanceId: expect.any(String), closed: true },
    ])
    expect(Object.keys(first.lateOpenClosures[0]!).sort()).toEqual(['closed', 'connectorId', 'instanceId'])
    expect(second).toEqual(first)
    expect(connections.getSnapshot().instances).toEqual([])
  })
})

// ---------------------------------------------------------------------------
// §5.4 — missing condition: repeated close is idempotent and never throws.
// ---------------------------------------------------------------------------

describe('T009-02 §5.4 — repeated close is idempotent and never throws', () => {
  it('sequential and concurrent duplicate closes all settle closed with one closeLocal', async () => {
    const { lifetime, connections } = newConnections()
    const owner = new OwnedResources()
    const caller = new OwnedResources()
    const kind = createConnectionKind<FakeValue>('fake.widget')
    const connector = new FakeConnector('fake.idem', 'Idem', kind)
    connections.forScope(owner).add(connector)

    const handle = await connections.open(caller, 'fake.idem', kind)
    const endpoint = connector.endpoints[0]!
    const results = await Promise.all([handle.close(), handle.close(), handle.close()])
    for (const result of results) expect(result).toEqual({ status: 'closed' })
    expect(endpoint.closeLocalCalls).toBe(1)

    // Post-close repeats (before and after scope/service teardown) also no-op.
    for (let attempt = 0; attempt < 3; attempt += 1) {
      await expect(handle.close()).resolves.toEqual({ status: 'closed' })
    }
    caller.dispose()
    owner.dispose()
    lifetime.dispose()
    await expect(handle.close()).resolves.toEqual({ status: 'closed' })
    expect(endpoint.closeLocalCalls).toBe(1)
  })

  it('close() after the caller scope already released the handle joins the settled result, no throw, no second release', async () => {
    const { lifetime, connections } = newConnections()
    const owner = new OwnedResources()
    const caller = new OwnedResources()
    const kind = createConnectionKind<FakeValue>('fake.widget')
    const connector = new FakeConnector('fake.join', 'Join', kind)
    connections.forScope(owner).add(connector)

    const handle = await connections.open(caller, 'fake.join', kind)
    const endpoint = connector.endpoints[0]!
    caller.dispose() // implicit local release starts synchronously

    await expect(handle.close()).resolves.toEqual({ status: 'closed' })
    expect(endpoint.closeLocalCalls).toBe(1)
    const report = await connections.whenSettled()
    expect(report.closeFailures).toEqual([])
    expect(report.lateOpenClosures).toEqual([])

    owner.dispose()
    lifetime.dispose()
  })
})
