// T026 — CN acceptance tests for @ordessa/connections (tests-first, contract C6 §7).
// Every test drives ONLY the platform API (@ordessa/connections/api) plus the
// fixed capability entry createConnections(lifetime); all counterparties are
// controlled in-memory fakes — no Electron, no real transports, no Agent /
// Workbench / ACP / Server involvement.
//
// CURRENT STATE (T026): createConnections is an explicit stub that throws
// "Connections platform not implemented (T027)" — every test below must be RED
// with that error. This is honest red, not fake green; T027 implements the
// platform and turns these tests green without editing assertions here.

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { OwnedResources } from '@ordessa/extension-api'
import {
  ConnectionsToken,
  createConnectionKind,
  type ConnectionEndpoint,
  type ConnectionKind,
  type Connections,
  type Connector,
} from '@ordessa/connections/api'
import { createConnections } from '../src/index'

// ---------------------------------------------------------------------------
// Controlled fakes — protocol-neutral, in-memory only.
// ---------------------------------------------------------------------------

interface FakeValue { label: string }

/** A fake endpoint owning a recording "transport" (CN-06 model).
 *  The transport is reachable ONLY through this module's closures: the platform
 *  has no handle to it, so `transportCalls` proves every action the platform
 *  performed against the low-level connection. closeLocal is the sole door. */
class FakeEndpoint implements ConnectionEndpoint<FakeValue> {
  readonly value: FakeValue
  readonly transportCalls: string[] = []
  closeLocalCalls = 0
  /** Swappable so tests can gate/reject the local release. */
  closeLocalResult: Promise<void> = Promise.resolve()

  constructor(label: string) { this.value = { label } }

  closeLocal(): Promise<void> {
    this.closeLocalCalls += 1
    this.transportCalls.push('closeLocal')
    return this.closeLocalResult
  }
}

class FakeConnector implements Connector<FakeValue> {
  readonly openCalls: AbortSignal[] = []
  readonly endpoints: FakeEndpoint[] = []
  openBehavior?: (signal: AbortSignal) => Promise<ConnectionEndpoint<FakeValue>>

  constructor(readonly id: string, readonly title: string, readonly kind: ConnectionKind<FakeValue>) {}

  open(signal: AbortSignal): Promise<ConnectionEndpoint<FakeValue>> {
    this.openCalls.push(signal)
    return this.openBehavior
      ? this.openBehavior(signal)
      : Promise.resolve(this.makeEndpoint())
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
  // The ONLY capability entry (contract §3). T026 stub throws here — honestly red.
  const connections = createConnections(lifetime)
  return { lifetime, connections }
}

function register(connections: Connections, owner: OwnedResources, connector: FakeConnector): void {
  connections.forScope(owner).add(connector)
}

// ---------------------------------------------------------------------------
// CN-01 — full lifecycle with only the platform + a non-Agent connector.
// ---------------------------------------------------------------------------

describe('CN-01 lifecycle', () => {
  it('registers, opens, exposes value/snapshot/subscribe, closes, and marks closed', async () => {
    // Counterexample sensitivity (contract §7 CN-01): if the platform required
    // Agent or an enabled Workbench to function, the static gate below or the
    // plain platform-only flow here would go red. Nothing outside
    // @ordessa/extension-api is (or may become) imported by api/ or src/.

    // Static dependency wall: api + src import only @ordessa/extension-api
    // (Token/ResourceScope/IDisposable) and relative paths; package.json must
    // carry no React/Workbench/Agent/ACP/Server/Harness/Profile/Pacthold/Electron dep.
    const forbidden = /(react|workbench|agent|acp|server|harness|profile|pacthold|electron)/i
    const packageRoot = fileURLToPath(new URL('..', import.meta.url))
    for (const rel of ['api/connections.ts', 'src/index.ts']) {
      const text = readFileSync(new URL(`../${rel}`, import.meta.url), 'utf8')
      for (const m of text.matchAll(/from\s+['"]([^'"]+)['"]/g)) {
        expect(m[1], `forbidden import in ${rel}`).not.toMatch(forbidden)
      }
    }
    const pkg = JSON.parse(readFileSync(`${packageRoot}package.json`, 'utf8'))
    for (const field of ['dependencies', 'devDependencies', 'peerDependencies']) {
      for (const name of Object.keys(pkg[field] ?? {})) {
        expect(name, `forbidden dependency ${name}`).not.toMatch(forbidden)
      }
    }
    // The API surface is importable with zero side effects and exposes the
    // token construction site of this module (used below as a presence check).
    expect(ConnectionsToken).toBeTruthy()

    const { connections } = newConnections()
    const owner = new OwnedResources()
    const caller = new OwnedResources()
    const kind = createConnectionKind<FakeValue>('fake.widget')
    const connector = new FakeConnector('fake.one', 'Fake one', kind)
    register(connections, owner, connector)

    expect(connections.getSnapshot().connectors).toContainEqual(
      expect.objectContaining({ id: 'fake.one', title: 'Fake one' }))

    let notifications = 0
    const unsubscribe = connections.subscribe(() => { notifications += 1 })

    const handle = await connections.open(caller, 'fake.one', kind)
    // Registration + open must have notified subscribers.
    expect(notifications).toBeGreaterThan(0)
    expect(handle.connectorId).toBe('fake.one')
    expect(handle.instanceId).toBeTruthy()
    // The endpoint value crosses through unchanged.
    expect(handle.value).toBe(connector.endpoints[0]!.value)
    expect(handle.getSnapshot()).toMatchObject({ instanceId: handle.instanceId, state: 'connected' })
    expect(connections.getSnapshot().instances)
      .toContainEqual(expect.objectContaining({ instanceId: handle.instanceId, state: 'connected' }))

    // Close: observable 'closing' while closeLocal is pending, then closed.
    const gate = deferred()
    connector.endpoints[0]!.closeLocalResult = gate.promise
    const closing = handle.close()
    await flush()
    expect(handle.getSnapshot().state).toBe('closing')
    expect(connections.getSnapshot().instances)
      .toContainEqual(expect.objectContaining({ instanceId: handle.instanceId, state: 'closing' }))
    gate.resolve()
    expect(await closing).toEqual({ status: 'closed' })
    expect(connector.endpoints[0]!.closeLocalCalls).toBe(1)
    expect(handle.getSnapshot().state).toBe('closed')
    // Closed record leaves the live platform view (§5.6: only unconfirmed records persist).
    expect(connections.getSnapshot().instances.find(i => i.instanceId === handle.instanceId)).toBeUndefined()

    unsubscribe()
    caller.dispose()
    owner.dispose()
  })
})

// ---------------------------------------------------------------------------
// CN-02 — rejections happen BEFORE connector.open is ever called.
// ---------------------------------------------------------------------------

describe('CN-02 rejection gates', () => {
  it('unknown connector id rejects with zero connector.open calls', async () => {
    // Counterexample sensitivity: removing the registration lookup would let
    // connector.open be reached (openCalls > 0) or open resolve — either turns red.
    const { connections } = newConnections()
    const caller = new OwnedResources()
    const kind = createConnectionKind<FakeValue>('fake.widget')
    await expect(connections.open(caller, 'not.registered', kind)).rejects.toThrow()
    expect(connections.getSnapshot().instances).toEqual([])
    caller.dispose()
  })

  it('kind mismatch rejects on runtime identity, not on names or casts', async () => {
    // Counterexample sensitivity: an implementation comparing kind.displayName
    // (or doing type-erasure-only checks) would wrongly accept the lookalike
    // kind or the cast duplicate below and connector.openCalls would go > 0.
    const { connections } = newConnections()
    const owner = new OwnedResources()
    const caller = new OwnedResources()
    const kindA = createConnectionKind<FakeValue>('fake.widget')
    const kindB = createConnectionKind<FakeValue>('fake.other')
    const connector = new FakeConnector('fake.kinds', 'Kinds', kindA)
    register(connections, owner, connector)

    await expect(connections.open(caller, 'fake.kinds', kindB)).rejects.toThrow(/kind/i)
    // Same display name, different instance => different kind (identity is ===).
    const lookalike = createConnectionKind<FakeValue>('fake.widget')
    await expect(connections.open(caller, 'fake.kinds', lookalike)).rejects.toThrow(/kind/i)
    // A generic cast must not fake a kind match at runtime.
    await expect(connections.open(caller, 'fake.kinds', kindB as unknown as typeof kindA)).rejects.toThrow(/kind/i)

    expect(connector.openCalls).toHaveLength(0)
    caller.dispose()
    owner.dispose()
  })

  it('caller scope already closed rejects before connector.open', async () => {
    const { connections } = newConnections()
    const owner = new OwnedResources()
    const caller = new OwnedResources()
    const kind = createConnectionKind<FakeValue>('fake.widget')
    const connector = new FakeConnector('fake.caller', 'Caller', kind)
    register(connections, owner, connector)
    caller.dispose()
    await expect(connections.open(caller, 'fake.caller', kind)).rejects.toThrow()
    expect(connector.openCalls).toHaveLength(0)
    owner.dispose()
  })

  it('registrant scope closed removes the registration and rejects before connector.open', async () => {
    const { connections } = newConnections()
    const owner = new OwnedResources()
    const caller = new OwnedResources()
    const kind = createConnectionKind<FakeValue>('fake.widget')
    const connector = new FakeConnector('fake.owner', 'Owner', kind)
    register(connections, owner, connector)
    owner.dispose()
    expect(connections.getSnapshot().connectors.find(c => c.id === 'fake.owner')).toBeUndefined()
    await expect(connections.open(caller, 'fake.owner', kind)).rejects.toThrow()
    expect(connector.openCalls).toHaveLength(0)
    caller.dispose()
  })

  it('duplicate connector id is rejected at registration with a clear error', () => {
    // Counterexample sensitivity: a second generic registry silently overwriting
    // ids would make the throws() below pass-through red.
    const { connections } = newConnections()
    const owner = new OwnedResources()
    const kind = createConnectionKind<FakeValue>('fake.widget')
    register(connections, owner, new FakeConnector('fake.dup', 'First', kind))
    expect(() => connections.forScope(new OwnedResources()).add(
      new FakeConnector('fake.dup', 'Second', kind))).toThrow(/fake\.dup/)
    expect(connections.getSnapshot().connectors.filter(c => c.id === 'fake.dup')).toHaveLength(1)
    owner.dispose()
  })
})

// ---------------------------------------------------------------------------
// CN-03 — late resolve after invalidation: close exactly once, never visible.
// ---------------------------------------------------------------------------

describe('CN-03 late resolve', () => {
  async function lateResolveScenario(unmount: 'caller' | 'owner') {
    const { connections } = newConnections()
    const owner = new OwnedResources()
    const caller = new OwnedResources()
    const kind = createConnectionKind<FakeValue>('fake.widget')
    const connector = new FakeConnector('fake.late', 'Late', kind)
    register(connections, owner, connector)

    const seenStates: string[] = []
    const unsubscribe = connections.subscribe(() => {
      seenStates.push(...connections.getSnapshot().instances.map(i => i.state))
    })

    const gate = deferred<ConnectionEndpoint<FakeValue>>()
    connector.openBehavior = () => gate.promise
    let outcome = 'pending'
    const opening = connections.open(caller, 'fake.late', kind)
    opening.then(() => { outcome = 'resolved' }, () => { outcome = 'rejected' })
    await flush()
    expect(connector.openCalls).toHaveLength(1)

    if (unmount === 'caller') caller.dispose()
    else owner.dispose()

    // The open resolves only AFTER the scope unmount (§5.3).
    const endpoint = connector.makeEndpoint()
    gate.resolve(endpoint)
    await flush()
    await flush()

    // Counterexample sensitivity: removing the late cleanup (or double-closing,
    // or delivering the handle) makes one of these red.
    expect(outcome).toBe('rejected')
    expect(endpoint.closeLocalCalls).toBe(1)
    expect(endpoint.transportCalls).toEqual(['closeLocal'])
    // Never appeared as a usable instance for anyone...
    expect(seenStates).not.toContain('connected')
    expect(connections.getSnapshot().instances).toEqual([])
    // ...and the already-unmounted view was not notified of a connected state.
    unsubscribe()
    if (unmount === 'owner') caller.dispose()
  }

  it('open resolving after the CALLER scope disposed is closed exactly once and never surfaces', async () => {
    await lateResolveScenario('caller')
  })

  it('open resolving after the REGISTRANT scope unmounted is closed exactly once and never surfaces', async () => {
    await lateResolveScenario('owner')
  })
})

// ---------------------------------------------------------------------------
// CN-04 — independent instances per scope; no pooling by connector id.
// ---------------------------------------------------------------------------

describe('CN-04 instance independence', () => {
  it('two scopes open distinct instances from one connector id; closing one leaves the other fully usable', async () => {
    // Counterexample sensitivity: a pool/singleton keyed by connector id would
    // share value/instanceId, or the first close would drop the second scope's
    // instance from the snapshot / close its endpoint — each red below.
    const { connections } = newConnections()
    const owner = new OwnedResources()
    const scopeA = new OwnedResources()
    const scopeB = new OwnedResources()
    const kind = createConnectionKind<FakeValue>('fake.widget')
    const connector = new FakeConnector('fake.shared', 'Shared', kind)
    register(connections, owner, connector)

    const handleA = await connections.open(scopeA, 'fake.shared', kind)
    const handleB = await connections.open(scopeB, 'fake.shared', kind)

    expect(handleA.instanceId).not.toBe(handleB.instanceId)
    expect(handleA.value).not.toBe(handleB.value)
    expect(connector.endpoints).toHaveLength(2)

    expect((await handleA.close()).status).toBe('closed')
    // A's close touched ONLY A's endpoint.
    expect(connector.endpoints[0]!.closeLocalCalls).toBe(1)
    expect(connector.endpoints[1]!.closeLocalCalls).toBe(0)
    // B remains fully usable.
    expect(handleB.getSnapshot().state).toBe('connected')
    expect(connections.getSnapshot().instances)
      .toContainEqual(expect.objectContaining({ instanceId: handleB.instanceId, state: 'connected' }))
    expect((await handleB.close()).status).toBe('closed')
    expect(connector.endpoints[1]!.closeLocalCalls).toBe(1)

    scopeA.dispose()
    scopeB.dispose()
    owner.dispose()
  })
})

// ---------------------------------------------------------------------------
// CN-05 — close coalescing and honest close_failed + explicit retry.
// ---------------------------------------------------------------------------

describe('CN-05 close semantics', () => {
  it('concurrent and duplicate closes on one handle coalesce into a single pending closeLocal', async () => {
    // Counterexample sensitivity: a non-coalescing implementation calls
    // closeLocal twice (red on the counter); an optimistic one resolves
    // 'closed' before the gate opens (red on ordering).
    const { connections } = newConnections()
    const owner = new OwnedResources()
    const caller = new OwnedResources()
    const kind = createConnectionKind<FakeValue>('fake.widget')
    const connector = new FakeConnector('fake.coalesce', 'Coalesce', kind)
    register(connections, owner, connector)
    const handle = await connections.open(caller, 'fake.coalesce', kind)
    const endpoint = connector.endpoints[0]!

    const gate = deferred()
    endpoint.closeLocalResult = gate.promise
    const first = handle.close()
    const second = handle.close()
    await flush()
    expect(endpoint.closeLocalCalls).toBe(1)
    gate.resolve()
    expect(await first).toEqual({ status: 'closed' })
    expect(await second).toEqual({ status: 'closed' })
    expect(endpoint.closeLocalCalls).toBe(1)

    caller.dispose()
    owner.dispose()
  })

  it('a rejecting closeLocal yields close_failed without marking closed; an explicit retry can succeed; no auto loop', async () => {
    // Counterexample sensitivity: swallowing the rejection or optimistically
    // marking 'closed' fails the state/outcome assertions; an automatic retry
    // loop drives closeLocalCalls beyond the number of explicit closes.
    const { connections } = newConnections()
    const owner = new OwnedResources()
    const caller = new OwnedResources()
    const kind = createConnectionKind<FakeValue>('fake.widget')
    const connector = new FakeConnector('fake.retry', 'Retry', kind)
    register(connections, owner, connector)
    const handle = await connections.open(caller, 'fake.retry', kind)
    const endpoint = connector.endpoints[0]!

    const gate = deferred()
    endpoint.closeLocalResult = gate.promise
    const closing = handle.close()
    gate.reject(new Error('release boom'))
    const outcome = await closing
    expect(outcome.status).toBe('close_failed')
    if (outcome.status === 'close_failed') expect(outcome.error).toContain('release boom')
    // Not closed (§5.4) and the record stays visible for diagnosis (§5.6).
    expect(handle.getSnapshot().state).not.toBe('closed')
    expect(connections.getSnapshot().instances)
      .toContainEqual(expect.objectContaining({ instanceId: handle.instanceId, state: 'close_failed' }))

    // Explicit retry only — no automatic loop happened in the meantime.
    expect(endpoint.closeLocalCalls).toBe(1)
    endpoint.closeLocalResult = Promise.resolve()
    expect(await handle.close()).toEqual({ status: 'closed' })
    expect(endpoint.closeLocalCalls).toBe(2)
    expect(handle.getSnapshot().state).toBe('closed')
    expect(connections.getSnapshot().instances.find(i => i.instanceId === handle.instanceId)).toBeUndefined()

    caller.dispose()
    owner.dispose()
  })
})

// ---------------------------------------------------------------------------
// CN-06 — transport ownership: exactly one local close, zero side-channel actions.
// ---------------------------------------------------------------------------

describe('CN-06 transport ownership', () => {
  it('the platform reaches the connector-owned transport only through closeLocal, at most once per handle, and triggers no extra actions', async () => {
    // The FakeEndpoint's recording transport is unreachable except via
    // closeLocal (contract §4: one close owner). Any implicit remote cancel /
    // release / second close would either bump the counter or appear in
    // transportCalls — both red here.
    const { connections } = newConnections()
    const owner = new OwnedResources()
    const caller = new OwnedResources()
    const kind = createConnectionKind<FakeValue>('fake.widget')
    const connector = new FakeConnector('fake.transport', 'Transport', kind)
    register(connections, owner, connector)
    const handle = await connections.open(caller, 'fake.transport', kind)
    const endpoint = connector.endpoints[0]!

    // Opening performs zero transport-side actions beyond the connector's own.
    expect(endpoint.transportCalls).toEqual([])

    expect(await handle.close()).toEqual({ status: 'closed' })
    expect(endpoint.transportCalls).toEqual(['closeLocal'])
    expect(endpoint.closeLocalCalls).toBe(1)

    // Post-close close is a no-op join, and scope teardown after a settled
    // close must NOT re-close the endpoint.
    expect(await handle.close()).toEqual({ status: 'closed' })
    caller.dispose()
    owner.dispose()
    await flush()
    const report = await connections.whenSettled()
    expect(endpoint.closeLocalCalls).toBe(1)
    expect(endpoint.transportCalls).toEqual(['closeLocal'])
    expect(report.closeFailures).toEqual([])
    expect(report.lateOpenClosures).toEqual([])
  })
})

// ---------------------------------------------------------------------------
// §5 rules implied by the CN table: open cancellation + scope settlement.
// ---------------------------------------------------------------------------

describe('§5 cancellation and settlement', () => {
  it('aborting the caller signal cancels a not-yet-finished open and a later resolve still closes exactly once', async () => {
    // Counterexample sensitivity (§5.2/§5.3): a platform that never aborts the
    // signal, resolves a cancelled open, or forgets the late cleanup fails here.
    const { connections } = newConnections()
    const owner = new OwnedResources()
    const caller = new OwnedResources()
    const kind = createConnectionKind<FakeValue>('fake.widget')
    const connector = new FakeConnector('fake.abort', 'Abort', kind)
    register(connections, owner, connector)

    const controller = new AbortController()
    const gate = deferred<ConnectionEndpoint<FakeValue>>()
    connector.openBehavior = () => gate.promise
    let outcome = 'pending'
    const opening = connections.open(caller, 'fake.abort', kind, { signal: controller.signal })
    opening.then(() => { outcome = 'resolved' }, () => { outcome = 'rejected' })
    await flush()
    expect(connector.openCalls).toHaveLength(1)
    expect(connector.openCalls[0]!.aborted).toBe(false)

    controller.abort()
    await flush()
    expect(outcome).toBe('rejected')
    expect(connector.openCalls[0]!.aborted).toBe(true)

    // The connector completes after cancellation: the endpoint must be
    // released exactly once and never surfaced.
    const endpoint = connector.makeEndpoint()
    gate.resolve(endpoint)
    await flush()
    await flush()
    expect(outcome).toBe('rejected')
    expect(endpoint.closeLocalCalls).toBe(1)
    expect(connections.getSnapshot().instances).toEqual([])

    caller.dispose()
    owner.dispose()
  })

  it('synchronous scope dispose only starts cleanup; whenSettled reports late-open closures and close failures without swallowing rejections', async () => {
    // Counterexample sensitivity (§5.5/§5.6): a dispose that awaits nothing and
    // claims completion (no 'closing' observation), one that drops close
    // failures, one that leaks an unhandled rejection, or one that loses the
    // late-open closure all go red below.
    const { connections } = newConnections()
    const owner = new OwnedResources()
    const kind = createConnectionKind<FakeValue>('fake.widget')

    // (a) handle whose implicit dispose-close will FAIL.
    const failing = new FakeConnector('fake.failing-close', 'Failing', kind)
    register(connections, owner, failing)
    const caller1 = new OwnedResources()
    const handle = await connections.open(caller1, 'fake.failing-close', kind)
    const endpoint = failing.endpoints[0]!
    const closeGate = deferred()
    endpoint.closeLocalResult = closeGate.promise

    // (b) open still pending on another scope that will unmount first.
    const late = new FakeConnector('fake.late-open', 'Late', kind)
    register(connections, owner, late)
    const caller2 = new OwnedResources()
    const openGate = deferred<ConnectionEndpoint<FakeValue>>()
    late.openBehavior = () => openGate.promise
    let lateOutcome = 'pending'
    connections.open(caller2, 'fake.late-open', kind)
      .then(() => { lateOutcome = 'resolved' }, () => { lateOutcome = 'rejected' })
    await flush()

    caller1.dispose() // §5.5: synchronous dispose only STARTS async cleanup.
    expect(endpoint.closeLocalCalls).toBe(1)
    // Record stays visible, unconfirmed (§5.6: UI removal is not proof of close).
    expect(connections.getSnapshot().instances)
      .toContainEqual(expect.objectContaining({ instanceId: handle.instanceId, state: 'closing' }))

    caller2.dispose()
    closeGate.reject(new Error('boom on dispose'))
    const lateEndpoint = late.makeEndpoint()
    openGate.resolve(lateEndpoint)

    const report = await connections.whenSettled()
    expect(lateOutcome).toBe('rejected')
    expect(lateEndpoint.closeLocalCalls).toBe(1)
    expect(report.lateOpenClosures).toEqual(
      [expect.objectContaining({ connectorId: 'fake.late-open', closed: true })])
    expect(report.closeFailures).toHaveLength(1)
    expect(report.closeFailures[0]).toMatchObject({ connectorId: 'fake.failing-close', instanceId: handle.instanceId })
    expect(report.closeFailures[0]!.error).toContain('boom on dispose')
    // The failed record remains available for host diagnosis (§5.6).
    expect(connections.getSnapshot().instances)
      .toContainEqual(expect.objectContaining({ instanceId: handle.instanceId, state: 'close_failed' }))

    owner.dispose()
  })
})
